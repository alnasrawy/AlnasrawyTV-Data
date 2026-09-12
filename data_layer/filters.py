"""Popularity filter for championships (the "big leagues only" whitelist).

Why: ysscores lists dozens of small, low-interest competitions (second
divisions, minor Asian/Nordic leagues…). For an Arabic match feed we only
want the competitions people actually follow. Two editable keyword lists
drive everything:

- ``INCLUDE_CHAMPIONSHIP_KEYWORDS`` — a championship is kept when its name
  contains ANY of these (substring match, so site naming variations such as
  "دوري أبطال أفريقيا | الأدوار الإقصائية" still match).
- ``EXCLUDE_CHAMPIONSHIP_KEYWORDS`` — applied AFTER includes (an exclusion
  always wins). Used as a safety net for collisions, e.g. the whitelist
  "الدوري المصري" would otherwise also match "الدوري المصري - القسم الثاني".

Edit the lists to taste; no other code needs to change. Set the environment
variable ``FILTER_POPULAR_ONLY=0`` to disable filtering entirely (debug).
"""

from __future__ import annotations

import os

from data_layer.models import Championship

INCLUDE_CHAMPIONSHIP_KEYWORDS: tuple[str, ...] = (
    # ── continental / international club & national cups ──────────────────
    "دوري أبطال أوروبا",
    "الدوري الأوروبي",
    "دوري المؤتمر",
    "دوري أبطال آسيا",
    "دوري أبطال أفريقيا",
    "كأس الكونفيدرالية",
    "كوبا ليبرتادوريس",
    "كوبا سودا أمريكانا",
    "دوري أبطال العرب",
    "كأس العرب",
    "كأس العالم",
    "كأس القارات",
    "كأس أمم",
    "كأس آسيا",
    "كأس أفريقيا",
    # ── top European leagues & their main cups ────────────────────────────
    "الدوري الإنجليزي الممتاز",
    "كأس الاتحاد الإنجليزي",
    "الدوري الإسباني",
    "كأس ملك إسبانيا",
    "الدوري الإيطالي",
    "كأس إيطاليا",
    "الدوري الألماني",
    "كأس ألمانيا",
    "الدوري الفرنسي",
    "كأس فرنسا",
    "الدوري البرتغالي الممتاز",
    "الدوري الهولندي الممتاز",
    # ── biggest Arab leagues ──────────────────────────────────────────────
    "الدوري السعودي للمحترفين",
    "دوري روشن",
    "الدوري المصري",
    "الدوري العراقي",
    "دوري نجوم العراق",
    "الدوري المغربي",
    "الدوري الإماراتي للمحترفين",
    "الدوري القطري",
    # ── Americas ──────────────────────────────────────────────────────────
    "الدوري البرازيلي",
    "الدوري المكسيكي الممتاز",
    "الدوري الأمريكي لكرة القدم",
    "الأرجنتيني",
)

EXCLUDE_CHAMPIONSHIP_KEYWORDS: tuple[str, ...] = (
    # second tiers / reserves that share a name with a whitelisted league
    "دوري البطولة الإنجليزية",
    "القسم الثاني",
    "القسم الثالث",
    "دوري الدرجة الثانية",
    "الدوري العراقي الدرجة الأولى",
    "الدرجة الأولى السعودي",
    "دوري الرديف",
    "تحت 23",
    "تحت 21",
    "تحت 19",
    "سيدات",
)


def _enabled() -> bool:
    return os.environ.get("FILTER_POPULAR_ONLY", "1").strip().lower() not in (
        "0", "false", "no", "off",
    )


def is_popular_championship(name: str) -> bool:
    """True when the championship should be published / sent to the app."""
    if not _enabled():
        return True
    clean = (name or "").strip()
    if not clean:
        return False
    if any(bad in clean for bad in EXCLUDE_CHAMPIONSHIP_KEYWORDS):
        return False
    return any(good in clean for good in INCLUDE_CHAMPIONSHIP_KEYWORDS)


def filter_championships(championships: list[Championship]) -> list[Championship]:
    """Keep only popular championships (drops empty ones automatically)."""
    return [c for c in championships if is_popular_championship(c.name)]
