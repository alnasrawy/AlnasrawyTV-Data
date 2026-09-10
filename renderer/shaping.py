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
from PIL import ImageDraw, ImageFont, Image

_ASSETS = pathlib.Path(__file__).resolve().parent / "assets"
FONT_DIR = _ASSETS / "fonts"
FONT_PATH = FONT_DIR / "NotoNaskhArabic[wght].ttf"

_BOLD_NAME = b"Bold"
_REGULAR_NAME = b"Regular"

_reshaper = arabic_reshaper.ArabicReshaper(
    configuration={"delete_harakat": False, "support_ligatures": True}
)


def shaped(text: str) -> str:
    """Reshape an (RTL-first) string for correct Arabic rendering."""
    return get_display(_reshaper.reshape(text))


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
    """Width of *shaped* text in pixels."""
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
        draw.text((x + 2, y + 3), shaped(text), font=font, fill=(8, 16, 26))
    draw.text((x, y), shaped(text), font=font, fill=fill)
    return y + int(size * 1.4)