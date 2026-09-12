"""Parsers: raw HTML → typed models.

Two entry points:

- parse_fixtures_html(html, day) -> list[Championship]
    List page (either /ar/fixtures or a match_date_to answer). Builds every
    Championship and Match skeleton with the data embedded in the list item:
    teams, logos, round, kickoff clock, score/status. DOM order is preserved
    so the output mirrors the site's exact ordering.

- parse_match_details_html(match, html) -> None   (mutates the Match)
    Fills channels, commentator and — only for finished matches — the
    goal events read from the inline events timeline (status==1, with
    penalty / own-goal flags when the site makes them distinguishable).

Event status codes verified against real finished matches (2026-09-10):
    1  هدف (goal)            4  هدف في مرماه (own goal)
    2  بطاقة صفراء           5  ضربة جزاء (scored penalty)
    3  بطاقة حمراء           7  هدف ملغي (disallowed)
    8  تبديل لاعب           22  في العارضة (post)
Events are duplicated in the page (desktop + mobile copies) → dedupe by event_id.
For own goals the event sits under the player's own team; the goal itself is
credited to the opposite side.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, time as dtime
from typing import Any

from bs4 import BeautifulSoup, Tag

from data_layer import config
from data_layer.models import Championship, GoalEvent, Match, Score, Team

logger = logging.getLogger(__name__)

_ENDED_MARK = "انتهت"
_PENALTY_DECIDED_MARK = "ترجيح"  # ركلات الترجيح — still counts as ended
_PENALTY_MARK = "جزاء"
_OWN_GOAL_MARK = "في مرماه"
_OWN_GOAL_ALT = "عكسي"  # defensive fallback label
_DISALLOWED_MARK = "ملغي"
_GOAL_STATUSES = frozenset({"1", "4", "5"})
_OWN_GOAL_STATUS = "4"
_PENALTY_STATUS = "5"
_IGNORED_INFO_LABELS = {
    "البطولة", "الجولة", "ملعب المباراة", "الحكم", "وقت المباراة",
    "تاريخ المباراة", "توقيت المباراة", "موعد المباراة", "الأحداث",
    "الشوط الأول", "الشوط الثاني", "الشوط الثالث", "الشوط الرابع",
    "الوقت الإضافي", "ركلات الترجيح",
}
_NON_COMMENTATOR_VALUES = {"غير محدد", "غير معروف", "لا يوجد", "بدون معلق", "غير متوفر"}
_SCORE_LINE_RE = re.compile(r"-?\d+\s*-\s*\d+")
# Penalty events (5) are scored penalties: Philadelphia 5-0 decomposed into
# 3 classic goals (1) + 2 penalty goals (5).

# ── public API ─────────────────────────────────────────────────────────────


def parse_fixtures_html(html: str, day: date) -> list[Championship]:
    """Parse a Yalla Shoot league-blocks page into ordered Championships.

    Ordering is exactly the DOM order (championships and matches all keep it).
    """
    soup = BeautifulSoup(html, "lxml")
    championships: list[Championship] = []

    for wrapper in soup.select("div.matches-wrapper"):
        name = _attr(wrapper, "champ_title")
        if not name:
            continue  # skip empty/odd wrappers, keep going

        champ = Championship(
            name=name,
            logo_url=_attr(wrapper, "champ_img"),
            page_url=_championship_page_url(wrapper),
        )

        for node in wrapper.select("a.ajax-match-item"):
            try:
                match = _parse_match_node(node, day)
            except Exception as exc:  # never let one bad item kill the rest
                logger.warning("skipped a match node inside '%s': %s", name, exc)
                continue
            if match is not None:
                champ.matches.append(match)

        championships.append(champ)

    return championships


def parse_match_details_html(match: Match, detail_html: str) -> None:
    """Enrich a Match with channels, commentator and goal events (in place)."""
    soup = BeautifulSoup(detail_html, "lxml")
    _fill_info_block(match, soup)
    match.goals = _extract_goals(soup, match)


# ── fixtures list node ─────────────────────────────────────────────────────


def _parse_match_node(node: Tag, day: date) -> Match | None:
    match_id = node.get("match_id") or _id_from_attr(node)
    source_url = node.get("href") or ""
    if not match_id or not source_url:
        return None

    home_name, home_logo = _team_fields(node, "home_name", "home_image", "first-team")
    away_name, away_logo = _team_fields(node, "away_name", "away_image", "second-team")
    if not home_name or not away_name:
        return None

    match = Match(
        match_id=str(match_id),
        source_url=source_url,
        home=Team(home_name, home_logo),
        away=Team(away_name, away_logo),
        round=node.get("title") or "",
    )

    classes = set(node.get("class") or [])
    result_wrap = node.select_one(".result-wrap")

    if "live-match" in classes:
        match.status = "live"
        match.live_minute = _live_minute(node)
        match.score = _score(node)
    elif result_wrap is not None:
        rw_text = result_wrap.get_text(" ", strip=True)
        has_scorebox = result_wrap.select_one(".first-team-result") is not None
        if (
            _ENDED_MARK in rw_text
            or _PENALTY_DECIDED_MARK in rw_text
            or has_scorebox
        ):
            match.status = "ended"
            match.score = _score(node)
            match.penalty_score = _penalty_shootout(node)
        else:
            match.status = "not_started"
            match.kickoff = _kickoff(node, day)
    else:
        match.status = "not_started"
        match.kickoff = _kickoff(node, day)

    return match


def _penalty_shootout(node: Tag) -> tuple[int, int] | None:
    """Penalty shootout (home, away) from the success bullets, if present."""
    wrap = node.select_one(".penalties-wrapper")
    if wrap is None:
        return None
    home = len(wrap.select(".first-team-shots .p-shot-item.success"))
    away = len(wrap.select(".second-team-shots .p-shot-item.success"))
    if home == 0 and away == 0:
        return None
    return (home, away)


def _team_fields(
    node: Tag, name_attr: str, logo_attr: str, side_class: str
) -> tuple[str, str]:
    name = (node.get(name_attr) or "").strip()
    if not name:
        b = node.select_one(f".{side_class} b")
        name = b.get_text(" ", strip=True) if b else ""
    logo = (node.get(logo_attr) or "").strip()
    return name, logo


def _score(node: Tag) -> Score | None:
    home_el = node.select_one(".first-team-result")
    away_el = node.select_one(".second-team-result")
    home = _to_int(home_el.get_text(" ", strip=True)) if home_el else None
    away = _to_int(away_el.get_text(" ", strip=True)) if away_el else None
    if home is not None and away is not None:
        return Score(home=home, away=away)
    return None


def _live_minute(node: Tag) -> str:
    time_el = node.select_one('[id^="match-time-"] .number')
    if time_el:
        txt = " ".join(time_el.get_text(" ", strip=True).split())
        if txt:
            return txt
    minutes_el = node.select_one('[id^="minutes-"]')
    if minutes_el is not None:
        return minutes_el.get("data-minutes") or ""
    return ""


def _kickoff(node: Tag, day: date) -> datetime | None:
    date_el = node.select_one("b.match-date")
    if date_el is None:
        return None
    clock = " ".join(date_el.get_text(" ", strip=True).split())
    meridiem = node.select_one(".mb-meridiem")
    meridiem_text = meridiem.get_text(" ", strip=True) if meridiem else ""
    parsed = _parse_clock(clock, meridiem_text)
    if parsed is None:
        return None
    hour, minute = parsed
    return datetime.combine(day, dtime(hour, minute), tzinfo=config.TZ)


def _parse_clock(clock: str, meridiem: str) -> tuple[int, int] | None:
    m = re.search(r"(\d{1,2}):(\d{2})", clock)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2))
    is_pm = "م" in meridiem  # ص = AM, م = PM
    if is_pm and hour != 12:
        hour += 12
    elif not is_pm and hour == 12:
        hour = 0
    return hour, minute


def _championship_page_url(wrapper: Tag) -> str:
    link = wrapper.select_one("a.champ-title")
    return link.get("href") or "" if link else ""


# ── match detail page ──────────────────────────────────────────────────────


def _fill_info_block(match: Match, soup: BeautifulSoup) -> None:
    for row in soup.select(".match-info-item"):
        t_el = row.select_one(".title")
        c_el = row.select_one(".content")
        if t_el is None or c_el is None:
            continue
        title = t_el.get_text(" ", strip=True)
        content_txt = c_el.get_text(" ", strip=True)

        if title in _IGNORED_INFO_LABELS:
            if title == "الجولة" and not match.round and content_txt:
                match.round = content_txt
            continue

        if title in ("القناة", "القنوات", "القناة الناقلة"):
            chs = c_el.select("a.channel_info") or c_el.select("a")
            if chs:
                for ch in chs:
                    name = ch.get_text(" ", strip=True).strip()
                    if name and name not in match.channels and name not in _NON_COMMENTATOR_VALUES:
                        match.channels.append(name)
            elif content_txt and content_txt not in _NON_COMMENTATOR_VALUES:
                if content_txt not in match.channels:
                    match.channels.append(content_txt)
        elif title in ("المعلق", "المعلقين"):
            co = c_el.select_one('a[href*="/commentator/"]') or c_el.select_one("a")
            name = co.get_text(" ", strip=True).strip() if co else content_txt
            if name and name not in _NON_COMMENTATOR_VALUES and not match.commentator:
                match.commentator = name
        else:
            # Multi-channel layout: the row title IS the channel name and the
            # row content is its commentator (e.g. "بي إن سبورت 1" / "beIN 4K").
            # Guard against round/score lines that reuse the same columns.
            if "مباراة" in title or _SCORE_LINE_RE.search(title):
                continue
            if title and title not in match.channels and title not in _NON_COMMENTATOR_VALUES:
                match.channels.append(title)
            if (
                content_txt
                and content_txt not in _NON_COMMENTATOR_VALUES
                and not match.commentator
                and not _SCORE_LINE_RE.search(content_txt)
            ):
                match.commentator = content_txt


def _extract_goals(soup: BeautifulSoup, match: Match) -> list[GoalEvent]:
    """Goal events from the inline timeline, deduped and flagged.

    Included: status 1 (goal), 4 (own goal), 5 (scored penalty).
    Own goals sit under the player's own side; the goal counts for the
    opposite side — GoalEvent.team holds the *credited* team.

    Goals (per side) should sum to the final score; a mismatch is logged
    (never raised) so future site changes are noticed, not fatal.
    """
    home = match.home.name
    away = match.away.name
    seen: set[str] = set()
    raw: list[dict[str, Any]] = []

    for el in soup.select("div.match-event-item"):
        anchor = el.select_one("a.t-side, a.comm_pop")
        if anchor is None:
            continue

        event_id = anchor.get("event_id")
        if event_id:
            key = str(event_id)
            if key in seen:
                continue  # desktop + mobile duplicates
            seen.add(key)

        name = " ".join((anchor.get("event_name") or "").split())
        status = str(anchor.get("status") or "")
        player_a = (anchor.get("player_a") or "").strip()
        player_s = (anchor.get("player_s") or "").strip()
        minute = (anchor.get("min") or "").strip()
        side = _side_name(el, home, away)  # team the player belongs to

        is_own = (
            status == _OWN_GOAL_STATUS
            or _OWN_GOAL_MARK in name
            or _OWN_GOAL_ALT in name
        )
        is_pen = status == _PENALTY_STATUS or _PENALTY_MARK in name
        if status not in _GOAL_STATUSES and "هدف" not in name:
            continue
        if _DISALLOWED_MARK in name:
            continue
        if not player_a:
            continue

        # The wrapper class for-team-a/b reflects the *beneficiary* side of the
        # event. For own goals it holds the opponent (who gets the goal), not
        # the player's team — which is exactly what GoalEvent.team should be.
        credited = side
        raw.append(
            {
                "player": player_a,
                "team": credited,
                "minute": minute,
                "assist": player_s,
                "is_own_goal": is_own,
                "is_penalty": is_pen,
            }
        )

    goals = [
        GoalEvent(
            player=g["player"],
            team=g["team"],
            minute=g["minute"],
            assist=g["assist"],
            is_own_goal=g["is_own_goal"],
            is_penalty=g["is_penalty"],
        )
        for g in sorted(raw, key=lambda g: _minute_key(g["minute"]))
    ]

    if match.score is not None:
        expected = match.score.home + match.score.away
        if len(goals) != expected:
            logger.warning(
                "match %s (%s): %d goal events but final score is %s",
                match.match_id, match.source_url, len(goals), match.score,
            )
    return goals


def _minute_key(minute: str) -> int:
    m = re.search(r"\d+", minute)
    return int(m.group(0)) if m else 999


def _side_name(el: Tag, home: str, away: str) -> str:
    classes = set(el.get("class") or [])
    if "for-team-a" in classes:
        return home
    if "for-team-b" in classes:
        return away
    return ""


# ── tiny helpers ───────────────────────────────────────────────────────────


def _attr(tag: Tag | None, key: str) -> str:
    if tag is None:
        return ""
    value = tag.get(key)
    return str(value).strip() if value is not None else ""


def _id_from_attr(node: Tag) -> str:
    node_id = node.get("id") or ""
    return node_id.replace("match-", "") if node_id else ""


def _to_int(text: str) -> int | None:
    m = re.search(r"\d+", text)
    return int(m.group(0)) if m else None