"""Telegram-style match image cards, generated with Pillow.

Two public entry points, both taking a ``data_layer.models.Match``:

- :func:`render_prematch_image` — "starts soon" announcement card.
- :func:`render_fulltime_image` — final score + scorers card.

Arabic is shaped via ``arabic_reshaper`` + ``python-bidi`` and drawn with
Noto Naskh Arabic (stored under ``renderer/assets/fonts``). Team logos are
downloaded once into ``renderer/assets/logos`` and cached by their media id.

Design canvas: 1080x720 landscape. All text is auto-shrunk to stay inside
the card; missing logos fall back to a generated letter tile.
"""

from __future__ import annotations

import pathlib
import re
from collections import Counter
from typing import Optional
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw

from data_layer.models import Match, Score
from renderer.channels import english_channels
from renderer.shaping import draw_centered, fit_font, load_font, shaped, text_width
from renderer.logos import load_logo

CANVAS = (1080, 720)
BAGHDAD = ZoneInfo("Asia/Baghdad")

# ── palette ────────────────────────────────────────────────────────────────
BG_TOP = (9, 24, 40)
BG_BOTTOM = (38, 62, 88)
GOLD = (255, 212, 102)
PRIMARY = (255, 255, 255)
MUTED = (154, 184, 202)
GOLD_SOFT = (196, 156, 64)

# ── helpers ────────────────────────────────────────────────────────────────


def _background(size: tuple[int, int]) -> Image.Image:
    """Vertical gradient canvas."""
    width, height = size
    img = Image.new("RGB", size, BG_TOP)
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / max(1, height - 1)
        draw.line(
            (0, y, width, y),
            fill=tuple(int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM)),
        )
    return img


