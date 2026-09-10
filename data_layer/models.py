"""Typed structures for the scraped data.

Plain dataclasses: parser fills them, everything downstream (cards,
Telegram, filters) consumes them. No parsing logic lives here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

MatchStatus = Literal["not_started", "live", "ended"]


@dataclass(slots=True)
class Team:
    name: str
    logo_url: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "logo_url": self.logo_url}


@dataclass(slots=True)
class Score:
    home: int
    away: int

    def __str__(self) -> str:
        return f"{self.home} - {self.away}"


@dataclass(slots=True)
class GoalEvent:
    player: str  # scorer; for own-goal the player who scored against his side
    team: str  # side the event is listed under (home/away display name)
    minute: str  # e.g. "68" or "45+2" as shown on the site
    assist: str = ""  # empty when none given
    is_own_goal: bool = False
    is_penalty: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "player": self.player,
            "team": self.team,
            "minute": self.minute,
            "assist": self.assist,
            "is_own_goal": self.is_own_goal,
            "is_penalty": self.is_penalty,
        }


@dataclass(slots=True)
class Match:
    match_id: str
    source_url: str
    home: Team
    away: Team
    round: str = ""
    kickoff: datetime | None = None  # tz-aware, Asia/Baghdad
    status: MatchStatus = "not_started"
    live_minute: str = ""  # e.g. "70:47" while a match is live
    score: Score | None = None
    penalty_score: tuple[int, int] | None = None  # penalty shootout (home, away)
    channels: list[str] = field(default_factory=list)  # may be empty
    commentator: str = ""  # may be empty (e.g. MLS)
    goals: list[GoalEvent] = field(default_factory=list)  # only when finished

    @property
    def kickoff_iso(self) -> str | None:
        return self.kickoff.isoformat() if self.kickoff else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "source_url": self.source_url,
            "round": self.round,
            "kickoff": self.kickoff_iso,
            "status": self.status,
            "live_minute": self.live_minute,
            "score": {"home": self.score.home, "away": self.score.away}
            if self.score
            else None,
            "penalty_score": {"home": self.penalty_score[0], "away": self.penalty_score[1]}
            if self.penalty_score
            else None,
            "home": self.home.as_dict(),
            "away": self.away.as_dict(),
            "channels": list(self.channels),
            "commentator": self.commentator,
            "goals": [g.as_dict() for g in self.goals],
        }


@dataclass(slots=True)
class Championship:
    name: str
    logo_url: str = ""
    page_url: str = ""
    matches: list[Match] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "logo_url": self.logo_url,
            "page_url": self.page_url,
            "matches": [m.as_dict() for m in self.matches],
        }