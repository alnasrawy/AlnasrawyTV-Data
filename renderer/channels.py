"""Arabic → English channel names.

The site names channels in Arabic on /ar pages; off-the-shelf English cards
want "beIN Sports 2" instead of "بي إن سبورت 2". This module maps the common
ones by pattern; anything unknown passes through unchanged so cards never
break on an unfamiliar broadcaster.
"""

from __future__ import annotations

import re

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # beIN Sports family (with optional number / HD suffix)
    (re.compile(r"بي\s*إن\s*سبورتس?\s*(1|2|3|4|5|6|7|8|9)?"), "beIN Sports"),
    (re.compile(r"بي\s*إن\s*سبورتس?\s*HD(\s*\d+)?"), "beIN Sports HD"),
    # OnTime Sports (Egypt)
    (re.compile(r"أون\s*تايم\s*سبورتس?\s*(\d+)?"), "OnTime Sports"),
    # Saudi SSC / Saudi Sports
    (re.compile(r"(إس\s*إس\s*سي|إسسي\s*سبورت|SSC)\s*(\d+)?"), "SSC Sports"),
    (re.compile(r"السعودية\s*الرياضية\s*(\d+)?"), "Saudi Sports"),
    (re.compile(r"سعودي\s*سبورتس?\s*(\d+)?"), "Saudi Sports"),
    # Alkass (Qatar)
    (re.compile(r"(ال\s*كأس|الكأس|ألكاس)\s*(1|2|واحد|اثنان)?"), "Alkass"),
    # UAE
    (re.compile(r"أبوظبي\s*الرياضية\s*(1|2|3|4)?"), "Abu Dhabi Sports"),
    (re.compile(r"دبي\s*الرياضية\s*(1|2|3)?"), "Dubai Sports"),
    (re.compile(r"الشارقة\s*الرياضية\s*(\d+)?"), "Sharjah Sports"),
    (re.compile(r"عراقية\s*رياضية"), "Iraqi Sports"),
    # Country sports channels
    (re.compile(r"الأردنية\s*الرياضية\s*(\d+)?"), "Jordan Sports"),
    (re.compile(r"عمان\s*الرياضية"), "Oman Sports"),
    (re.compile(r"العراقية\s*الرياضية"), "Iraqi Sports"),
]

# name that only needs the trailing number kept as-is
_ALREADY_EN = re.compile(
    r"^(beIN|BT|Sky|ITV|DAZN|ESPN|TNT|Prime|Apple|Eleven|Canal|Movistar|"
    r"SFR|TF1|RMC|Sport|Sports|TV|MLS|NFL|NBA)[\w\s.'&-]*$",
    re.IGNORECASE,
)


def english_channel_name(name: str) -> str:
    """Best-effort English broadcaster name for an Arabic channel label."""
    name = name.strip()
    if not name or _ALREADY_EN.match(name):
        return name
    for pattern, base in _PATTERNS:
        m = pattern.search(name)
        if m:
            number = m.group(m.lastindex) if m.lastindex else ""
            return f"{base} {number}".rstrip()
    return name


def english_channels(names: list[str]) -> list[str]:
    """Map a list of channel names (deduped, order kept)."""
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        en = english_channel_name(name)
        if en and en not in seen:
            seen.add(en)
            out.append(en)
    return out