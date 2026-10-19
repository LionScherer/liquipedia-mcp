"""League, group and Swiss standings.

LPDB keeps two tables: ``standingstable`` (one row per table on a wiki page) and
``standingsentry`` (one row per team *per round*). Pitfalls handled here, all observed
in real answers:

1. Leagues and Swiss stages store one entry per round; only the highest
   ``roundindex`` per (team, page, index) is current. Answers are not sorted by round.
2. Tables exist before the first match, with all records 0–0 and placements 1..n.
   If no team has played, the group is reported as not started and has no leader.
3. Only ``definitestatus`` is used (``currentstatus`` says "down" for everyone before
   the start).
4. Bo1 Swiss stages (League of Legends) keep game records at 0–0; then only the match
   record is meaningful.

Team lookups are the default path because people say "Worlds", not the exact
tournament name, and LPDB has no usable fuzzy search. They cost three requests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from liquipedia_mcp._parse import to_bool, to_dict, to_int, to_str
from liquipedia_mcp.client import LiquipediaClient
from liquipedia_mcp.errors import InvalidInputError
from liquipedia_mcp.models import Record, StandingsGroup, StandingsResult, StandingsRow
from liquipedia_mcp.validation import validate_name, validate_wiki

ENTRY_FIELDS = (
    "opponentname,pagename,standingsindex,roundindex,scoreboard,placement,definitestatus,pageid"
)
TABLE_FIELDS = "pagename,standingsindex,tournament,title,extradata"
TEAM_ENTRY_LIMIT = 200
MAX_CANDIDATE_PAGES = 20
"""With 8, Team Falcons' World Championship group fell out behind 15 newer qualifier
pages, so look at up to 20 pages."""

STATUS_LABELS = {
    "up": "advanced",
    "byeup": "advanced (bye)",
    "seedup": "advanced (seeded)",
    "down": "eliminated",
}
"""``stay``, ``stayup`` and ``staydown`` deliberately map to nothing."""


@dataclass
class _Entry:
    pagename: str
    index: int
    pageid: int
    row: StandingsRow


def _record(scoreboard: dict[str, Any], kind: str) -> Record:
    data = to_dict(scoreboard.get(kind))
    return Record(
        wins=max(to_int(data.get("w")) or 0, 0),
        losses=max(to_int(data.get("l")) or 0, 0),
        draws=max(to_int(data.get("d")) or 0, 0),
    )


def parse_entry(raw: dict[str, Any]) -> _Entry | None:
    team = to_str(raw.get("opponentname"))
    pagename = to_str(raw.get("pagename"))
    if not team or not pagename:
        return None
    scoreboard = to_dict(raw.get("scoreboard"))
    placement = to_int(raw.get("placement"))
    status = (to_str(raw.get("definitestatus")) or "").lower()
    return _Entry(
        pagename=pagename,
        index=to_int(raw.get("standingsindex")) or 0,
        pageid=to_int(raw.get("pageid")) or 0,
        row=StandingsRow(
            team=team,
            placement=placement if placement and placement > 0 else None,
            matches=_record(scoreboard, "match"),
            games=_record(scoreboard, "game"),
            status=STATUS_LABELS.get(status),
            round_index=to_int(raw.get("roundindex")),
        ),
    )


def latest_rounds(rows: list[dict[str, Any]]) -> list[_Entry]:
    """Keep only the highest ``roundindex`` per (team, page, index); order is irrelevant."""
    best: dict[tuple[str, str, int], _Entry] = {}
    for raw in rows:
        entry = parse_entry(raw)
        if entry is None:
            continue
        key = (entry.row.team.casefold(), entry.pagename, entry.index)
        current = best.get(key)
        if current is None or (entry.row.round_index or 0) > (current.row.round_index or 0):
            best[key] = entry
    return list(best.values())


def _played(row: StandingsRow) -> bool:
    return row.matches.played > 0 or row.games.played > 0


def make_title(*parts: str | None) -> str:
    """Join tournament, stage and group title with " – ", dropping empties and repeats."""
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        text = (part or "").strip()
        if text and text.casefold() not in seen:
            seen.add(text.casefold())
            out.append(text)
    return " – ".join(out)


def _end_date(meta: dict[str, Any]) -> str | None:
    value = to_str(to_dict(meta.get("extradata")).get("enddate"))
    return value[:10] if value and value[:4].isdigit() and not value.startswith("0000") else None


def build_group(
    pagename: str, index: int, meta: dict[str, Any] | None, entries: list[_Entry]
) -> StandingsGroup:
    """Build one table from its metadata row and its (already de-duplicated) entries."""
    meta = meta or {}
    extradata = to_dict(meta.get("extradata"))
    tournament = to_str(meta.get("tournament"))
    stage = to_str(extradata.get("stagename"))
    title = to_str(meta.get("title"))
    rows = [e.row for e in entries]
    started = any(_played(r) for r in rows)
    if started:
        rows.sort(key=lambda r: (r.placement is None, r.placement or 0, r.team.casefold()))
        best = rows[0].placement
        leaders = [r for r in rows if r.placement == best] if best is not None else []
        leader = leaders[0].team if len(leaders) == 1 else None
    else:
        # Pre-start placements are just the seeding/listing order; drop them.
        for r in rows:
            r.placement = None
        rows.sort(key=lambda r: r.team.casefold())
        leader = None
    finished_raw = extradata.get("finished")
    return StandingsGroup(
        pagename=pagename,
        standings_index=index,
        title=make_title(tournament, stage, title) or pagename.replace("_", " "),
        tournament=tournament,
        stage=stage,
        group_title=title,
        end_date=_end_date(meta),
        finished=None if finished_raw in (None, "") else to_bool(finished_raw),
        started=started,
        show_game_record=started and any(r.games.played > 0 for r in rows),
        leader=leader,
        rows=rows,
    )


def _safe_pagename(pagename: str) -> str | None:
    try:
        return validate_name(pagename, "page name").replace(" ", "_")
    except InvalidInputError:
        return None


async def get_team_standings(
    client: LiquipediaClient,
    wiki: str,
    team: str,
    *,
    tournament: str | None = None,
) -> StandingsResult:
    """The table of the phase the team is currently playing in (3 requests).

    The current phase is the one the team has played in with the latest
    ``extradata.enddate`` (tie-break: page id) – *not* simply the highest page id, which
    picked a January cup over a September league. A later phase the team has not played
    in yet is returned as ``next_up``. ``tournament`` (exact name) narrows the search.
    """
    wiki = validate_wiki(wiki)
    team = validate_name(team, "team")
    tournament = validate_name(tournament, "tournament") if tournament else None
    result = StandingsResult(wiki=wiki, groups=[], team=team, tournament=tournament)

    # (a) every standings row of this team, newest pages first
    raw_entries = await client.query(
        "standingsentry",
        wiki,
        conditions=f"[[opponentname::{team}]]",
        fields=ENTRY_FIELDS,
        order="pageid DESC",
        limit=TEAM_ENTRY_LIMIT,
    )
    # (b) latest round per (page, index)
    entries = sorted(latest_rounds(raw_entries), key=lambda e: (-e.pageid, e.index))
    if not entries:
        return result

    # (c) candidate pages: newest not-yet-started phase first, then played ones
    unstarted = [e for e in entries if not _played(e.row)]
    played = [e for e in entries if _played(e.row)]
    pages: list[str] = []
    for entry in unstarted[:1] + played:
        safe = _safe_pagename(entry.pagename)
        if safe and safe not in pages:
            pages.append(safe)
        if len(pages) >= MAX_CANDIDATE_PAGES:
            break
    if not pages:
        return result

    # (d) metadata for all candidate tables in one request
    tables = await client.query(
        "standingstable",
        wiki,
        conditions=" OR ".join(f"[[pagename::{p}]]" for p in pages),
        fields=TABLE_FIELDS,
        limit=1000,
    )
    meta = {
        ((to_str(t.get("pagename")) or ""), to_int(t.get("standingsindex")) or 0): t for t in tables
    }

    def eligible(entry: _Entry) -> bool:
        m = meta.get((entry.pagename, entry.index))
        if m is None:
            return False
        if tournament:
            return (to_str(m.get("tournament")) or "").casefold() == tournament.casefold()
        return True

    # (e) current phase: latest end date among played phases, tie-break page id
    played_ok = [e for e in played if eligible(e)]
    current = max(
        played_ok,
        key=lambda e: (_end_date(meta[(e.pagename, e.index)]) or "", e.pageid),
        default=None,
    )

    # (f) a later phase that has not started for this team
    upcoming = [e for e in unstarted if eligible(e)]
    next_entry: _Entry | None = None
    for cand in upcoming:  # newest page first
        if current is None:
            next_entry = cand
            break
        cand_end = _end_date(meta[(cand.pagename, cand.index)])
        cur_end = _end_date(meta[(current.pagename, current.index)])
        later = cand_end >= cur_end if cand_end and cur_end else cand.pageid > current.pageid
        if later:
            next_entry = cand
            break

    chosen = current or next_entry
    if chosen is None:
        return result
    if current is not None and next_entry is not None:
        result.next_up = build_group(
            next_entry.pagename,
            next_entry.index,
            meta[(next_entry.pagename, next_entry.index)],
            [],
        )
        result.next_up.started = False

    # (g) the complete table of the chosen phase
    page = _safe_pagename(chosen.pagename)
    if page is None:
        return result
    full = await client.query(
        "standingsentry",
        wiki,
        conditions=f"[[pagename::{page}]] AND [[standingsindex::{chosen.index}]]",
        fields=ENTRY_FIELDS,
        limit=1000,
    )
    group_entries = [
        e for e in latest_rounds(full) if e.pagename == chosen.pagename and e.index == chosen.index
    ]
    result.groups.append(
        build_group(
            chosen.pagename, chosen.index, meta[(chosen.pagename, chosen.index)], group_entries
        )
    )
    return result


async def get_tournament_standings(
    client: LiquipediaClient, wiki: str, tournament: str
) -> StandingsResult:
    """All tables on the newest page of a tournament, by exact name (2 requests)."""
    wiki = validate_wiki(wiki)
    tournament = validate_name(tournament, "tournament")
    result = StandingsResult(wiki=wiki, groups=[], tournament=tournament)
    tables = await client.query(
        "standingstable",
        wiki,
        conditions=f"[[tournament::{tournament}]]",
        fields=TABLE_FIELDS,
        order="pageid DESC",
        limit=100,
    )
    if not tables:
        return result
    newest = to_str(tables[0].get("pagename"))
    page = _safe_pagename(newest or "")
    if not newest or not page:
        return result
    metas = {
        to_int(t.get("standingsindex")) or 0: t
        for t in tables
        if to_str(t.get("pagename")) == newest
    }
    raw = await client.query(
        "standingsentry",
        wiki,
        conditions=f"[[pagename::{page}]]",
        fields=ENTRY_FIELDS,
        limit=1000,
    )
    by_index: dict[int, list[_Entry]] = {}
    for entry in latest_rounds(raw):
        if entry.pagename == newest:
            by_index.setdefault(entry.index, []).append(entry)
    for index in sorted(set(metas) | set(by_index)):
        result.groups.append(build_group(newest, index, metas.get(index), by_index.get(index, [])))
    return result


async def get_standings(
    client: LiquipediaClient,
    wiki: str,
    *,
    team: str | None = None,
    tournament: str | None = None,
) -> StandingsResult:
    """Team lookup if ``team`` is given (optionally narrowed by ``tournament``),
    otherwise all groups of the tournament with that exact name."""
    if team:
        return await get_team_standings(client, wiki, team, tournament=tournament)
    if tournament:
        return await get_tournament_standings(client, wiki, tournament)
    raise InvalidInputError("Give a team or an exact tournament name.")
