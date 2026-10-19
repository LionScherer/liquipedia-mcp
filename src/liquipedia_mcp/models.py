"""Structured results returned by the core functions.

All dataclasses offer ``to_dict()`` producing JSON-compatible data (datetimes become
ISO 8601 strings). Every top-level result carries ``source`` with the attribution that
the CC-BY-SA 3.0 license requires.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

ATTRIBUTION = "Source: Liquipedia (liquipedia.net), CC-BY-SA 3.0"
SOURCE_URL = "https://liquipedia.net"
LICENSE = "CC-BY-SA 3.0"

TIER_NAMES = {1: "S-Tier", 2: "A-Tier", 3: "B-Tier", 4: "C-Tier", 5: "D-Tier"}


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    return value


class _Serializable:
    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))  # type: ignore[call-overload]


@dataclass
class Source(_Serializable):
    name: str = "Liquipedia"
    url: str = SOURCE_URL
    license: str = LICENSE
    text: str = ATTRIBUTION


# ---------------------------------------------------------------------- matches


@dataclass
class Opponent(_Serializable):
    name: str
    """Team (or player) name; never empty for matches returned by the core."""
    score: int | None
    """Series score; ``None`` when not played yet (LPDB stores -1 as a placeholder)."""
    status: str | None = None
    """LPDB opponent status if it is not a plain score, e.g. ``"W"``/``"FF"``/``"DQ"``."""
    players: list[str] = field(default_factory=list)


@dataclass
class PickedCharacter(_Serializable):
    player: str
    character: str


@dataclass
class Game(_Serializable):
    number: int
    """1-based position of the game in the series (counting only played games)."""
    score1: int
    """Score of the match's first opponent."""
    score2: int
    winner_name: str | None
    overtime: bool = False
    map: str | None = None
    length: str | None = None
    kills1: int | None = None
    kills2: int | None = None
    picks1: list[PickedCharacter] = field(default_factory=list)
    picks2: list[PickedCharacter] = field(default_factory=list)


@dataclass
class Match(_Serializable):
    wiki: str | None
    tournament: str
    date: datetime | None
    """UTC kickoff. When ``date_exact`` is False only the day is known and the time
    (usually 00:00) is a placeholder: use ``day`` instead."""
    date_exact: bool
    """False when only the day is known."""
    opponent1: Opponent
    opponent2: Opponent
    finished: bool
    winner_name: str | None
    """Explicit winner by name (never by index). ``None`` if open or a draw."""
    best_of: int | None = None
    tier: int | None = None
    tier_type: str | None = None
    section: str | None = None
    """E.g. "Playoffs", "Group Stage"."""
    round: str | None = None
    """Readable round name such as "Grand Final"; omitted when only a wiki shorthand exists."""
    ticker_name: str | None = None
    status: str | None = None
    games: list[Game] = field(default_factory=list)
    mvp: str | None = None
    """E.g. "Faker (Game 1+2), Zeus (Game 3)" (League of Legends)."""
    day: str | None = None
    """UTC calendar day of ``date`` ("2026-10-20"); the only meaningful part of
    day-only (``date_exact=False``) matches."""

    @property
    def score_line(self) -> str | None:
        """E.g. "Team A 3–1 Team B", or ``None`` when no valid score exists."""
        if self.opponent1.score is None or self.opponent2.score is None:
            return None
        return (
            f"{self.opponent1.name} {self.opponent1.score}–{self.opponent2.score} "
            f"{self.opponent2.name}"
        )


@dataclass
class MatchList(_Serializable):
    kind: str
    """"results", "upcoming", "between" or "details"."""
    wikis: list[str]
    matches: list[Match]
    team: str | None = None
    tournament: str | None = None
    max_tier: int | None = None
    start: datetime | None = None
    end: datetime | None = None
    omitted_tbd: int = 0
    """Matches left out because an opponent is not determined yet."""
    include_minor_types: bool = True
    """False when qualifiers, showmatches, weeklies etc. were filtered out (general
    queries with a tier filter only)."""
    omitted_date_only: int = 0
    """Day-only matches left out of a time range because their day is only partly
    inside it (see :func:`~liquipedia_mcp.matches.get_matches_between`)."""
    truncated: bool = False
    """True when more matches matched than are returned."""
    truncated_count: int = 0
    """How many matches were cut off (a lower bound when ``truncated_more`` is set)."""
    truncated_more: bool = False
    """The API answer itself hit the request limit, so even more matches may exist."""
    includes_picks: bool = False
    source: Source = field(default_factory=Source)


# --------------------------------------------------------------------- standings


@dataclass
class Record(_Serializable):
    wins: int = 0
    losses: int = 0
    draws: int = 0

    @property
    def played(self) -> int:
        return self.wins + self.losses + self.draws


@dataclass
class StandingsRow(_Serializable):
    team: str
    placement: int | None
    matches: Record
    games: Record
    status: str | None = None
    """"advanced", "advanced (bye)", "advanced (seeded)", "eliminated" or ``None``."""
    round_index: int | None = None


@dataclass
class StandingsGroup(_Serializable):
    pagename: str
    standings_index: int
    title: str
    """tournament – stage – group title, de-duplicated."""
    tournament: str | None = None
    stage: str | None = None
    group_title: str | None = None
    end_date: str | None = None
    finished: bool | None = None
    started: bool = False
    """False when no team has played a match yet; placements are then meaningless."""
    show_game_record: bool = True
    """False when game records carry no information (e.g. Bo1 Swiss)."""
    leader: str | None = None
    rows: list[StandingsRow] = field(default_factory=list)


@dataclass
class StandingsResult(_Serializable):
    wiki: str
    groups: list[StandingsGroup]
    team: str | None = None
    tournament: str | None = None
    next_up: StandingsGroup | None = None
    """A later phase the team is in that has not started yet (rows not loaded)."""
    source: Source = field(default_factory=Source)
