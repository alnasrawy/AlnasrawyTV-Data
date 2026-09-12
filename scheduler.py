"""Smart scheduler: daily rollover + idle/active sleep loop.

Three modes:

- **daily** — once per day (~01:00 Baghdad): refetch yesterday (final
  results) + today + tomorrow, store the day plan, compute first/last
  kickoff of the day.
- **idle** — nothing near now: quick wake-ups every ``idle_interval``
  (default 20 min) to re-check whether the nearest match is approaching.
  No blind multi-hour ``time.sleep()``.
- **active** — a match is starting soon or a match of the day is still
  unfinished: poll every ``active_interval`` (default 5 min); send
  prematch cards <=10 min before kickoff and fulltime cards as soon as
  a match ends. Re-verifies kickoff times from the site on every tick.
  Stays active until the *last* match of the day has ended.

State (dedup) lives in :mod:`state_store`; cards in :mod:`renderer`;
transport in :mod:`notify`. The clock is injectable so tests can fast
forward time without real waits.
"""

from __future__ import annotations

import logging
import pathlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional, Protocol
from zoneinfo import ZoneInfo

from data_layer.fetcher import Fetcher
from data_layer.filters import filter_championships
from data_layer.main import load_day
from data_layer.models import Match, Team
from data_layer.parser import parse_fixtures_html, parse_match_details_html
from notify import LogPublisher, build_publisher, Notifier, Publisher
from renderer import render_fulltime_image, render_prematch_image
from state_store import (
    EVENT_FULLTIME,
    EVENT_PREMATCH,
    already_sent,
    get_daily_plan,
    mark_sent,
    save_daily_plan,
    update_match_status,
)

logger = logging.getLogger("scheduler")

BAGHDAD = ZoneInfo("Asia/Baghdad")

MODE_IDLE = "idle"
MODE_ACTIVE = "active"


# ── configuration / clock ──────────────────────────────────────────────────


@dataclass
class SchedulerConfig:
    tz: ZoneInfo = BAGHDAD
    idle_interval: float = 20 * 60          # seconds between idle wake-ups
    active_interval: float = 5 * 60         # seconds between active polls
    prematch_window: float = 10 * 60        # seconds before kickoff to announce
    max_fetch_failures: int = 3             # consecutive failures before alerting
    image_dir: pathlib.Path = pathlib.Path(__file__).resolve().parent / "out_imgs"


class Clock(Protocol):
    def now(self) -> datetime: ...
    def sleep(self, seconds: float) -> None: ...


class RealClock(Clock):
    def now(self) -> datetime:
        return datetime.now(BAGHDAD)

    def sleep(self, seconds: float) -> None:
        import time

        time.sleep(seconds)


# ── site access (full step-1 pipeline) ────────────────────────────────────


class SiteFetcher:
    """Thin adapter over data_layer used by the scheduler."""

    def __init__(self) -> None:
        self._fetcher = Fetcher()

    def full_plan(self, ref_date: datetime.date) -> list[Match]:
        """Yesterday + today + tomorrow, each fully enriched (details)."""
        out: list[Match] = []
        for day in (ref_date - timedelta(days=1), ref_date, ref_date + timedelta(days=1)):
            for champ in filter_championships(load_day(self._fetcher, day)):
                out.extend(champ.matches)
        return out

    def refresh_fixtures(self, days: list[datetime.date]) -> dict[str, Match]:
        """Light list-level refresh: current kickoff / status / score."""
        out: dict[str, Match] = {}
        today = BAGHDAD and datetime.now(BAGHDAD).date()
        for day in set(days):
            html = (
                self._fetcher.fetch_fixtures_html()
                if day == today
                else self._fetcher.fetch_matches_html_for_date(day)
            )
            for champ in filter_championships(parse_fixtures_html(html, day)):
                for m in champ.matches:
                    out[m.match_id] = m
        return out

    def fetch_detail(self, match: Match) -> None:
        """Pull the detail page for one match (goals, score, commentary)."""
        html = self._fetcher.fetch_match_page(match.source_url)
        parse_match_details_html(match, html)


# ── scheduler ──────────────────────────────────────────────────────────────


