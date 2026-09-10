"""Acceptance test for state_store (step 3/5).

Run:  python state_store\\selftest.py
Uses a throwaway temp DB and simulates a restart (fresh subprocess) to
prove dedup survives across runs. Prints PASS/FAIL for every criterion.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE))

from data_layer.models import Match, Team  # noqa: E402
from state_store import (  # noqa: E402
    already_sent,
    cleanup_old_events,
    get_daily_plan,
    mark_sent,
    save_daily_plan,
    set_db_path,
    update_match_status,
)

PASS = 0
FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}  {detail}")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="state_selftest_"))
    db = tmp / "test_state.db"
    print(f"using temp db: {db}")

    print("C1. mark_sent dedup (UNIQUE + INSERT OR IGNORE)")
    set_db_path(db)
    r1 = mark_sent("6106240", "prematch")
    r2 = mark_sent("6106240", "prematch")
    check("first mark inserts", r1 is True, f"got {r1}")
    check("second mark ignored silently (no error, no row)", r2 is False, f"got {r2}")
    check("already_sent True right after first mark", already_sent("6106240", "prematch") is True)
    check("different event type is a separate key",
          mark_sent("6106240", "fulltime") is True)
    check("other match unaffected",
          already_sent("9999999", "prematch") is False)
    from state_store.store import _connection as _c
    n = _c().execute("SELECT COUNT(*) FROM sent_events").fetchone()[0]
    check("table holds exactly 2 rows (no duplicates)", n == 2, f"count={n}")

    print("C2. restart simulation (state must persist across a fresh process)")
    child = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, r'%s')" % WORKSPACE +
         ";" "from state_store import set_db_path, already_sent;"
         "set_db_path(r'%s');" % db +
         "import sys;"
         "(print('PREMATCH=' + str(already_sent('6106240','prematch')),"
         " 'FULLTIME=' + str(already_sent('6106240','fulltime'))))"],
        capture_output=True, text=True, encoding="utf-8",
    )
    out = child.stdout.strip()
    ok = child.returncode == 0 and "PREMATCH=True" in out and "FULLTIME=True" in out
    check("fresh process sees previously saved sent events",
          ok, f"rc={child.returncode} out={out!r}")
    if child.stderr.strip():
        print("   stderr:", child.stderr.strip()[:300])

    print("C3. cleanup_old_events prunes > 1 week")
    st = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    mark_sent("OLD", "prematch", sent_at=st)
    deleted = cleanup_old_events(older_than_days=7)
    check("deleted exactly the old row",
          deleted == 1,
          f"deleted={deleted}")
    check("young events kept",
          already_sent("6106240", "prematch") is True
          and already_sent("OLD", "prematch") is False)

    print("C4. daily plan round trip")
    now = datetime(2026, 9, 10, 22, 0, tzinfo=__import__("zoneinfo").ZoneInfo("Asia/Baghdad"))
    matches = [
        Match(match_id="1", source_url="", home=Team("أ"), away=Team("ب"),
              kickoff=now, status="not_started", channels=["beIN Sports 2"]),
        Match(match_id="2", source_url="", home=Team("ج"), away=Team("د"),
              kickoff=None, status="live"),
        Match(match_id="3", source_url="", home=Team("ه"), away=Team("و"),
              kickoff=now, status="ended"),
    ]
    save_daily_plan(matches)
    plan = get_daily_plan()
    by_id = {r["match_id"]: r for r in plan}
    check("plan saved 3 matches", len(by_id) == 3, f"rows={len(by_id)}")
    check("kickoff date/time stored in Baghdad",
          by_id.get("1", {}).get("match_date") == "2026-09-10"
          and by_id.get("1", {}).get("match_time") == "22:00",
          str(by_id.get("1")))
    check("null kickoff stored as empty date/time",
          by_id.get("2", {}).get("match_date") == ""
          and by_id.get("2", {}).get("match_time") == "",
          str(by_id.get("2")))

    print("C5. update_match_status refreshes a row")
    update_match_status("1", "live")
    p1 = {r["match_id"]: r for r in get_daily_plan()}["1"]
    check("status updated to live", p1["status"] == "live", str(p1))
    check("last_checked_at populated", bool(p1["last_checked_at"]), str(p1))

    print("C6. re-saving the plan upserts (no duplicates)")
    save_daily_plan(matches)
    check("still 3 rows after upsert", len(get_daily_plan()) == 3)

    print("C7. concurrent mark_sent stays safe")
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda _: mark_sent("RACE", "prematch"),
                              range(64)))
    from state_store.store import _connection as _c2
    n_race = _c2().execute(
        "SELECT COUNT(*) FROM sent_events WHERE match_id='RACE'").fetchone()[0]
    check("concurrent writes inserted exactly one row",
          results.count(True) == 1 and n_race == 1,
          f"inserted={results.count(True)} rows={n_race}")

    print()
    print(f"RESULT: {PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())