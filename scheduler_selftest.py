"""Acceptance test for the scheduler (step 4/5).

Simulates a full match day with a fake clock + fake fetcher (no network,
no real waiting) and verifies:

- daily plan built on boot
- idle -> active -> idle transitions happen without manual intervention
- active mode persists until the LAST match of the day ends
- prematch / fulltime cards are each sent exactly once
- dedup survives a simulated restart (state comes from step-3 store)
- next-day rollover fires only at/after 01:00
- repeated fetch failures raise an admin alert without killing the loop

Run:  python scheduler_selftest.py
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

WORKSPACE = Path(__file__).resolve().parent
sys.path.insert(0, str(WORKSPACE))

from data_layer.models import Match, Score, Team  # noqa: E402
from scheduler import MODE_ACTIVE, MODE_IDLE  # noqa: E402
from scheduler import Scheduler, SchedulerConfig  # noqa: E402
from state_store import get_daily_plan, set_db_path  # noqa: E402

BAGHDAD = ZoneInfo("Asia/Baghdad")

PASS = 0
FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}  {detail}")


# ── fakes ──────────────────────────────────────────────────────────────────


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.t = start

    def now(self) -> datetime:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)


class FakePublisher:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_photo(self, photo_path: str, caption: str = "") -> None:
        self.sent.append((photo_path, caption))


class FakeNotifier:
    def __init__(self) -> None:
        self.alerts: list[str] = []

    def alert(self, text: str) -> None:
        self.alerts.append(text)


def _match(mid: str, kickoff: datetime, end_score: tuple[int, int]) -> Match:
    return Match(
        match_id=mid,
        source_url=f"https://www.ysscores.com/ar/match/{mid}",
        home=Team(f"فريق{mid}أ"), away=Team(f"فريق{mid}ب"),
        kickoff=kickoff, status="not_started", channels=["beIN Sports 2"],
    )


class FakeFetcher:
    """A match starts at `kickoff`, stays live `duration`, then ends."""

    def __init__(self, clock: FakeClock,
                 profiles: list[tuple[Match, timedelta, tuple[int, int]]]) -> None:
        self._clock = clock
        self.profiles = profiles
        self.full_plan_calls = 0
        self.detail_calls = 0
        self.fail_next_refreshes = 0

    def _status(self, base: Match, dur: timedelta, end_score: tuple[int, int]) -> Match:
        now = self._clock.now()
        m = _match(base.match_id, base.kickoff, end_score)
        if now < base.kickoff:
            m.status, m.score = "not_started", None
        elif now < base.kickoff + dur:
            m.status, m.score = "live", Score(1, 0)
        else:
            m.status, m.score = "ended", Score(*end_score)
        return m

    def full_plan(self, ref_date) -> list[Match]:
        self.full_plan_calls += 1
        return [self._status(b, d, s) for b, d, s in self.profiles]

    def refresh_fixtures(self, days) -> dict[str, Match]:
        if self.fail_next_refreshes > 0:
            self.fail_next_refreshes -= 1
            raise ConnectionError("simulated network failure")
        return {b.match_id: self._status(b, d, s) for b, d, s in self.profiles}

    def fetch_detail(self, match: Match) -> None:
        self.detail_calls += 1
        match.status = "ended"
        match.score = Score(2, 1)
        match.goals = []


def _make(db: Path, profiles, start: datetime) -> tuple[
    Scheduler, FakeClock, FakeFetcher, FakePublisher, FakeNotifier,
]:
    set_db_path(db)
    clock = FakeClock(start)
    fetcher = FakeFetcher(clock, profiles)
    pub, noty = FakePublisher(), FakeNotifier()
    cfg = SchedulerConfig(
        image_dir=Path(tempfile.mkdtemp(prefix="sched_imgs_")),
        max_fetch_failures=3,
    )
    s = Scheduler(
        fetcher=fetcher, publisher=pub, notifier=noty, config=cfg, clock=clock,
        render_prematch=lambda m, p: str(p),
        render_fulltime=lambda m, p: str(p),
    )
    return s, clock, fetcher, pub, noty


def transitions(s: Scheduler) -> list[str]:
    return [f"{a}->{b}" for _t, a, b in s._transitions]


def sent_names(pub: FakePublisher, kind: str) -> list[str]:
    return sorted(
        Path(p).name for p, _ in pub.sent if f"_{kind}.png" in p
    )


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="sched_state_"))
    d = datetime(2026, 9, 10, tzinfo=BAGHDAD)
    H = lambda hh, mm=0: d.replace(hour=hh, minute=mm)  # noqa: E731
    profiles = [
        (_match("1", H(6, 25), (2, 1)), timedelta(hours=1), (2, 1)),
        (_match("2", H(10, 0), (1, 1)), timedelta(hours=2), (1, 1)),
        (_match("3", H(18, 30), (0, 3)), timedelta(hours=1), (0, 3)),
    ]

    print("S1. full day: transitions + one send each + active till last match")
    s, _c, fetcher, pub, _n = _make(tmp / "s1.db", profiles, H(6, 0))
    s.run(max_iterations=170)  # ~06:00 -> 20:10, same calendar day

    check("daily plan built on first boot", s._plan_ref_date == d.date())
    check("plan persisted to state store", len(get_daily_plan()) == 3)

    tx = transitions(s)
    check("mode transitions are start->idle, idle->active, active->idle",
          tx == ["start->idle", "idle->active", "active->idle"], f"got {tx}")

    check("prematch sent once per match",
          sent_names(pub, "prematch") == ["1_prematch.png", "2_prematch.png", "3_prematch.png"],
          str(sent_names(pub, "prematch")))
    check("fulltime sent once per match",
          sent_names(pub, "fulltime") == ["1_fulltime.png", "2_fulltime.png", "3_fulltime.png"],
          str(sent_names(pub, "fulltime")))
    check("no duplicate publishes", len(pub.sent) == 6, f"sent={len(pub.sent)}")

    print("S2. no matches today -> idle all day, nothing sent")
    s2, _c2, _f2, pub2, _n2 = _make(tmp / "s2.db", [], H(6, 0))
    s2.run(max_iterations=20)
    check("no sends", pub2.sent == [])
    check("stays idle only", transitions(s2) == ["start->idle"], str(transitions(s2)))

    print("S3. restart mid-run: state store prevents dupes, nothing is missed")
    db3 = tmp / "s3.db"
    s3, _c3, _f3, pub3, _n3 = _make(db3, profiles, H(6, 0))
    s3.run(max_iterations=40)  # stops ~09:30 -> A ended(+fulltime), B still live
    check("run1 sends only A's cards",
          sorted(Path(p).name for p, _ in pub3.sent)
          == ["1_fulltime.png", "1_prematch.png"],
          str(sorted(Path(p).name for p, _ in pub3.sent)))

    s4, _c4, _f4, pub4, _n4 = _make(db3, profiles, H(12, 30))  # B ended offline
    s4.run(max_iterations=17)  # stops ~17:50, before C's prematch window
    check("restart sends missed B fulltime, never re-sends A",
          sent_names(pub4, "fulltime") == ["2_fulltime.png"],
          str(sent_names(pub4, "fulltime")))
    check("restart does not resend A prematch/fulltime",
          sent_names(pub4, "prematch") == [] and "1_fulltime.png" not in sent_names(pub4, "fulltime"))

    print("S4. daily rollover respects the 01:00 boundary")
    s5, clk5, f5, pub5, _n5 = _make(tmp / "s4.db", profiles, H(6, 0))
    s5.run(max_iterations=5)
    calls_before = f5.full_plan_calls
    clk5.t = datetime(2026, 9, 11, 0, 40, tzinfo=BAGHDAD)
    s5.run(max_iterations=1)
    check("no replan before 01:00", f5.full_plan_calls == calls_before,
          f"calls={f5.full_plan_calls}")
    clk5.t = datetime(2026, 9, 11, 1, 5, tzinfo=BAGHDAD)
    s5.run(max_iterations=1)
    check("replan happens at/after 01:00",
          f5.full_plan_calls > calls_before
          and s5._plan_ref_date == datetime(2026, 9, 11, tzinfo=BAGHDAD).date())

    print("S5. repeated fetch failures alert admin, loop keeps running")
    s6, _c6, f6, _p6, noty6 = _make(tmp / "s5.db", profiles, H(6, 0))
    f6.fail_next_refreshes = 8
    s6.run(max_iterations=30)
    check("admin got a repeated-failure alert",
          any("فشل متكرر" in a for a in noty6.alerts), str(noty6.alerts))

    print()
    print(f"RESULT: {PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())