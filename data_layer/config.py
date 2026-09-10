"""Global configuration for the data layer.

All site/network constants live here so they can be tuned in one place.
Time zone is pinned to Asia/Baghdad (GMT+3) on purpose: "today" must be
bounded the same way regardless of where the worker is running.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

# ── Time zone ──────────────────────────────────────────────────────────────
TZ = ZoneInfo("Asia/Baghdad")  # GMT+3, no DST

# ── Site ───────────────────────────────────────────────────────────────────
BASE_URL = "https://www.ysscores.com"
FIXTURES_PATH = "/ar/fixtures"
DATE_ENDPOINT_PATH = "/ar/match_date_to"
HOME_PATH = "/"  # GET this first: it issues the XSRF-TOKEN cookie

# ── Identity / politeness ──────────────────────────────────────────────────
# Honest, verifiable UA (robots.txt allows /ar/fixtures; no obfuscation).
USER_AGENT = (
    "AlnasrawyTV-DataBot/1.0 "
    "(match data collector; robots.txt respected; delay 1-3s)"
)
ACCEPT_HTML = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
ACCEPT_LANGUAGE = "ar,en;q=0.8"

# Random delay between two HTTP round-trips (seconds). Keeps load low.
REQUEST_DELAY_RANGE: tuple[float, float] = (1.0, 3.0)
# Only 1–2 connections in flight at the same time.
MAX_CONCURRENCY = 2

# ── Robustness ─────────────────────────────────────────────────────────────
HTTP_TIMEOUT = 25.0  # seconds, connect+read
RETRY_MAX_ATTEMPTS = 3
RETRY_BACKOFF_BASE = 1.5  # seconds; wait = base * 2 ** (attempt - 1)
RETRY_STATUS_CODES = frozenset({429, 503})
# match_date_to answers 419 when the CSRF cookie is stale — retry after refresh.
CSRF_ERROR_STATUS = 419

# ── Configuration helpers ──────────────────────────────────────────────────
# Yalla Shoot's date picker sends the locale string "September 11,2026".
LOCALE_MONTHS: tuple[str, ...] = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def locale_date(dt) -> str:
    """Format a date the way the site's own picker does (`data-locale`)."""
    return f"{LOCALE_MONTHS[dt.month - 1]} {dt.day},{dt.year}"