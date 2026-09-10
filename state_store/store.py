"""Persistent state store: dedup + daily plan.

A single local SQLite file (no external DB server). The shared connection
is guarded by one reentrant lock so any function may be called from
multiple threads. ``isolation_level=None`` commits every statement
immediately, so a crash mid-run can never leave half-written state behind,
and ``INSERT OR IGNORE`` under a ``UNIQUE(match_id, event_type)`` constraint
is the last line of defense against double sends.
"""

from __future__ import annotations

import pathlib
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from zoneinfo import ZoneInfo

from data_layer.models import Match

BAGHDAD = ZoneInfo("Asia/Baghdad")

_DEFAULT_DB = str(pathlib.Path(__file__).resolve().parent.parent / "state.db")

DB_PATH: Optional[str] = None
_state_lock = threading.RLock()
_conn: Optional[sqlite3.Connection] = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sent_events (
    match_id  TEXT NOT NULL,
    event_type TEXT NOT NULL,
    sent_at   TEXT NOT NULL,
    UNIQUE(match_id, event_type)
);

CREATE TABLE IF NOT EXISTS daily_plan (
    match_id       TEXT PRIMARY KEY,
    match_date     TEXT NOT NULL,
    match_time     TEXT NOT NULL,
    status         TEXT NOT NULL,
    last_checked_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_sent_events_sent_at ON sent_events(sent_at);
"""

EVENT_PREMATCH = "prematch"
EVENT_FULLTIME = "fulltime"


def set_db_path(path: str | pathlib.Path) -> None:
    """Point the store at a different SQLite file (before first use)."""
    global DB_PATH, _conn
    with _state_lock:
        DB_PATH = str(path)
        _conn = None  # reopen lazily on the new path


def _connection() -> sqlite3.Connection:
    global _conn
    path = DB_PATH or _DEFAULT_DB
    if _conn is None:
        _conn = sqlite3.connect(
            path, check_same_thread=False, isolation_level=None
        )
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA busy_timeout=5000")
        _conn.executescript(_SCHEMA)
    return _conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── sent events (dedup) ───────────────────────────────────────────────────


def already_sent(match_id: str, event_type: str) -> bool:
    """Return True when this (match, event) was already marked sent."""
    with _state_lock:
        row = _connection().execute(
            "SELECT 1 FROM sent_events WHERE match_id = ? AND event_type = ?",
            (match_id, event_type),
        ).fetchone()
    return row is not None


def mark_sent(match_id: str, event_type: str, sent_at: str | None = None) -> bool:
    """Record a sent event. Returns True if newly inserted.

    A duplicate call returns False — the UNIQUE constraint + INSERT OR
    IGNORE silently drops it instead of duplicating the row.
    """
    with _state_lock:
        cur = _connection().execute(
            "INSERT OR IGNORE INTO sent_events (match_id, event_type, sent_at)"
            " VALUES (?, ?, ?)",
            (match_id, event_type, sent_at or _now_iso()),
        )
    return cur.rowcount == 1


def cleanup_old_events(older_than_days: int = 7) -> int:
    """Delete sent_events recorded before `now - days`. Returns deleted rows."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()
    with _state_lock:
        cur = _connection().execute(
            "DELETE FROM sent_events WHERE sent_at < ?", (cutoff,)
        )
    return cur.rowcount


# ── daily plan ────────────────────────────────────────────────────────────


def _plan_row(match: Match) -> dict[str, str]:
    date_s = ""
    time_s = ""
    if match.kickoff is not None:
        k = match.kickoff.astimezone(BAGHDAD) if match.kickoff.tzinfo else match.kickoff.replace(tzinfo=BAGHDAD)
        date_s = k.strftime("%Y-%m-%d")
        time_s = k.strftime("%H:%M")
    return {
        "match_id": str(match.match_id),
        "match_date": date_s,
        "match_time": time_s,
        "status": match.status,
    }


def save_daily_plan(matches: list[Match]) -> None:
    """Upsert the full day plan. Existing rows are refreshed in place."""
    with _state_lock:
        conn = _connection()
        for m in matches:
            r = _plan_row(m)
            conn.execute(
                "INSERT INTO daily_plan"
                " (match_id, match_date, match_time, status, last_checked_at)"
                " VALUES (:match_id, :match_date, :match_time, :status, :checked)"
                " ON CONFLICT(match_id) DO UPDATE SET"
                "   match_date = excluded.match_date,"
                "   match_time = excluded.match_time,"
                "   status = excluded.status,"
                "   last_checked_at = excluded.last_checked_at",
                {**r, "checked": _now_iso()},
            )


def get_daily_plan() -> list[dict]:
    """All plan rows as dicts (match_id, match_date, match_time, status, last_checked_at)."""
    with _state_lock:
        rows = _connection().execute(
            "SELECT match_id, match_date, match_time, status, last_checked_at"
            " FROM daily_plan ORDER BY rowid"
        ).fetchall()
    return [dict(r) for r in rows]


def update_match_status(match_id: str, status: str) -> None:
    """Refresh one match's status + last_checked_at without touching the plan shape."""
    with _state_lock:
        _connection().execute(
            "UPDATE daily_plan SET status = ?, last_checked_at = ? WHERE match_id = ?",
            (status, _now_iso(), str(match_id)),
        )