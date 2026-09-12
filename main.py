"""Unified entry point (step 5/5): data (1) + cards (2) + state (3) +
scheduler (4) + telegram publisher (a).

    python main.py                  # run the scheduler forever (long-lived host)
    python main.py --cron           # one sweep — the GitHub Actions poller
    python main.py --test-day today # print today's data, publish nothing
    python main.py --trial          # one live end-to-end card (manual check)

Test mode never touches Telegram — it is only a safe data-layer dump, so
you can exercise the scraper without disturbing the real channel.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

from config import config
from data_layer import config as dl_config
from data_layer.fetcher import Fetcher
from data_layer.main import load_day
from data_layer.parser import parse_fixtures_html, parse_match_details_html
from notify import LogPublisher
from renderer import render_fulltime_image, render_prematch_image
from scheduler import Scheduler, SchedulerConfig
from telegram_publisher import alert_admin, publish_photo_to_channels, send_message

logger = logging.getLogger("main")


def _alias(value: str) -> date:
    today = datetime.now(dl_config.TZ).date()
    if value in ("today", "tomorrow", "yesterday"):
        return {
            "today": today,
            "tomorrow": today + timedelta(days=1),
            "yesterday": today - timedelta(days=1),
        }[value]
    return date.fromisoformat(value)


def _test_day(target: date, max_details: int | None) -> int:
    """Data-layer dump only — no images, no Telegram."""
    logger.info("test-day %s — read only, nothing will be published", target.isoformat())
    with Fetcher() as fetcher:
        championships = load_day(fetcher, target, max_details=max_details)
    payload = {
        "day": target.isoformat(),
        "timezone": str(dl_config.TZ),
        "generated_at": datetime.now(dl_config.TZ).isoformat(timespec="seconds"),
        "championships": [c.as_dict() for c in championships],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


class ChannelPublisher:
    """Adapter the scheduler understands, wrapping telegram_publisher.

    send_photo → every configured channel; alert → private admin chat.
    """

    def send_photo(self, photo_path: str, caption: str = "") -> None:
        publish_photo_to_channels(photo_path, caption)

    def alert(self, text: str) -> None:
        alert_admin(text)


class LogNotifier:
    def alert(self, text: str) -> None:
        logger.error("ALERT(admin) %s", text)


def run_scheduler() -> None:
    """Start the full scheduler using live Telegram publishing."""
    if config.telegram_ready:
        publisher: object = ChannelPublisher()
    else:
        logger.warning(
            "Telegram not configured (TG_BOT_TOKEN/TG_CHANNELS) — "
            "using a console publisher. Fill .env to enable posting."
        )
        publisher = LogPublisher()
    notifier = ChannelPublisher() if config.admin_chat_id else LogNotifier()

    cfg = SchedulerConfig(image_dir=config.image_dir)
    Scheduler(publisher=publisher, notifier=notifier, config=cfg).run()


def run_trial() -> int:
    """Daily end-to-end smoke used by the GitHub Actions cron job."""
    now = datetime.now(dl_config.TZ)
    logger.info("trial run (%s) — live fetch, publish a single card", now.isoformat())
    with Fetcher() as fetcher:
        championships = load_day(fetcher, now.date())
    items = [(c, m) for c in championships for m in c.matches]
    if not items:
        print("TRIAL: no matches today — nothing to publish")
        return 0

    live = [x for x in items if x[1].status == "live"]
    upcoming = sorted(
        (x for x in items if x[1].kickoff and x[1].kickoff >= now),
        key=lambda x: x[1].kickoff,
    )
    if live:
        ch, match = live[0]
    elif upcoming:
        ch, match = upcoming[0]
    else:  # today already finished — publish a fulltime card of the last match
        ch, match = max(items, key=lambda x: x[1].kickoff)

    image = config.image_dir / f"trial_{match.match_id}.png"
    if match.status == "ended":
        render_fulltime_image(
            match, str(image),
            championship_name=ch.name, championship_logo_url=ch.logo_url,
        )
        caption = f"التجربة اليومية — {match.home.name} {match.score[0]}-{match.score[1]} {match.away.name}"
    else:
        render_prematch_image(
            match, str(image),
            championship_name=ch.name, championship_logo_url=ch.logo_url,
        )
        caption = f"التجربة اليومية — {match.home.name} ضد {match.away.name}"

    if not config.telegram_ready:
        print(f"TRIAL: telegram not configured — card kept at {image}")
        return 0
    publish_photo_to_channels(str(image), caption)
    if config.admin_chat_id:
        send_message(config.admin_chat_id, f"التجربة اليومية تمت: {caption}")
    print(f"TRIAL: published -> {config.chat_ids}")
    return 0


def run_cron() -> int:
    """One operational sweep — GitHub Actions runs this every few minutes.
    Behaves like a boot of the scheduler: builds the day plan, seeds last
    statuses from the persisted state, sends whatever is due, exits 0.
    State stays durable because the workflow commits ``state.db`` back."""
    if not config.telegram_ready:
        logger.warning("TG_BOT_TOKEN/TG_CHANNELS empty — console mode only")
    publisher = ChannelPublisher() if config.telegram_ready else LogPublisher()
    notifier = ChannelPublisher() if config.admin_chat_id else LogNotifier()

    scheduler = Scheduler(
        publisher=publisher,
        notifier=notifier,
        config=SchedulerConfig(image_dir=config.image_dir),
    )
    try:
        scheduler.sweep()
    except Exception as exc:  # surface as a red run so failures are visible
        logger.exception("cron sweep failed")
        alert_admin(f"فشلت جولة المجدول (GitHub Actions): {exc}")
        return 1
    print("CRON: sweep finished cleanly")
    return 0


def _feed(days: list[tuple[str, date]], out: Path) -> int:
    """Build the public matches.json feed for the companion app.

    ``days`` = (day_label, date) list, e.g. [("yesterday", d-1), ("today", d),
    ("tomorrow", d+1)]. Each match keeps its ``day`` label so the app can
    group them. List pages come first (light), then the feed enriches the
    most relevant matches (live → today's upcoming → tomorrow's upcoming)
    with their detail pages so channels & commentator are filled for the
    matches the app actually cares about. Committed by the GitHub poller.
    """
    labels = " ".join(f"{lab}:{day.isoformat()}" for lab, day in days)
    logger.info("feed [%s] -> %s", labels, out)

    collected: list[tuple[str, date, object, object]] = []
    with Fetcher() as fetcher:
        for day_label, target in days:
            if target == datetime.now(dl_config.TZ).date():
                championships = parse_fixtures_html(fetcher.fetch_fixtures_html(), day=target)
            else:
                championships = load_day(fetcher, target, max_details=0)
            for ch in championships:
                for m in ch.matches:
                    collected.append((day_label, target, ch, m))

        candidates = _feed_enrich_candidates(collected)
        logger.info("feed: enriching %d/%d matches with detail pages",
                    len(candidates), len(collected))
        with ThreadPoolExecutor(max_workers=dl_config.MAX_CONCURRENCY) as pool:
            futures = []
            for m in candidates:
                futures.append(pool.submit(_enrich_match, fetcher, m))
            for future in futures:
                future.result()  # never raises

    matches = []
    for day_label, target, ch, m in collected:
        score = {"home": m.score.home, "away": m.score.away} if m.score else None
        pen = None
        if m.penalty_score and any(m.penalty_score):
            pen = {"home": m.penalty_score[0], "away": m.penalty_score[1]}
        matches.append(
            {
                "day": day_label,
                "date": target.isoformat(),
                "match_id": m.match_id,
                "championship": ch.name,
                "championship_logo_url": ch.logo_url,
                "round": m.round,
                "source_url": m.source_url,
                "kickoff": m.kickoff.isoformat(timespec="minutes") if m.kickoff else None,
                "status": m.status,
                "live_minute": m.live_minute if m.status == "live" else "",
                "teams": {
                    "home": {"name": m.home.name, "logo_url": m.home.logo_url},
                    "away": {"name": m.away.name, "logo_url": m.away.logo_url},
                },
                "score": score,
                "penalty_score": pen,
                "channels": list(m.channels) if m.channels else [],
                "commentator": m.commentator or "",
            }
        )

    payload = {
        "source": "ysscores",
        "feed_version": 2,
        "days": [day.isoformat() for _, day in days],
        "timezone": str(dl_config.TZ),
        "generated_at": datetime.now(dl_config.TZ).isoformat(timespec="seconds"),
        "count": len(matches),
        "matches": matches,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"FEED: {len(matches)} matches -> {out}")
    return 0


def _feed_enrich_candidates(collected: list[tuple[str, date, object, object]]) -> list:
    """Pick the matches worth a detail fetch, keeping the poll fast.

    Priority: live games first, then upcoming (soonest kickoff) from today
    and tomorrow, capped so a full poll stays well under a minute of detail
    fetches. Finished matches on earlier days only get details when cheap.
    """
    now = datetime.now(dl_config.TZ)
    by_rank: list[tuple[tuple[int, float], object]] = []

    def rank(m) -> tuple[int, float]:
        if m.status == "live":
            return (0, 0.0)
        if m.status == "not_started" and m.kickoff:
            diff = (m.kickoff - now).total_seconds()
            bucket = 1 if diff >= 0 else 2
            return (bucket, m.kickoff.timestamp())
        return (3, 0.0)

    for day_label, target, ch, m in collected:
        by_rank.append((rank(m), m))

    by_rank.sort(key=lambda x: x[0])
    cap = dl_config.FEED_DETAIL_CAP
    return [m for _, m in by_rank][:cap]


def _enrich_match(fetcher: Fetcher, m) -> None:
    """Fetch one detail page and merge channels/commentator into the Match."""
    try:
        html = fetcher.fetch_match_page(m.source_url)
        parse_match_details_html(m, html)
    except Exception:
        logger.exception("feed detail fetch failed for match %s", m.match_id)


def _feed_days(spec: str) -> list[tuple[str, date]]:
    today = datetime.now(dl_config.TZ).date()
    if spec == "all":
        return [
            ("yesterday", today - timedelta(days=1)),
            ("today", today),
            ("tomorrow", today + timedelta(days=1)),
        ]
    if spec in ("yesterday", "today", "tomorrow"):
        return [(spec, _alias(spec))]
    return [("custom", date.fromisoformat(spec))]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--test-day",
        metavar="SPEC",
        default=None,
        help="today | yesterday | tomorrow | YYYY-MM-DD — print data, publish nothing",
    )
    parser.add_argument(
        "--max-details",
        type=int,
        default=None,
        help="limit detail fetches in --test-day mode (faster dry runs)",
    )
    parser.add_argument(
        "--trial",
        action="store_true",
        help="one end-to-end card to Telegram (used by the GitHub daily cron)",
    )
    parser.add_argument(
        "--cron",
        action="store_true",
        help="one scheduler sweep (used by the GitHub Actions poller)",
    )
    parser.add_argument(
        "--feed",
        metavar="SPEC",
        default=None,
        help="all (yesterday+today+tomorrow) | today | yesterday | tomorrow | YYYY-MM-DD "
        "— write matches.json for the companion app",
    )
    parser.add_argument(
        "--feed-out",
        metavar="PATH",
        default=None,
        help="where to write the feed (default: matches.json next to main.py)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    if args.cron:
        return run_cron()
    if args.trial:
        return run_trial()
    if args.feed:
        out = Path(args.feed_out) if args.feed_out else Path(__file__).resolve().parent / "matches.json"
        return _feed(_feed_days(args.feed), out)
    if args.test_day:
        return _test_day(_alias(args.test_day), args.max_details)

    run_scheduler()
    return 0


if __name__ == "__main__":
    sys.exit(main())