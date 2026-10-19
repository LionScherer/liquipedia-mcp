"""Plain-English text for the structured results (used by the MCP server).

Applications that want another language or layout should format the dataclasses from
:mod:`liquipedia_mcp.models` themselves; they must keep the attribution line.
"""

from __future__ import annotations

from datetime import datetime

from liquipedia_mcp.models import (
    ATTRIBUTION,
    TIER_NAMES,
    Game,
    Match,
    MatchList,
    Record,
    StandingsGroup,
    StandingsResult,
)

WIKI_NAMES = {
    "rocketleague": "Rocket League",
    "leagueoflegends": "League of Legends",
}


def wiki_name(wiki: str | None) -> str:
    if not wiki:
        return ""
    return WIKI_NAMES.get(wiki, wiki)


def _when(date: datetime | None, exact: bool) -> str:
    if date is None:
        return "date TBA"
    if not exact:
        return f"{date:%Y-%m-%d} (time TBA)"
    return f"{date:%Y-%m-%d %H:%M} UTC"


def _tier_filter(max_tier: int | None) -> str | None:
    if max_tier is None:
        return None
    if max_tier == 1:
        return "S-Tier only"
    return f"S-Tier to {TIER_NAMES[max_tier]}"


def _game(game: Game) -> str:
    text = f"G{game.number} {game.score1}–{game.score2}"
    extras = []
    if game.overtime:
        extras.append("OT")
    if game.map:
        extras.append(game.map)
    if game.length:
        extras.append(game.length)
    if game.kills1 is not None and game.kills2 is not None:
        extras.append(f"kills {game.kills1}–{game.kills2}")
    return f"{text} ({', '.join(extras)})" if extras else text


def format_match(match: Match, number: int | None = None, show_wiki: bool = False) -> str:
    context = [_when(match.date, match.date_exact)]
    if show_wiki and match.wiki:
        context.append(wiki_name(match.wiki))
    context.append(match.tournament)
    stage = ", ".join(p for p in (match.section, match.round) if p)
    if stage:
        context.append(stage)
    if match.best_of:
        context.append(f"Bo{match.best_of}")
    head = " | ".join(context)
    lines = [f"{number}. {head}" if number is not None else head]
    a, b = match.opponent1, match.opponent2

    if match.finished:
        score = match.score_line
        if score:
            lines.append(f"   Result: {score}. Winner: {match.winner_name or 'none (draw)'}.")
        elif match.winner_name:
            loser = b if match.winner_name == a.name else a
            how = f" ({loser.name}: {loser.status})" if loser.status else ""
            lines.append(f"   Result: {a.name} vs {b.name} – {match.winner_name} won{how}.")
        else:
            lines.append(f"   {a.name} vs {b.name} – finished, no score available.")
        if match.games:
            games = ", ".join(_game(g) for g in match.games)
            lines.append(f"   Games ({a.name}–{b.name}): {games}")
        if match.mvp:
            lines.append(f"   MVP: {match.mvp}")
        for game in match.games:
            if game.picks1 or game.picks2:
                p1 = ", ".join(f"{p.player} ({p.character})" for p in game.picks1) or "–"
                p2 = ", ".join(f"{p.player} ({p.character})" for p in game.picks2) or "–"
                lines.append(f"   G{game.number} picks – {a.name}: {p1}; {b.name}: {p2}")
    else:
        lines.append(f"   {a.name} vs {b.name} – not played yet")
    return "\n".join(lines)


def format_match_list(result: MatchList) -> str:
    wikis = ", ".join(wiki_name(w) for w in result.wikis)
    title = {
        "results": "Latest results",
        "upcoming": "Upcoming matches",
        "details": "Match details",
    }.get(result.kind, "Matches")
    if result.kind == "between" and result.start and result.end:
        title = f"Matches {result.start:%Y-%m-%d %H:%M} – {result.end:%Y-%m-%d %H:%M} UTC"
    filters = [
        f"team: {result.team}" if result.team else None,
        f"tournament: {result.tournament}" if result.tournament else None,
        _tier_filter(result.max_tier),
    ]
    header = f"{title} – {wikis}"
    shown = [f for f in filters if f]
    if shown:
        header += f" ({'; '.join(shown)})"
    order = {"results": "newest first", "details": "newest first"}.get(
        result.kind, "in chronological order"
    )
    lines = [f"{header}, {order}:"]
    if not result.matches:
        lines.append("No matches found.")
    show_wiki = len(result.wikis) > 1
    for i, match in enumerate(result.matches, start=1):
        lines.append(format_match(match, i, show_wiki))
    if result.omitted_tbd:
        lines.append(
            f"({result.omitted_tbd} match(es) with opponents not determined yet were left out.)"
        )
    lines.append(ATTRIBUTION)
    return "\n".join(lines)


def _record(record: Record) -> str:
    if record.draws:
        return f"{record.wins}–{record.losses}–{record.draws}"
    return f"{record.wins}–{record.losses}"


def format_group(group: StandingsGroup, team: str | None = None) -> str:
    lines = [f"{group.title}"]
    if not group.started:
        names = ", ".join(r.team for r in group.rows) or "not known yet"
        lines.append("Not started yet – no matches played, so there is no leader.")
        lines.append(f"Participants: {names}")
        return "\n".join(lines)
    draws = any(r.matches.draws for r in group.rows)
    unit = "W–L–D" if draws else "W–L"
    for row in group.rows:
        place = f"{row.placement}." if row.placement is not None else "-"
        parts = [f"{place} {row.team}", f"matches {_record(row.matches)}"]
        if group.show_game_record:
            parts.append(f"games {_record(row.games)}")
        if row.status:
            parts.append(row.status)
        line = " – ".join(parts)
        if team and row.team.casefold() == team.casefold():
            line += "  (queried team)"
        lines.append(line)
    lines.append(f"(Records are {unit}.)")
    if group.leader:
        lines.append(f"Leader: {group.leader}")
    if group.finished:
        lines.append("This stage is finished.")
    return "\n".join(lines)


def format_standings(result: StandingsResult) -> str:
    subject = result.team or result.tournament or ""
    lines = [f"Standings – {subject} ({wiki_name(result.wiki)})"]
    if not result.groups:
        if result.team:
            lines.append(
                f"No standings table found for {result.team}. Check the exact team name "
                "as written on Liquipedia."
            )
        else:
            lines.append(
                "No standings table found for this tournament. The name must match "
                "Liquipedia exactly; try a team lookup instead."
            )
    for group in result.groups:
        lines.append("")
        lines.append(format_group(group, result.team))
    if result.next_up:
        lines.append("")
        lines.append(f"Next up for {result.team} (not started): {result.next_up.title}")
    lines.append("")
    lines.append(ATTRIBUTION)
    return "\n".join(lines)
