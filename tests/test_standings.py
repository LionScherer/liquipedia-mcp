from liquipedia_mcp import standings
from liquipedia_mcp.standings import build_group, latest_rounds, make_title

from .conftest import load, run

LCK = "LCK/2026/Rounds_3-5"
KESPA = "KeSPA_Cup/2026"
WORLDS = "World_Championship/2026/Swiss_Stage"


def team_api(api):
    api.add("standingsentry", "lol_team_entries.json", contains="[[opponentname::T1]]")
    api.add("standingstable", "lol_team_tables.json", contains="[[pagename::")
    api.add(
        "standingsentry",
        "lol_team_full_table.json",
        contains=(f"[[pagename::{LCK}]]", "[[standingsindex::0]]"),
    )
    return api


def test_team_lookup_picks_latest_end_date_not_highest_pageid(api, client):
    team_api(api)
    result = run(standings.get_standings(client, "leagueoflegends", team="T1"))
    # not the KeSPA Cup (higher pageid, January) but the LCK (September)
    (group,) = result.groups
    assert group.pagename == LCK
    assert group.title == "LCK 2026 – Rounds 3-5 – Legend Group"


def test_team_lookup_full_flow(api, client):
    team_api(api)
    result = run(standings.get_standings(client, "leagueoflegends", team="T1"))
    assert len(api.calls) == 3

    first, second, third = api.calls
    assert first.params["conditions"] == "[[opponentname::T1]]"
    assert first.params["order"] == "pageid DESC"
    assert first.params["limit"] == "200"
    # the not-yet-started phase comes first among the candidates, then played pages
    assert second.params["conditions"] == (
        f"[[pagename::{WORLDS}]] OR [[pagename::{KESPA}]] OR [[pagename::{LCK}]] "
        "OR [[pagename::LCK/2026/Road_to_MSI]]"
    )
    assert third.params["conditions"] == f"[[pagename::{LCK}]] AND [[standingsindex::0]]"
    assert third.params["limit"] == "1000"

    (group,) = result.groups
    assert group.started
    # only the highest round per team counts, although rounds arrive unsorted
    rows = {r.team: r for r in group.rows}
    assert (rows["T1"].matches.wins, rows["T1"].matches.losses) == (10, 3)
    assert rows["T1"].round_index == 13
    assert [r.team for r in group.rows] == [
        "Gen.G",
        "T1",
        "Hanwha Life Esports",
        "Dplus KIA",
        "KT Rolster",
    ]
    assert [r.placement for r in group.rows] == [1, 2, 3, 4, 5]
    assert group.leader == "Gen.G"
    assert rows["Gen.G"].status == "advanced"
    assert rows["Dplus KIA"].status is None  # "stay" says nothing
    assert rows["KT Rolster"].status == "eliminated"
    assert group.show_game_record

    # the later phase that has not started is named as next up
    assert result.next_up is not None
    assert result.next_up.pagename == WORLDS
    assert result.next_up.title == "2026 World Championship – Swiss Stage"
    assert not result.next_up.started


def test_team_lookup_falls_back_to_pageid_without_end_dates(api, client):
    tables = load("lol_team_tables.json")
    for t in tables["result"]:
        t["extradata"].pop("enddate")
    api.add("standingsentry", "lol_team_entries.json", contains="[[opponentname::T1]]")
    api.add("standingstable", tables, contains="[[pagename::")
    api.add("standingsentry", {"result": []}, contains=f"[[pagename::{KESPA}]]")
    result = run(standings.get_standings(client, "leagueoflegends", team="T1"))
    assert result.groups[0].pagename == KESPA
    assert result.next_up.pagename == WORLDS


def test_team_lookup_only_unstarted_phase(api, client):
    entries = [e for e in load("lol_team_entries.json")["result"] if e["pagename"] == WORLDS]
    api.add("standingsentry", {"result": entries}, contains="[[opponentname::T1]]")
    api.add("standingstable", "lol_team_tables.json", contains="[[pagename::")
    api.add(
        "standingsentry", "lol_worlds_not_started_entries.json", contains=f"[[pagename::{WORLDS}]]"
    )
    result = run(standings.get_standings(client, "leagueoflegends", team="T1"))
    (group,) = result.groups
    assert not group.started
    assert group.leader is None
    assert all(r.placement is None for r in group.rows)
    assert result.next_up is None


