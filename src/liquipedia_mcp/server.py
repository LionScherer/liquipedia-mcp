"""MCP server: a thin wrapper around the core functions.

Every tool returns English text (for the model) plus the structured result
(``structuredContent``). Both carry the Liquipedia attribution.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field

from liquipedia_mcp import __version__, matches, standings
from liquipedia_mcp import format as fmt
from liquipedia_mcp.client import LiquipediaClient
from liquipedia_mcp.errors import LiquipediaError
from liquipedia_mcp.models import ATTRIBUTION

INSTRUCTIONS = f"""\
Esports data (match results, schedules, standings) from the Liquipedia LPDB API.

Rules for answering with these tools:
- Read every match line on its own. A score belongs only to the two teams on that line;
  never add scores up into an overall record that the tool did not state.
- The winner of a match is given explicitly by name ("Winner: ..."); use that, never infer
  it from the order of the teams.
- Matches that are not played yet have no score. Never report them as 0–0 or as a result.
  Opponents that are not determined yet (TBD) are left out on purpose.
- A standings table marked "Not started yet" has no leader; only name its participants.
- Requests are limited (60 per hour, shared by all tools). Prefer one well-aimed call over
  many; answers are cached for a few minutes, so repeating a call does not give newer data.
- Always mention the source: "{ATTRIBUTION}".

