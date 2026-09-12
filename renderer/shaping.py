"""Arabic text shaping + font helpers.

Every Arabic string that must be drawn goes through :func:`shaped`:

    get_display(arabic_reshaper.reshape(text))

so letters connect correctly and the run order (RTL, with embedded digits
and Latin tokens) is rendered properly on a left-to-right canvas.
"""

from __future__ import annotations

import pathlib
from functools import lru_cache

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import ImageDraw, ImageFont, Image, features

_ASSETS = pathlib.Path(__file__).resolve().parent / "assets"
FONT_DIR = _ASSETS / "fonts"
FONT_PATH = FONT_DIR / "NotoNaskhArabic[wght].ttf"

_BOLD_NAME = b"Bold"
_REGULAR_NAME = b"Regular"

_reshaper = arabic_reshaper.ArabicReshaper(
    configuration={"delete_harakat": False, "support_ligatures": True}
)

# Pillow wheels differ in their FreeType libraqm support (Ubuntu runners have
# it, Windows local builds usually do not). libraqm re-runs the unicode bidi
# algorithm on whatever string we hand to `draw.text`, so pre-shaped
# presentation forms would get reversed a second time. Every draw/measure below
# therefore picks the correct input per build: raw logical text when raqm is
# present (PIL shapes+orders it), otherwise OUR pre-shaped visual string.
HAS_RAQM = features.check("raqm")


def shaped(text: str) -> str:
    """Reshape an (RTL-first) string for correct Arabic rendering."""
    return get_display(_reshaper.reshape(text))


def draw_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill,
    *,
    anchor=None,
) -> None:
    """Draw text with correct Arabic layout on any Pillow build."""
    if HAS_RAQM:
        draw.text(xy, text, font=font, fill=fill, anchor=anchor)
    else:
        draw.text(xy, shaped(text), font=font, fill=fill, anchor=anchor)


def text_bbox(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
) -> tuple[int, int, int, int]:
    """Ink bounding box of *as-drawn* text (mirrors :func:`draw_text`)."""
    if HAS_RAQM:
        return draw.textbbox((0, 0), text, font=font)
    return draw.textbbox((0, 0), shaped(text), font=font)


@lru_cache(maxsize=256)
def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Noto Naskh Arabic at the given size; bold via the variable axis."""
    font = ImageFont.truetype(str(FONT_PATH), size=int(size))
    try:
        font.set_variation_by_name(_BOLD_NAME if bold else _REGULAR_NAME)
    except Exception:  # pragma: no cover — unlikely once loaded successfully
        pass
    return font


def text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
    """Width of *as-drawn* text in pixels (mirrors :func:`draw_text`)."""
    if HAS_RAQM:
        return int(draw.textlength(text, font=font))
    return int(draw.textlength(shaped(text), font=font))


def fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    size: int,
    bold: bool = True,
    min_size: int = 12,
) -> ImageFont.FreeTypeFont:
    """Shrink the font until `text` fits within `max_width` pixels."""
    size = int(size)
    font = load_font(size, bold)
    while size > min_size and text_width(draw, text, font) > max_width:
        size -= 2
        font = load_font(size, bold)
    return font


def draw_centered(
    base: Image.Image,
    draw: ImageDraw.ImageDraw,
    cx: int,
    y: int,
    text: str,
    size: int,
    fill,
    *,
    bold: bool = True,
    max_width: int = 900,
    font: ImageFont.FreeTypeFont | None = None,
    shadow: bool = False,
) -> int:
    """Draw text centered on cx, returning its bottom y. No overflow."""
    font = font or fit_font(draw, text, max_width, size, bold)
    width = text_width(draw, text, font)
    x = cx - width // 2
    if shadow:
        draw_text(draw, (x + 2, y + 3), text, font, (8, 16, 26))
    draw_text(draw, (x, y), text, font, fill)
    return y + int(size * 1.4)