def test_team_lookup_with_tournament_filter(api, client):
    team_api(api)
    api.add("standingsentry", {"result": []}, contains=f"[[pagename::{KESPA}]]")
    result = run(
        standings.get_standings(client, "leagueoflegends", team="T1", tournament="KeSPA Cup 2026")
    )
    assert result.groups[0].pagename == KESPA
    assert result.next_up is None  # Worlds is filtered out


def test_team_without_entries(api, client):
    api.add("standingsentry", {"result": []})
    result = run(standings.get_standings(client, "leagueoflegends", team="Nobody"))
    assert result.groups == []
    assert len(api.calls) == 1


def test_candidate_pages_capped_at_twenty(api, client):
    rows = [
        {
            "opponentname": "Team Falcons",
            "pagename": f"Qualifier/{i}",
            "standingsindex": 0,
            "roundindex": 1,
            "scoreboard": {"match": {"w": 1, "l": 0, "d": 0}},
            "pageid": 1000 - i,
        }
        for i in range(30)
    ]
    api.add("standingsentry", {"result": rows}, contains="opponentname")
    api.add("standingstable", {"result": []})
    run(standings.get_standings(client, "rocketleague", team="Team Falcons"))
    assert api.calls[1].params["conditions"].count("[[pagename::") == 20


def test_not_started_tournament(api, client):
    api.add("standingstable", "lol_worlds_not_started_tables.json")
    api.add("standingsentry", "lol_worlds_not_started_entries.json")
    result = run(
        standings.get_standings(client, "leagueoflegends", tournament="2026 World Championship")
    )
    assert api.calls[0].params["conditions"] == "[[tournament::2026 World Championship]]"
    assert api.calls[0].params["order"] == "pageid DESC"
    assert api.calls[1].params["conditions"] == f"[[pagename::{WORLDS}]]"
    (group,) = result.groups
    assert not group.started
    assert group.leader is None
    assert not group.show_game_record
    assert [r.placement for r in group.rows] == [None] * 8
    # currentstatus "down" before the start is ignored
    assert all(r.status is None for r in group.rows)


def test_tournament_all_groups_and_statuses(api, client):
    api.add("standingstable", "rl_tournament_tables.json")
    api.add("standingsentry", "rl_tournament_entries.json")
    result = run(
        standings.get_standings(client, "rocketleague", tournament="RLCS 2026 - World Championship")
    )
    a, b = result.groups
    assert a.title == "RLCS 2026 - World Championship – Group Stage – Group A"
    assert b.title.endswith("Group B")
    assert a.leader == "Team Falcons"
    statuses = {r.team: r.status for g in result.groups for r in g.rows}
    assert statuses == {
        "Team Falcons": "advanced (bye)",
        "Karmine Corp": "advanced",
        "NRG": "advanced",
        "Twisted Minds": "eliminated",
        "Team Vitality": "advanced (seeded)",
        "Gentle Mates": None,
        "Ninjas in Pyjamas": None,
        "FURIA Esports": "eliminated",
    }
    falcons = a.rows[0]
    assert (falcons.matches.wins, falcons.games.wins, falcons.games.losses) == (3, 9, 2)


def test_tournament_not_found(api, client):
    api.add("standingstable", {"result": []})
    result = run(standings.get_standings(client, "rocketleague", tournament="Worlds"))
    assert result.groups == []
    assert len(api.calls) == 1


def test_swiss_bo1_hides_game_record():
    entries = latest_rounds(load("lol_swiss_bo1_entries.json")["result"])
    group = build_group(WORLDS, 0, None, entries)
    assert group.started
    assert not group.show_game_record
    rows = {r.team: r for r in group.rows}
    assert (rows["T1"].matches.wins, rows["T1"].round_index) == (2, 2)
    assert rows["Gen.G"].placement == 3
    assert group.leader == "T1"
    assert group.title == "World Championship/2026/Swiss Stage"


def test_tied_leader_is_not_named():
    entries = latest_rounds(load("lol_swiss_bo1_entries.json")["result"])
    for e in entries:
        if e.row.team == "Gen.G":
            e.row.placement = 1
    assert build_group(WORLDS, 0, None, entries).leader is None


def test_make_title_dedupes():
    assert make_title("Worlds", "Swiss Stage", "swiss stage") == "Worlds – Swiss Stage"
    assert make_title(None, "", "Group A") == "Group A"


def test_missing_input(client):
    import pytest

    from liquipedia_mcp.errors import InvalidInputError

    with pytest.raises(InvalidInputError):
        run(standings.get_standings(client, "rocketleague"))
