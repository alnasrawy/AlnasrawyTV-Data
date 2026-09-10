"""state_store — persistent SQLite state store (step 3/5).

Public API::

    already_sent(match_id, event_type) -> bool
    mark_sent(match_id, event_type, sent_at=None) -> bool
    cleanup_old_events(older_than_days=7) -> int
    save_daily_plan(matches: list[Match]) -> None
    get_daily_plan() -> list[dict]
    update_match_status(match_id, status) -> None

Also exposed: set_db_path(path), EVENT_PREMATCH / EVENT_FULLTIME.
"""

from .store import (
    EVENT_FULLTIME,
    EVENT_PREMATCH,
    already_sent,
    cleanup_old_events,
    get_daily_plan,
    mark_sent,
    save_daily_plan,
    set_db_path,
    update_match_status,
)

__all__ = [
    "EVENT_FULLTIME",
    "EVENT_PREMATCH",
    "already_sent",
    "cleanup_old_events",
    "get_daily_plan",
    "mark_sent",
    "save_daily_plan",
    "set_db_path",
    "update_match_status",
]