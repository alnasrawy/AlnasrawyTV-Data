"""Unified entry point (step 5/5): data (1) + cards (2) + state (3) +
scheduler (4) + telegram publisher (a).

    python main.py                  # run the scheduler forever
    python main.py --test-day today # print today's data, publish nothing

Test mode never touches Telegram — it is only a safe data-layer dump, so
you can exercise the scraper without disturbing the real channel.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from config import config
from data_layer import config as dl_config
from data_layer.fetcher import Fetcher
from data_layer.main import load_day
from notify import LogPublisher
from scheduler import Scheduler, SchedulerConfig
from telegram_publisher import alert_admin, publish_photo_to_channels

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
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    if args.test_day:
        return _test_day(_alias(args.test_day), args.max_details)

    run_scheduler()
    return 0


if __name__ == "__main__":
    sys.exit(main())