class Scheduler:
    """Main run loop; inject anything non-standard for tests."""

    def __init__(
        self,
        *,
        fetcher: Optional[object] = None,
        publisher: Optional[Publisher] = None,
        notifier: Optional[Notifier] = None,
        config: Optional[SchedulerConfig] = None,
        clock: Optional[Clock] = None,
        render_prematch: Optional[Callable[..., str]] = None,
        render_fulltime: Optional[Callable[..., str]] = None,
    ) -> None:
        self._fetcher = fetcher or SiteFetcher()
        self._publisher = publisher or build_publisher() or LogPublisher()
        self._notifier = notifier or LogPublisher()
        self.cfg = config or SchedulerConfig()
        self._clock = clock or RealClock()
        self._render_prematch = render_prematch or render_prematch_image
        self._render_fulltime = render_fulltime or render_fulltime_image

        self._matches: dict[str, Match] = {}
        self._last_status: dict[str, str] = {}
        self._plan_ref_date: Optional[datetime.date] = None
        self._mode: Optional[str] = None
        self._consecutive_failures = 0
        self._transitions: list[tuple[datetime, str, str]] = []
        self.cfg.image_dir.mkdir(parents=True, exist_ok=True)

    # ── public ──────────────────────────────────────────────────────────────

    def run(self, max_iterations: int | None = None) -> None:
        """Execute the loop. ``max_iterations`` is for tests only."""
        ticks = 0
        while max_iterations is None or ticks < max_iterations:
            ticks += 1
            try:
                self._tick()
            except Exception as exc:  # noqa: BLE001 — keep the loop alive
                logger.exception("unhandled exception in tick")
                self._notifier.alert(f"خطأ غير متوقع في الحلقة: {exc}")
                self._clock.sleep(self.cfg.active_interval)

    def sweep(self) -> None:
        """Run exactly one cycle — used by the GitHub Actions cron (step 5).
        Each workflow run is a fresh process, so this is like one boot
        (plan built/seeded, all due cards checked, no sleeping)."""
        self._tick(sleep=False)

    def _tick(self, *, sleep: bool = True) -> None:
        now = self._clock.now()
        self._ensure_plan(now)

        self._refresh_and_send(now)
        self._decide_mode(now)
        if not sleep:
            return
        if self._mode == MODE_ACTIVE:
            self._clock.sleep(self.cfg.active_interval)
        else:
            self._clock.sleep(self.cfg.idle_interval)

    def _ensure_plan(self, now: datetime) -> None:
        """Plan is (re)built only when truly needed.

        - A fresh boot (each GitHub cron run is a fresh process) reuses the
          persisted ``daily_plan`` instead of hammering the site with a full
          detail fetch every 10 minutes; the light fixtures refresh below
          re-verifies kickoffs/status.
        - The heavy full fetch happens once per day (first boot with an
          empty store, or daily rollover at/after 01:00 Baghdad).
        """
        if not self._plan_due(now):
            return
        # fresh boot (e.g. each GitHub Actions run) reuses the persisted plan
        # when it still covers today; the light refresh re-verifies it.
        if self._plan_ref_date is None:
            stored = get_daily_plan()
            if self._plan_covers(stored, now.date()):
                self._adopt_stored_plan(stored, now.date())
                self._log(
                    "استخدام الخطة المخزنة | stored plan",
                    f"date={now.date()} matches={len(self._matches)}",
                )
                return
        # first boot ever, or the daily 01:00 rollover -> full reload
        self._daily_cycle(now.date())

    @staticmethod
    def _plan_kickoff(row: dict) -> Optional[datetime]:
        """Reconstruct a Baghdad-aware kickoff from the stored date+time."""
        if not row.get("match_date") or not row.get("match_time"):
            return None
        try:
            return datetime.strptime(
                f"{row['match_date']} {row['match_time']}", "%Y-%m-%d %H:%M"
            ).replace(tzinfo=BAGHDAD)
        except ValueError:
            return None

    @staticmethod
    def _plan_covers(rows: list[dict], today: datetime.date) -> bool:
        for r in rows:
            kickoff = Scheduler._plan_kickoff(r)
            if kickoff is not None and kickoff.date() == today:
                return True
        return False

    def _adopt_stored_plan(
        self, rows: list[dict], ref_date: datetime.date
    ) -> None:
        """Light-weight plan adopted from the SQLite ``daily_plan`` rows.
        The fixtures refresh below replaces these stubs with fresh list
        objects (real team names/logos), and due cards fetch their details.
        """
        self._matches = {}
        for r in rows:
            kickoff = self._plan_kickoff(r)
            m = Match(
                match_id=r["match_id"],
                source_url="",
                home=Team(""), away=Team(""),
                kickoff=kickoff, status=r.get("status", "not_started"),
            )
            self._matches[r["match_id"]] = m
        # seed from the stored statuses so matches that ended while we were
        # offline still fire their fulltime card exactly once.
        self._last_status = {r["match_id"]: r.get("status", "not_started") for r in rows}
        self._plan_ref_date = ref_date

    def _plan_due(self, now: datetime) -> bool:
        """Full replan: first boot, or every day at/after 01:00 Baghdad."""
        date = now.date()
        if self._plan_ref_date is None:
            return True
        if self._plan_ref_date > date:  # wall-clock moved backwards
            return True
        if self._plan_ref_date < date and now.hour >= 1:
            return True
        return False

    def _decide_mode(self, now: datetime) -> None:
        """Idle ⇄ active logic.

        Enter active when a live match exists or one starts within the
        prematch window. Once active, exit ONLY when the *last* match of
        the day has ended (no unfinished match today, nothing upcoming) —
        this is what keeps publishing alive across the whole match day.
        """
        window = self.cfg.prematch_window
        today = now.date()
        live = False
        near = False
        today_unfinished = False
        for m in self._matches.values():
            if m.status == "live":
                live = True
            if m.kickoff is not None:
                remaining = (m.kickoff - now).total_seconds()
                if 0 <= remaining <= window:
                    near = True
                if m.kickoff.astimezone(self.cfg.tz).date() == today \
                        and m.status != "ended":
                    today_unfinished = True

        if self._mode == MODE_ACTIVE:
            new_mode = MODE_IDLE if (not today_unfinished and not near) else MODE_ACTIVE
        else:
            new_mode = MODE_ACTIVE if (live or near) else MODE_IDLE
        self._set_mode(new_mode)

    # ── daily cycle ─────────────────────────────────────────────────────────

    def _daily_cycle(self, ref_date: datetime.date) -> None:
        self._consecutive_failures = 0
        try:
            matches = self._fetcher.full_plan(ref_date)
        except Exception as exc:  # noqa: BLE001
            self._handle_fetch_failure(exc, "daily")
            return  # keep old plan until tomorrow

        self._matches = {m.match_id: m for m in matches}
        # last observed statuses come from the stored plan, so matches that
        # ended while we were offline still fire their fulltime card.
        stored = {r["match_id"]: r["status"] for r in get_daily_plan()}
        self._last_status = {
            m.match_id: stored.get(m.match_id, m.status) for m in matches
        }
        try:
            save_daily_plan(matches)
        except Exception as exc:  # noqa: BLE001
            logger.exception("failed to persist daily plan")

        self._plan_ref_date = ref_date
        day_matches = [
            m for m in matches
            if m.kickoff is not None
            and m.kickoff.astimezone(self.cfg.tz).date() == ref_date
        ]
        first = min((m.kickoff for m in day_matches), default=None)
        last = max((m.kickoff for m in day_matches), default=None)
        self._log(
            "تحميل خطة اليوم | daily",
            f"date={ref_date} matches={len(self._matches)} "
            f"first={first:%H:%M} last={last:%H:%M}"
            if first and last else f"date={ref_date} matches={len(self._matches)}",
        )

    # ── polling / sending ──────────────────────────────────────────────────

    def _refresh_and_send(self, now: datetime) -> None:
        try:
            light = self._fetcher.refresh_fixtures(
                [self._plan_ref_date - timedelta(days=1),
                 self._plan_ref_date,
                 self._plan_ref_date + timedelta(days=1)]
                if self._plan_ref_date else []
            )
            self._consecutive_failures = 0
        except Exception as exc:  # noqa: BLE001
            if not self._matches:  # nothing to update; stay quiet
                self._handle_fetch_failure(exc, "refresh")
                return
            self._handle_fetch_failure(exc, "refresh")
            light = {}

        for mid, lm in light.items():
            m = self._matches.get(mid)
            if m is None or not getattr(m.home, "name", None):
                # stub from the stored plan -> take the fresh list object
                self._matches[mid] = lm
            else:
                m.kickoff = lm.kickoff
                m.status = lm.status
                m.score = lm.score
                m.live_minute = lm.live_minute

        # Drop adopted stubs that the (popular-filtered) fresh list no longer
        # returns — keeps an older stored plan from leaking small leagues.
        if light:
            self._matches = {mid: m for mid, m in self._matches.items() if mid in light}

        self._send_prematches(now)
        self._send_fulltimes(now)

    def _send_prematches(self, now: datetime) -> None:
        for m in self._matches.values():
            if m.kickoff is None or already_sent(m.match_id, EVENT_PREMATCH):
                continue
            remaining = (m.kickoff - now).total_seconds()
            if not (0 <= remaining <= self.cfg.prematch_window):
                continue
            if not m.channels or not m.commentator:  # plan loaded from store
                try:
                    self._fetcher.fetch_detail(m)
                except Exception as exc:  # noqa: BLE001 — retry next tick
                    self._handle_fetch_failure(exc, "detail")
                    continue
            path = f"{self.cfg.image_dir / m.match_id}_prematch.png"
            try:
                self._render_prematch(m, path)
                self._publisher.send_photo(path, self._prematch_caption(m))
            except Exception as exc:  # noqa: BLE001 — retry next tick
                logger.exception("prematch publish failed %s", m.match_id)
                self._notifier.alert(f"فشل نشر كرت قبل المباراة {m.match_id}: {exc}")
                continue
            mark_sent(m.match_id, EVENT_PREMATCH)
            self._log("نشر كرت قبل المباراة | prematch", f"{m.home.name} - {m.away.name}")

    def _send_fulltimes(self, now: datetime) -> None:
        for m in self._matches.values():
            if m.status != "ended" or already_sent(m.match_id, EVENT_FULLTIME):
                continue
            prev = self._last_status.get(m.match_id)
            if prev == "ended":  # already seen ended earlier
                continue
            try:
                self._fetcher.fetch_detail(m)
            except Exception as exc:  # noqa: BLE001
                self._handle_fetch_failure(exc, "detail")
                continue  # do not advance status; retry next tick
            path = f"{self.cfg.image_dir / m.match_id}_fulltime.png"
            try:
                self._render_fulltime(m, path)
                self._publisher.send_photo(
                    path, self._fulltime_caption(m)
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("fulltime publish failed %s", m.match_id)
                self._notifier.alert(f"فشل نشر كرت نهاية المباراة {m.match_id}: {exc}")
                continue
            mark_sent(m.match_id, EVENT_FULLTIME)
            self._last_status[m.match_id] = "ended"
            update_match_status(m.match_id, "ended")
            self._log(
                "نشر كرت النتيجة | fulltime",
                f"{m.home.name} {m.score or ''} {m.away.name}",
            )

    def _set_mode(self, mode: str) -> None:
        if self._mode != mode:
            prev = self._mode
            self._mode = mode
            self._transitions.append((self._clock.now(), prev or "start", mode))
            self._log("انتقال وضع | mode", f"{prev or 'بداية'} -> {mode}")

    # ── failure handling ────────────────────────────────────────────────────

    def _handle_fetch_failure(self, exc: Exception, where: str) -> None:
        self._consecutive_failures += 1
        logger.warning("fetch failed (%s): %s", where, exc)
        if self._consecutive_failures >= self.cfg.max_fetch_failures:
            self._notifier.alert(
                f"فشل متكرر في جلب البيانات ({where}): {type(exc).__name__} {exc}"
            )
            self._consecutive_failures = 0  # alert once per burst, then re-arm

    # ── helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _log(tag: str, detail: str) -> None:
        logger.info("%s | %s", tag, detail)

    @staticmethod
    def _prematch_caption(m: Match) -> str:
        lines = [f"{m.home.name}  -  {m.away.name}"]
        if m.round:
            lines.append(m.round)
        if m.kickoff:
            t = m.kickoff.astimezone(BAGHDAD)
            lines.append(f"الوقت: {t:%H:%M} بتوقيت بغداد")
        if m.channels:
            lines.append("القناة: " + "، ".join(c for c in m.channels if c.strip()))
        return "\n".join(lines)

    @staticmethod
    def _fulltime_caption(m: Match) -> str:
        score = m.score
        if score:
            title = f"{m.home.name} {score.home} - {score.away} {m.away.name}"
        else:
            title = f"{m.home.name} - {m.away.name}"
        lines = [title]
        if m.penalty_score:
            lines.append(f"ركلات الترجيح: {m.penalty_score[0]} - {m.penalty_score[1]}")
        return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover — real entry point
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    Scheduler().run()