def _panel(base: Image.Image, box: tuple[int, int, int, int], radius: int = 24, alpha: int = 46) -> None:
    """Darken a rounded area so bright text pops against the gradient."""
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rounded_rectangle(box, radius=radius, fill=(8, 20, 36, alpha))
    base.paste(Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB"), (0, 0))


def _title_block(
    base: Image.Image,
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    champ_logo: Optional[Image.Image] = None,
) -> None:
    """Championship name (with optional small logo) + gold divider on top."""
    if champ_logo is not None:
        base.paste(champ_logo, (CANVAS[0] // 2 - champ_logo.width // 2, 8), champ_logo)
        title_y, divider_y = 64, 112
    else:
        title_y, divider_y = 34, 98
    draw_centered(base, draw, CANVAS[0] // 2, title_y, text, 32, GOLD, max_width=980, shadow=True)
    cx = CANVAS[0] // 2
    line_w = 640
    draw.rounded_rectangle(
        (cx - line_w // 2, divider_y, cx + line_w // 2, divider_y + 5),
        radius=2, fill=GOLD_SOFT,
    )


def _team_header(
    base: Image.Image,
    draw: ImageDraw.ImageDraw,
    home: str,
    home_logo: str,
    away: str,
    away_logo: str,
    home_x: int,
    away_x: int,
    *,
    logo_y: int = 128,
    logo_size: int = 112,
    name_y: int = 252,
) -> None:
    """Pair of logos + names, left and right columns."""
    for cx, name, url in (
        (home_x, home, home_logo),
        (away_x, away, away_logo),
    ):
        logo = load_logo(url, logo_size, name)
        base.paste(logo, (cx - logo_size // 2, logo_y), logo)
        draw_centered(
            base, draw, cx, name_y, name, 30, PRIMARY,
            max_width=430, bold=True, shadow=True,
        )


def _line_height(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    """Visual ink height of a shaped line (Negative bounds above baseline)."""
    box = draw.textbbox((0, 0), shaped(text), font=font)
    return box[3] - box[1], box[1], box[3]


def _scorers(
    base: Image.Image,
    draw: ImageDraw.ImageDraw,
    cx: int,
    y: int,
    entries: list[tuple[str, int]],
    *,
    max_width: int = 400,
    panel: bool = True,
) -> int:
    """Draw scorer lines under a column (each fully in its own panel)."""
    if not entries:
        label = "بدون أهداف"
        font = fit_font(draw, label, max_width, 24, bold=False)
        if panel:
            h, off, _bot = _line_height(draw, label, font)
            _panel(base, (cx - 185, int(y + off - 14), cx + 185, int(y + off + 14 + h)), radius=18, alpha=46)
        return draw_centered(
            base, draw, cx, y, label, 24, MUTED,
            max_width=max_width, bold=False, shadow=True,
        ) - int(24 * 0.3)

    rows: list[tuple[str, int, object, tuple[int, int, int, int]]] = []
    cur = y
    bottom = y
    for player, count in entries:
        label = f"{player} ({count})" if count > 1 else player
        font = fit_font(draw, label, max_width, 25, bold=False)
        h, off, bot = _line_height(draw, label, font)
        rows.append((label, cur, font, (0, off, 0, bot)))
        bottom = cur + bot
        cur += int(h + 7)
    if panel and rows:
        _, off0, _, _ = rows[0][3]
        top = rows[0][1] + off0
        _panel(
            base,
            (cx - 185, int(top - 14), cx + 185, int(bottom + 14)),
            radius=18, alpha=46,
        )
    for label, yy, font, _bb in rows:
        width = text_width(draw, label, font)
        draw.text((cx - width // 2 + 2, yy + 3), shaped(label), font=font, fill=(8, 16, 26))
        draw.text((cx - width // 2, yy), shaped(label), font=font, fill=GOLD)
    return cur


def _scorer_entries(match: Match) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    """(home, away) scorer name→goals lists, in chronological order."""
    home: Counter[str] = Counter()
    away: Counter[str] = Counter()
    for g in match.goals:
        if g.team == match.home.name:
            home[g.player] += 1
        elif g.team == match.away.name:
            away[g.player] += 1
    # Counter keeps insertion order; goals are pre-sorted by minute.
    return list(home.items()), list(away.items())


def _watermark(
    base: Image.Image,
    *,
    logo_path: Optional[str] = None,
    text: str = "AlnasrawyTV",
) -> Image.Image:
    """Small semi-transparent corner mark (real logo if file exists)."""
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    if logo_path and pathlib.Path(logo_path).exists():
        logo = Image.open(logo_path).convert("RGBA")
        logo.thumbnail((44, 44))
        x = CANVAS[0] - logo.width - 16
        y = CANVAS[1] - logo.height - 12
        logo.putalpha(logo.getchannel("A").point(lambda a: int(a * 0.8)))
        overlay.paste(logo, (x, y), logo)
    else:
        font = load_font(20, bold=True)
        width = text_width(draw, text, font)
        draw.text(
            (CANVAS[0] - width - 16, CANVAS[1] - 34), shaped(text),
            font=font, fill=(255, 255, 255, 72),
        )
    return Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")


def _kickoff_baghdad(match: Match) -> Optional[datetime]:
    if match.kickoff is None:
        return None
    if match.kickoff.tzinfo:
        return match.kickoff.astimezone(BAGHDAD)
    return match.kickoff.replace(tzinfo=BAGHDAD)


def _kickoff_label(match: Match) -> str:
    t = _kickoff_baghdad(match)
    if t is None:
        return "--:--"
    return t.strftime("%H:%M")


def _commentator_lines(match: Match) -> list[str]:
    """Split the raw commentator field into individual names."""
    raw = (match.commentator or "").strip()
    if not raw:
        return []
    parts = [p.strip() for p in re.split(r"\s+و\s+|,|،|&+", raw) if p.strip()]
    return parts or [raw]


def _save(image: Image.Image, output_path: str | pathlib.Path) -> str:
    path = pathlib.Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG")
    return str(path)


# ── public API ─────────────────────────────────────────────────────────────


def render_prematch_image(
    match: Match,
    output_path: str,
    *,
    championship_name: str = "",
    championship_logo_url: str = "",
    watermark_logo_path: Optional[str] = None,
) -> str:
    """"Starts soon" card: league / logos / phrase+time / channels+commentators."""
    base = _background(CANVAS)
    draw = ImageDraw.Draw(base)

    champ_logo = None
    if championship_logo_url:
        champ_logo = load_logo(
            championship_logo_url, 52,
            championship_name or match.round or "؟",
        )
    _title_block(
        base, draw, championship_name or match.round or "",
        champ_logo=champ_logo,
    )

    # logos, then names just below
    _team_header(
        base, draw, match.home.name, match.home.logo_url,
        match.away.name, match.away.logo_url,
        home_x=260, away_x=820, logo_y=150, logo_size=120, name_y=292,
    )

    # ── between logos and names: phrase above, kickoff time below ──────────
    phrase_text = "تبدأ المباراة قريباً"
    time_text = _kickoff_label(match)
    font_phrase = fit_font(draw, phrase_text, 700, 24, bold=True)
    font_time = fit_font(draw, time_text, 560, 40, bold=True)

    hp, offp, _ = _line_height(draw, phrase_text, font_phrase)
    ht, _, _ = _line_height(draw, time_text, font_time)
    gap = 8
    top = 158
    y1 = top
    y2 = y1 + hp + gap

    _panel(base, (404, int(y1 + offp - 12), 676, int(y2 + ht + 12)), radius=20, alpha=46)
    draw_centered(base, draw, CANVAS[0] // 2, y1, phrase_text, 24, GOLD,
                  font=font_phrase, max_width=700, shadow=True)
    draw_centered(base, draw, CANVAS[0] // 2, y2, time_text, 40, PRIMARY,
                  font=font_time, max_width=560, shadow=True)

    # ── bottom band: broadcasting channels + commentators ───────────────────
    channels = english_channels([c for c in match.channels if c.strip()])
    comm_lines = _commentator_lines(match)

    rows: list[tuple[str, int, bool]] = []  # (text, size, gold?)
    if channels:
        rows.extend((c, 28, False) for c in channels[:4])
    else:
        rows.append(("القناة غير محددة", 24, False))
    if comm_lines:
        sep = ("─" * 16, 18, True)
        rows.append(sep)
        rows.extend(("المعلق: " + c, 24, True) for c in comm_lines[:2])

    # fonts + line spacing measured
    y_top_row = CANVAS[1] - 40 - 42 * len(rows)
    if y_top_row < 360:
        y_top_row = 360
    draw_ys: list[int] = []
    cur = y_top_row
    for text, size, _gold in rows:
        font = fit_font(draw, text, 860, size, bold=_gold)
        h, _, _ = _line_height(draw, text, font)
        draw_ys.append((text, cur, font, size, _gold))
        cur += h + 10

    _panel(base, (150, y_top_row - 12, 930, cur - 2), radius=24, alpha=50)
    for text, yy, font, _size, gold in draw_ys:
        width = text_width(draw, text, font)
        fill = GOLD if gold else PRIMARY
        draw.text((540 - width // 2 + 2, yy + 3), shaped(text), font=font, fill=(8, 16, 26))
        draw.text((540 - width // 2, yy), shaped(text), font=font, fill=fill)

    return _save(_watermark(base, logo_path=watermark_logo_path), output_path)


def render_fulltime_image(
    match: Match,
    output_path: str,
    *,
    championship_name: str = "",
    championship_logo_url: str = "",
    watermark_logo_path: Optional[str] = None,
) -> str:
    """Final-score card: logos / corners score between them / scorers below."""
    base = _background(CANVAS)
    draw = ImageDraw.Draw(base)

    champ_logo = None
    if championship_logo_url:
        champ_logo = load_logo(
            championship_logo_url, 52,
            championship_name or match.round or "؟",
        )
    _title_block(
        base, draw, championship_name or match.round or "",
        champ_logo=champ_logo,
    )

    home_x, away_x = 250, 830
    # logos + names, score hangs between the two crests
    _team_header(
        base, draw, match.home.name, match.home.logo_url,
        match.away.name, match.away.logo_url,
        home_x=home_x, away_x=away_x, logo_y=168, logo_size=120, name_y=306,
    )

    # center score: smaller, between the two logos (horizontal + vertical)
    score = match.score or Score(0, 0)
    score_text = f"{score.home} - {score.away}"
    _panel(base, (424, 176, 656, 296), radius=26, alpha=60)
    draw_centered(
        base, draw, CANVAS[0] // 2, 200, score_text, 66, GOLD,
        max_width=600, shadow=True,
        font=fit_font(draw, score_text, 600, 66, bold=True),
    )

    y_line = draw_centered(
        base, draw, CANVAS[0] // 2, 388, "انتهت المباراة", 27, MUTED,
        max_width=600, bold=False,
    )
    y_scorers = y_line + 34 if match.penalty_score is None else y_line + 66

    # scorers under each team name
    home_scorers, away_scorers = _scorer_entries(match)
    _scorers(base, draw, home_x, y_scorers, home_scorers, max_width=400)
    _scorers(base, draw, away_x, y_scorers, away_scorers, max_width=400)

    if match.penalty_score is not None:
        ph, pa = match.penalty_score
        draw_centered(
            base, draw, CANVAS[0] // 2, y_line + 6, f"ركلات الترجيح: {ph} - {pa}",
            29, GOLD, max_width=600, bold=False, shadow=True,
        )

    return _save(_watermark(base, logo_path=watermark_logo_path), output_path)