Wiki ids: rocketleague, leagueoflegends (verified); other Liquipedia wikis may work.
Tiers: 1=S, 2=A, 3=B, 4=C, 5=D.
"""

_READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True)

Wiki = Annotated[
    str,
    Field(description="Liquipedia wiki id, e.g. 'rocketleague' or 'leagueoflegends'."),
]
Team = Annotated[
    str | None,
    Field(description="Exact team name as on Liquipedia, e.g. 'Team Falcons', 'T1'."),
]
Tournament = Annotated[
    str | None,
    Field(description="Exact tournament name as on Liquipedia (no fuzzy matching)."),
]
MaxTier = Annotated[
    int,
    Field(
        ge=1,
        le=5,
        description=(
            "Only used without team/tournament: include tiers 1..max_tier "
            "(1=S only, 2=S+A, ...). Default 1."
        ),
    ),
]


def _result(text: str, data: dict[str, Any]) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)], structured_content=data)


async def _run(call: Callable[[], Awaitable[Any]], render: Callable[[Any], str]) -> CallToolResult:
    try:
        result = await call()
    except LiquipediaError as exc:
        # Messages are user-safe and never contain the API key.
        raise ToolError(str(exc)) from None
    return _result(render(result), result.to_dict())


def build_server(client: LiquipediaClient) -> MCPServer:
    """Create the MCP server around an existing client (one client per process)."""
    server: MCPServer = MCPServer(
        "liquipedia-mcp",
        title="Liquipedia esports data",
        instructions=INSTRUCTIONS,
        version=__version__,
        website_url="https://github.com/LionScherer/liquipedia-mcp",
    )

    @server.tool(
        title="Latest match results",
        annotations=_READ_ONLY,
        description=(
            "Finished matches, newest first, with the series score, the winner by name and "
            "the score of every single game (e.g. 3–2 OT), so you can tell close series from "
            "one-sided ones. Filter by team and/or exact tournament name; without either, only "
            "top-tier matches (max_tier) are returned. With 3 matches or fewer, League of "
            "Legends champion picks and MVPs are included. Read each line on its own and do "
            "not invent totals. Cite Liquipedia as the source."
        ),
    )
    async def get_results(
        wiki: Wiki,
        team: Team = None,
        tournament: Tournament = None,
        max_tier: MaxTier = 1,
        limit: Annotated[int, Field(ge=1, le=50, description="Number of matches.")] = 5,
    ) -> CallToolResult:
        return await _run(
            lambda: matches.get_results(
                client, wiki, team=team, tournament=tournament, max_tier=max_tier, limit=limit
            ),
            fmt.format_match_list,
        )

    @server.tool(
        title="Upcoming matches",
        annotations=_READ_ONLY,
        description=(
            "Scheduled matches from now on, soonest first (times in UTC; 'time TBA' when only "
            "the day is known). Filter by team and/or exact tournament; without either, only "
            "top-tier matches (max_tier). These matches have no result yet: never present "
            "them with a score. Pairings with undetermined (TBD) opponents are left out. Cite "
            "Liquipedia as the source."
        ),
    )
    async def get_upcoming(
        wiki: Wiki,
        team: Team = None,
        tournament: Tournament = None,
        max_tier: MaxTier = 1,
        limit: Annotated[int, Field(ge=1, le=50, description="Number of matches.")] = 10,
    ) -> CallToolResult:
        return await _run(
            lambda: matches.get_upcoming(
                client, wiki, team=team, tournament=tournament, max_tier=max_tier, limit=limit
            ),
            fmt.format_match_list,
        )

    @server.tool(
        title="Matches in a time range",
        annotations=_READ_ONLY,
        description=(
            "All matches between two UTC timestamps (max. 31 days), in chronological order, "
            "for one or more wikis in a single request – e.g. 'what's on this weekend' or "
            "'what happened yesterday'. Finished matches show score and winner; the others are "
            "marked 'not played yet' and have no score. Without a team only top-tier matches "
            "(max_tier) are returned. Cite Liquipedia as the source."
        ),
    )
    async def get_matches_between(
        wikis: Annotated[
            str,
            Field(
                description="One or more wiki ids separated by '|' or ',', "
                "e.g. 'rocketleague|leagueoflegends'."
            ),
        ],
        start_utc: Annotated[str, Field(description="ISO 8601 start, e.g. 2026-10-24T00:00Z.")],
        end_utc: Annotated[str, Field(description="ISO 8601 end, e.g. 2026-10-26T00:00Z.")],
        max_tier: MaxTier = 1,
        team: Team = None,
    ) -> CallToolResult:
        return await _run(
            lambda: matches.get_matches_between(
                client, wikis, start_utc, end_utc, max_tier=max_tier, team=team
            ),
            fmt.format_match_list,
        )

    @server.tool(
        title="Standings",
        annotations=_READ_ONLY,
        description=(
            "League, group or Swiss standings. Preferred: pass the team – this finds the phase "
            "the team is currently playing in (works when you only know 'Worlds' or 'LCK') and "
            "names its next phase if one is scheduled. Alternatively pass the exact tournament "
            "name to get all groups of its newest stage. Each row: placement, team, match "
            "record, game record (when meaningful), advanced/eliminated if decided. If a table "
            "is 'Not started yet', there is no leader. Cite Liquipedia as the source."
        ),
    )
    async def get_standings(
        wiki: Wiki,
        team: Team = None,
        tournament: Tournament = None,
    ) -> CallToolResult:
        return await _run(
            lambda: standings.get_standings(client, wiki, team=team, tournament=tournament),
            fmt.format_standings,
        )

    @server.tool(
        title="Match details",
        annotations=_READ_ONLY,
        description=(
            "Every game of a team's most recent finished match(es): game scores, overtime, "
            "game length, kills and maps where available, MVPs and League of Legends champion "
            "picks per player. Optionally only matches against a given opponent. Use this for "
            "follow-up questions like 'was it close?' or 'who played which champion?'. Cite "
            "Liquipedia as the source."
        ),
    )
    async def get_match_details(
        wiki: Wiki,
        team: Annotated[str, Field(description="Exact team name as on Liquipedia.")],
        opponent: Team = None,
        limit: Annotated[int, Field(ge=1, le=3, description="Number of matches (1-3).")] = 1,
    ) -> CallToolResult:
        return await _run(
            lambda: matches.get_match_details(client, wiki, team, opponent=opponent, limit=limit),
            fmt.format_match_list,
        )

    return server
