"""Generate demo images from real scraped data (acceptance for step 2).

Run from E:\\Match_data:  python -m renderer.demo

Produces three PNGs in E:\\Match_data\\demo_out/:
  prematch_.png        (a not-started match from tomorrow)
  fulltime_.png        (a finished match with multiple scorers)
  penalties_.png       (a match decided by penalty shootout, if any today)
"""

from __future__ import annotations

import logging
import pathlib
from datetime import datetime, timedelta

from data_layer import config
from data_layer.fetcher import Fetcher
from data_layer.main import load_day
from data_layer.models import Match
from renderer import render_fulltime_image, render_prematch_image

OUT = pathlib.Path(r"E:\Match_data\demo_out")


def _find(championships, **pred):
    for champ in championships:
        for match in champ.matches:
            if all(getattr(match, k) == v for k, v in pred.items()):
                return champ, match
    return None, None


def main() -> int:
    logging.basicConfig(level=logging.WARNING)

    today = datetime.now(config.TZ).date()
    tomorrow = today + timedelta(days=1)

    with Fetcher() as fetcher:
        # prematch: first not-started match of tomorrow
        champs_tomorrow = load_day(fetcher, tomorrow)
        champ_pre, pre = _find(champs_tomorrow, status="not_started")

        # fulltime + penalties: from today's finished list
        champs_today = load_day(fetcher, today)

    print(f"prematch demo:  {getattr(champ_pre, 'name', '?')} — "
          f"{pre.home.name if pre else '?'} vs {pre.away.name if pre else '?'}")
    path = render_prematch_image(
        pre, OUT / "prematch_.png",
        championship_name=champ_pre.name if champ_pre else "",
        championship_logo_url=champ_pre.logo_url if champ_pre else "",
    )
    print("  ->", path)

    # scorer-rich finished match (multi-goal + multi-player)
    champ_ft, fin = _find(champs_today, status="ended")
    if fin:
        print(f"fulltime demo:   {champ_ft.name} — {fin.home.name} {fin.score} {fin.away.name}")
        path = render_fulltime_image(
            fin, OUT / "fulltime_.png",
            championship_name=champ_ft.name,
            championship_logo_url=champ_ft.logo_url,
        )
        print("  ->", path)

    # penalty-shootout match, if any today
    champ_pen, penmatch = None, None
    for champ in champs_today:
        for m in champ.matches:
            if m.penalty_score is not None:
                champ_pen, penmatch = champ, m
                break
        if penmatch:
            break
    if penmatch:
        print(f"penalties demo:  {champ_pen.name} — "
              f"{penmatch.home.name} {penmatch.score} {penmatch.away.name}"
              f" (ترجيح {penmatch.penalty_score[0]} - {penmatch.penalty_score[1]})")
        path = render_fulltime_image(
            penmatch, OUT / "penalties_.png",
            championship_name=champ_pen.name,
            championship_logo_url=champ_pen.logo_url,
        )
        print("  ->", path)
    else:
        print("penalties demo:  (none today)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())