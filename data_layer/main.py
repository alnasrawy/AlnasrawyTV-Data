"""Standalone demo/acceptance entry point for the data layer.

Usage (running from E:\\Match_data):

    python -m data_layer.main                     # today, all details
    python -m data_layer.main --max-details 5     # quickly check a few
    python -m data_layer.main --date 2026-09-11   # any day (site picker)
    python -m data_layer.main --out matches.json  # write JSON instead of stdout

Prints one compact JSON object:

    {day, timezone, generated_at, championships: [...]}

Order of championships and matches matches the site exactly.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

from data_layer import config
from data_layer.fetcher import Fetcher
from data_layer.models import Championship, Match
from data_layer.parser import parse_fixtures_html, parse_match_details_html

logger = logging.getLogger("data_layer")


# ── pipeline ───────────────────────────────────────────────────────────────


def load_day(
    fetcher: Fetcher, day: date, max_details: int | None = None
) -> list[Championship]:
    """Parse the day's list page and enrich every match's detail page.

    Returns the Championships; each Match is already filled with its
    channels, commentator and (for finished games) goal events.
    """
    if day == datetime.now(config.TZ).date():
        list_html = fetcher.fetch_fixtures_html()
    else:
        list_html = fetcher.fetch_matches_html_for_date(day)

    championships = parse_fixtures_html(list_html, day)

    jobs = [
        (champ, match)
        for champ in championships
        for match in champ.matches
    ]
    if max_details is not None:
        jobs = jobs[: max(0, max_details)]

    if jobs:
        with ThreadPoolExecutor(max_workers=config.MAX_CONCURRENCY) as pool:
            futures = [
                pool.submit(_enrich_one, fetcher, champ, match)
                for champ, match in jobs
            ]
            for future in futures:
                future.result()  # _enrich_one never raises

    return championships


def _enrich_one(
    fetcher: Fetcher, champ: Championship, match: Match
) -> None:
    """Download + parse one match's detail page; isolated on failure."""
    try:
        detail_html = fetcher.fetch_match_page(match.source_url)
        parse_match_details_html(match, detail_html)
    except Exception as exc:  # noqa: BLE001 — one bad match must not kill the run
        logger.error("failed to enrich %s / match %s: %s",
                     champ.name, match.match_id, exc)


# ── CLI ────────────────────────────────────────────────────────────────────


def _parse_day(value: str) -> date:
    return date.fromisoformat(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=_parse_day, default=None,
                        help="YYYY-MM-DD (default: today in Asia/Baghdad)")
    parser.add_argument("--max-details", type=int, default=None,
                        help="limit detail-page fetches (useful for testing)")
    parser.add_argument("--out", default=None,
                        help="write JSON to a file instead of stdout")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    today = datetime.now(config.TZ).date()
    day = args.date or today

    with Fetcher() as fetcher:
        championships = load_day(fetcher, day, max_details=args.max_details)

    payload = {
        "day": day.isoformat(),
        "timezone": str(config.TZ),
        "generated_at": datetime.now(config.TZ).isoformat(timespec="seconds"),
        "championships": [c.as_dict() for c in championships],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        logger.info("wrote %s (%d championships)", args.out, len(championships))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())