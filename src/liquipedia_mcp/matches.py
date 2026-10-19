"""Match queries: results, upcoming matches, date ranges and per-game details.

Each query function costs at most one API request (fewer when cached) and returns a
:class:`~liquipedia_mcp.models.MatchList`.

Query rules (verified against real LPDB answers for rocketleague and leagueoflegends):

* ``order=date DESC`` without ``[[finished::1]]`` returns the matches scheduled
  furthest in the future first, so results, upcoming matches and date ranges use
  separate conditions and orderings.
* Without a tier filter, C/D-tier leagues dominate. Queries without a team or
  tournament therefore default to ``max_tier=1`` (S-Tier). Team/tournament queries use
  no tier filter.
* Unplayed scores are ``-1`` placeholders and never reported as results; matches with
  an undetermined opponent ("TBD") are left out and counted in ``omitted_tbd``.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from liquipedia_mcp._parse import (
    clean_player_name,
    parse_date,
    to_bool,
    to_dict,
    to_int,
    to_list,
    to_str,
)
from liquipedia_mcp.client import RANGE_TTL, LiquipediaClient
from liquipedia_mcp.errors import InvalidInputError
from liquipedia_mcp.models import Game, Match, MatchList, Opponent, PickedCharacter
from liquipedia_mcp.validation import (
    clamp,
    lpdb_datetime,
    parse_utc,
    validate_name,
    validate_tier,
    validate_wiki,
    validate_wikis,
)

MATCH_FIELDS = (
    "tournament,date,dateexact,winner,finished,bestof,status,liquipediatier,"
    "liquipediatiertype,section,tickername,game,extradata,match2opponents,"
    "match2games,match2bracketdata"
)
MAX_MATCHES = 50
PICKS_MAX_MATCHES = 3
"""Champion picks are large; they are only included for this many matches or fewer."""
MAX_RANGE = timedelta(days=31)
_TBD_NAMES = {"", "tbd", "tba", "to be determined"}


# ----------------------------------------------------------------------- parsing


def _opponent(raw: Any) -> Opponent | None:
    data = raw if isinstance(raw, dict) else {}
    name = to_str(data.get("name")) or ""
    if name.lower() in _TBD_NAMES:
        return None
    score = to_int(data.get("score"))
    status = to_str(data.get("status"))
    players: list[str] = []
    for player in to_list(data.get("match2players")):
        if not isinstance(player, dict):
            continue
        pname = to_str(player.get("name")) or to_str(player.get("displayname"))
        if pname:
            players.append(clean_player_name(pname))
    return Opponent(
        name=name,
        score=score if score is not None and score >= 0 else None,
        status=status if status and status.upper() != "S" else None,
        players=players,
    )


def _picks(raw_opponent: Any) -> list[PickedCharacter]:
    picks: list[PickedCharacter] = []
    for player in to_list(to_dict(raw_opponent).get("players")):
        if not isinstance(player, dict):
            continue
        name, character = to_str(player.get("player")), to_str(player.get("character"))
        if name and character:
            picks.append(PickedCharacter(clean_player_name(name), character))
    return picks


def _game(raw: Any, number: int, names: tuple[str, str], include_picks: bool) -> Game | None:
    data = to_dict(raw)
    if not data:
        return None
    if str(data.get("status", "")).lower() == "notplayed":
        return None
    if str(data.get("resulttype", "")).lower() == "np":
        return None
    scores = to_list(data.get("scores"))
    if len(scores) != 2:
        return None
    s1, s2 = (to_int(s) for s in scores)
    if s1 is None or s2 is None or s1 < 0 or s2 < 0:
        return None
    extradata = to_dict(data.get("extradata"))
    opponents = to_list(data.get("opponents"))
    kills = [to_int(to_dict(to_dict(o).get("stats")).get("kills")) for o in opponents[:2]]
    kills += [None] * (2 - len(kills))
    winner = names[0] if s1 > s2 else names[1] if s2 > s1 else None
    game = Game(
        number=number,
        score1=s1,
        score2=s2,
        winner_name=winner,
        overtime=to_bool(extradata.get("ot")),
        map=to_str(data.get("map")),
        length=to_str(data.get("length")),
        kills1=kills[0],
        kills2=kills[1],
    )
    if include_picks and len(opponents) >= 2:
        game.picks1 = _picks(opponents[0])
        game.picks2 = _picks(opponents[1])
    return game


def _round_name(bracketdata: Any) -> str | None:
    header = to_str(to_dict(bracketdata).get("header"))
    if not header or header.startswith("!"):
        # "!l4!x"-style headers are wiki shorthands; don't guess what they mean.
        return None
    return header


def _mvp(extradata: dict[str, Any]) -> str | None:
    players = to_dict(extradata.get("mvp")).get("players")
    entries: list[tuple[int | None, str]] = []

    def name_of(value: Any) -> str | None:
        if isinstance(value, dict):
            name = to_str(value.get("displayname")) or to_str(value.get("name"))
        else:
            name = to_str(value)
        return clean_player_name(name) if name else None

    if isinstance(players, dict):
        for key, value in players.items():
            for item in value if isinstance(value, list) else [value]:
                if name := name_of(item):
                    entries.append((to_int(key), name))
    elif isinstance(players, list):
        for item in players:
            if name := name_of(item):
                entries.append((None, name))
    if not entries:
        return None
    grouped: dict[str, list[int]] = {}
    for game, name in sorted(entries, key=lambda e: (e[0] is None, e[0] or 0)):
        games = grouped.setdefault(name, [])
        if game is not None and game not in games:
            games.append(game)
    parts = []
    for name, games in grouped.items():
        label = "+".join(str(g) for g in games)
        parts.append(f"{name} (Game {label})" if games else name)
    return ", ".join(parts)


def parse_match(
    row: dict[str, Any], wiki: str | None = None, include_picks: bool = False
) -> Match | None:
    """Turn one LPDB ``match`` row into a :class:`Match`.

    Returns ``None`` when an opponent is not determined yet (TBD); such rows must not
    be presented as a pairing.
    """
    opponents = to_list(row.get("match2opponents"))
    if len(opponents) != 2:
        return None
    op1, op2 = _opponent(opponents[0]), _opponent(opponents[1])
    if op1 is None or op2 is None:
        return None
    finished = to_bool(row.get("finished"))
    if not finished:
        # Placeholder or partial scores of unfinished matches are not results.
        op1.score = op2.score = None

    winner_name: str | None = None
    if finished:
        if op1.score is not None and op2.score is not None and op1.score != op2.score:
            winner_name = op1.name if op1.score > op2.score else op2.name
        else:
            winner = str(row.get("winner", "")).strip()
            winner_name = {"1": op1.name, "2": op2.name}.get(winner)

    games: list[Game] = []
    if finished:
        for index, raw_game in enumerate(to_list(row.get("match2games")), start=1):
            game = _game(raw_game, index, (op1.name, op2.name), include_picks)
            if game:
                games.append(game)

    tier = to_int(row.get("liquipediatier"))
    return Match(
        wiki=to_str(row.get("wiki")) or wiki,
        tournament=to_str(row.get("tournament")) or "Unknown tournament",
        date=parse_date(row.get("date")),
        date_exact=to_bool(row.get("dateexact")),
        opponent1=op1,
        opponent2=op2,
        finished=finished,
        winner_name=winner_name,
        best_of=to_int(row.get("bestof")) or None,
        tier=tier if tier and tier > 0 else None,
        tier_type=to_str(row.get("liquipediatiertype")),
        section=to_str(row.get("section")),
        round=_round_name(row.get("match2bracketdata")),
        ticker_name=to_str(row.get("tickername")),
        status=to_str(row.get("status")),
        games=games,
        mvp=_mvp(to_dict(row.get("extradata"))) if finished else None,
    )


def parse_matches(
    rows: Iterable[dict[str, Any]],
    wiki: str | None,
    limit: int,
    include_picks: bool | None = None,
) -> tuple[list[Match], int, bool]:
    """Parse rows in order, skip TBD pairings, stop at ``limit``.

    Returns ``(matches, omitted_tbd, includes_picks)``. ``omitted_tbd`` only counts TBD
    rows that fall inside the returned window. With ``include_picks=None`` champion
    picks are included when at most :data:`PICKS_MAX_MATCHES` matches are returned.
    """
    kept: list[tuple[dict[str, Any], Match]] = []
    omitted = 0
    for row in rows:
        if len(kept) >= limit:
            break
        match = parse_match(row, wiki)
        if match is None:
            omitted += 1
        else:
            kept.append((row, match))
    if include_picks is None:
        include_picks = len(kept) <= PICKS_MAX_MATCHES
    if include_picks:
        return [parse_match(r, wiki, include_picks=True) or m for r, m in kept], omitted, True
    return [m for _, m in kept], omitted, False


# ----------------------------------------------------------------------- queries


def _conditions(*parts: str | None) -> str:
    return " AND ".join(p for p in parts if p)


def _scope(
    team: str | None, tournament: str | None, max_tier: int | None
) -> tuple[str | None, str | None, int | None, list[str]]:
    """Validate filters; apply the tier filter only to general (team-less) queries."""
    team = validate_name(team, "team") if team else None
    tournament = validate_name(tournament, "tournament") if tournament else None
    parts: list[str] = []
    if team:
        parts.append(f"[[opponent::{team}]]")
    if tournament:
        parts.append(f"[[tournament::{tournament}]]")
    tier: int | None = None
    if not team and not tournament:
        tier = validate_tier(1 if max_tier is None else max_tier)
        parts.append(f"[[liquipediatier::<{tier + 1}]]")
    return team, tournament, tier, parts


def _now(now: datetime | None) -> datetime:
    return parse_utc(now) if now is not None else datetime.now(UTC)


async def get_results(
    client: LiquipediaClient,
    wiki: str,
    *,
    team: str | None = None,
    tournament: str | None = None,
    max_tier: int | None = None,
    limit: int = 10,
) -> MatchList:
    """Finished matches, newest first (``[[finished::1]]``, ``date DESC``)."""
    wiki = validate_wiki(wiki)
    limit = clamp(limit, 1, MAX_MATCHES)
    team, tournament, tier, parts = _scope(team, tournament, max_tier)
    rows = await client.query(
        "match",
        wiki,
        conditions=_conditions("[[finished::1]]", *parts),
        fields=MATCH_FIELDS,
        order="date DESC",
        limit=limit,
    )
    matches, omitted, picks = parse_matches(rows, wiki, limit)
    return MatchList(
        kind="results",
        wikis=[wiki],
        matches=matches,
        team=team,
        tournament=tournament,
        max_tier=tier,
        omitted_tbd=omitted,
        includes_picks=picks,
    )


async def get_upcoming(
    client: LiquipediaClient,
    wiki: str,
    *,
    team: str | None = None,
    tournament: str | None = None,
    max_tier: int | None = None,
    limit: int = 10,
    now: datetime | None = None,
) -> MatchList:
    """Scheduled matches after ``now``, soonest first (``[[finished::0]]``, ``date ASC``)."""
    wiki = validate_wiki(wiki)
    limit = clamp(limit, 1, MAX_MATCHES)
    team, tournament, tier, parts = _scope(team, tournament, max_tier)
    start = _now(now)
    rows = await client.query(
        "match",
        wiki,
        conditions=_conditions("[[finished::0]]", f"[[date::>{lpdb_datetime(start)}]]", *parts),
        fields=MATCH_FIELDS,
        order="date ASC",
        # Over-fetch so that dropping TBD pairings still leaves `limit` matches.
        limit=min(limit * 2 + 10, 200),
    )
    matches, omitted, _ = parse_matches(rows, wiki, limit, include_picks=False)
    return MatchList(
        kind="upcoming",
        wikis=[wiki],
        matches=matches,
        team=team,
        tournament=tournament,
        max_tier=tier,
        start=start,
        omitted_tbd=omitted,
    )


async def get_matches_between(
    client: LiquipediaClient,
    wikis: str | Iterable[str],
    start_utc: str | datetime,
    end_utc: str | datetime,
    *,
    max_tier: int | None = None,
    team: str | None = None,
    limit: int = MAX_MATCHES,
) -> MatchList:
    """All matches (played or not) in ``[start, end]``, chronological, several wikis in
    one request. Finished ones carry scores; others are listed as scheduled."""
    wiki_list = validate_wikis(wikis)
    start, end = parse_utc(start_utc, "start_utc"), parse_utc(end_utc, "end_utc")
    if end <= start:
        raise InvalidInputError("end_utc must be after start_utc.")
    if end - start > MAX_RANGE:
        raise InvalidInputError("The time range may span at most 31 days.")
    limit = clamp(limit, 1, MAX_MATCHES * 4)
    team, _, tier, parts = _scope(team, None, max_tier)
    rows = await client.query(
        "match",
        wiki_list,
        conditions=_conditions(
            f"[[date::>{lpdb_datetime(start)}]]", f"[[date::<{lpdb_datetime(end)}]]", *parts
        ),
        fields=MATCH_FIELDS,
        order="date ASC",
        limit=min(limit * 2 + 10, 500),
        ttl=RANGE_TTL,
    )
    single = wiki_list[0] if len(wiki_list) == 1 else None
    matches, omitted, _ = parse_matches(rows, single, limit, include_picks=False)
    return MatchList(
        kind="between",
        wikis=wiki_list,
        matches=matches,
        team=team,
        max_tier=tier,
        start=start,
        end=end,
        omitted_tbd=omitted,
    )


async def get_match_details(
    client: LiquipediaClient,
    wiki: str,
    team: str,
    *,
    opponent: str | None = None,
    limit: int = 1,
) -> MatchList:
    """The team's latest finished match(es) with every game: scores, overtime, length,
    kills, maps, MVP and (League of Legends) champion picks. At most 3 matches."""
    wiki = validate_wiki(wiki)
    team = validate_name(team, "team")
    opponent = validate_name(opponent, "opponent") if opponent else None
    limit = clamp(limit, 1, PICKS_MAX_MATCHES)
    rows = await client.query(
        "match",
        wiki,
        conditions=_conditions("[[finished::1]]", f"[[opponent::{team}]]"),
        fields=MATCH_FIELDS,
        order="date DESC",
        # Filtering by opponent happens locally, so look a bit further back.
        limit=30 if opponent else limit,
    )
    if opponent:
        wanted = opponent.casefold()
        rows = [
            r
            for r in rows
            if any(
                (to_str(to_dict(o).get("name")) or "").casefold() == wanted
                for o in to_list(r.get("match2opponents"))
            )
        ]
    matches, omitted, _ = parse_matches(rows, wiki, limit, include_picks=True)
    return MatchList(
        kind="details",
        wikis=[wiki],
        matches=matches,
        team=team,
        omitted_tbd=omitted,
        includes_picks=True,
    )
