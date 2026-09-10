"""Team/championship logo handling: local cache + graceful fallback.

Logos are downloaded once into `assets/logos/` and reused forever; the file
name derives from the URL tail (which is the media id), so the same team is
never re-fetched. Missing/failed downloads fall back to a generated tile
with the team's first letter instead of crashing.
"""

from __future__ import annotations

import pathlib
import re

import httpx
from PIL import Image, ImageDraw, ImageFilter

from renderer.shaping import load_font, shaped, text_width

_ASSETS = pathlib.Path(__file__).resolve().parent / "assets"
CACHE_DIR = _ASSETS / "logos"

_USER_AGENT = "AlnasrawyTV-DataBot/1.0 (logo cache)"

# Allow an empty clipboard-level cache dir for tests; directories are created
# lazily on first successful download.
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_path(url: str) -> pathlib.Path | None:
    if not url:
        return None
    name = url.rstrip("/").split("/")[-1] or "logo.png"
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return CACHE_DIR / name


def load_logo(url: str, size: int, fallback_label: str) -> Image.Image:
    """Round-cornered logo `size`×`size`. Never raises on bad data."""
    image: Image.Image | None = None
    path = _cache_path(url)

    if path is not None and path.exists():
        image = _open_any(path)

    if image is None:
        downloaded = _download(url)
        if downloaded is not None:
            path = path or CACHE_DIR / "downloaded.png"
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                downloaded.save(path)
                image = downloaded
            except Exception:  # pragma: no cover
                image = downloaded

    image = image or _placeholder(fallback_label, size)
    return _rounded_square(image, size)


def _open_any(path: pathlib.Path) -> Image.Image | None:
    try:
        with Image.open(path) as img:
            return img.convert("RGBA")
    except Exception:
        return None


def _download(url: str) -> Image.Image | None:
    if not url:
        return None
    try:
        resp = httpx.get(
            url,
            timeout=20,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        )
        if resp.status_code != 200 or not resp.content:
            return None
        return _open_bytes(resp.content)
    except Exception:
        return None


def _open_bytes(data: bytes) -> Image.Image | None:
    import io

    try:
        with Image.open(io.BytesIO(data)) as img:
            return img.convert("RGBA")
    except Exception:
        return None


def _placeholder(label: str, size: int) -> Image.Image:
    """A neutral tile with the first character of the team name."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=size // 6, fill=(36, 60, 82, 255)
    )
    char = (label or "؟").strip()[:1] or "؟"
    font = load_font(int(size * 0.48), bold=True)
    width = text_width(draw, char, font)
    draw.text(
        ((size - width) // 2, int(size * 0.24)), shaped(char), font=font,
        fill=(238, 193, 72, 255),
    )
    return img


def _rounded_square(image: Image.Image, size: int) -> Image.Image:
    image = image.resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=size // 6, fill=255
    )
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(image, (0, 0), mask)
    return out