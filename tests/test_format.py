import re
from datetime import UTC, datetime

from liquipedia_mcp import format as fmt
from liquipedia_mcp import matches, standings
from liquipedia_mcp.models import ATTRIBUTION

from .conftest import load, run

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
PLACEHOLDER = re.compile(r"(?<![\d-])-1(?!\d)")  # a -1 score, not a date


def test_results_text(api, client):
    api.add("match", "rl_results.json")
    text = fmt.format_match_list(run(matches.get_results(client, "rocketleague", limit=3)))
    print(text)
    assert text.startswith("Latest results – Rocket League (S-Tier only), newest first:")
    assert "Result: Team Falcons 4–1 Karmine Corp. Winner: Team Falcons." in text
    assert "Games (Team Falcons–Karmine Corp): G1 1–0 (OT, DFH Stadium, 6:21)" in text
    assert "Playoffs, Grand Final" in text
    assert "!l4!x" not in text
    assert "Winner: Team Vitality." in text
    assert not PLACEHOLDER.search(text)
    assert text.endswith(ATTRIBUTION)


def test_upcoming_text_never_shows_scores(api, client):
    api.add("match", "rl_upcoming.json")
    text = fmt.format_match_list(run(matches.get_upcoming(client, "rocketleague", now=NOW)))
    print(text)
    assert "Team Falcons vs Karmine Corp – not played yet" in text
    assert "2026-10-25 (time TBA)" in text
    assert "0–0" not in text
    assert not PLACEHOLDER.search(text)
    assert "TBD" not in text
    assert "1 match(es) with opponents not determined yet were left out" in text
    assert ATTRIBUTION in text


def test_lol_details_text(api, client):
    api.add("match", "lol_match_details.json")
    text = fmt.format_match_list(run(matches.get_match_details(client, "leagueoflegends", "T1")))
    print(text)
    assert "MVP: Faker (Game 1+2), Chovy (Game 3), Oner (Game 4)" in text
    assert "G1 picks – T1: Zeus (K'Sante), Oner (Lee Sin), Faker (Azir)" in text
    assert "G1 1–0 (31:22, kills 18–9)" in text


def test_empty_list_text(api, client):
    api.add("match", {"result": []})
    text = fmt.format_match_list(run(matches.get_results(client, "dota2", max_tier=2)))
    assert "No matches found." in text
    assert "(S-Tier to A-Tier)" in text
    assert "dota2" in text


def test_multi_wiki_text_names_wiki(api, client):
    rows = {"result": [dict(r, wiki="rocketleague") for r in load("rl_upcoming.json")["result"]]}
    api.add("match", rows)
    result = run(
        matches.get_matches_between(
            client, "rocketleague|leagueoflegends", "2026-10-24", "2026-10-26"
        )
    )
    text = fmt.format_match_list(result)
    assert "| Rocket League | RLCS 2027 - Paris Open" in text


def test_standings_text(api, client):
    api.add("standingsentry", "lol_team_entries.json", contains="[[opponentname::T1]]")
    api.add("standingstable", "lol_team_tables.json", contains="[[pagename::")
    api.add("standingsentry", "lol_team_full_table.json", contains="[[standingsindex::0]]")
    text = fmt.format_standings(run(standings.get_standings(client, "leagueoflegends", team="T1")))
    print(text)
    assert "1. Gen.G – matches 12–1 – games 25–6 – advanced" in text
    assert "2. T1 – matches 10–3 – games 20–3 – advanced  (queried team)" in text
    assert "4. Dplus KIA – matches 4–9 – games 10–19\n" in text
    assert "Leader: Gen.G" in text
    assert "Next up for T1 (not started): 2026 World Championship – Swiss Stage" in text
    assert text.endswith(ATTRIBUTION)


def test_not_started_text(api, client):
    api.add("standingstable", "lol_worlds_not_started_tables.json")
    api.add("standingsentry", "lol_worlds_not_started_entries.json")
    text = fmt.format_standings(
        run(
            standings.get_standings(client, "leagueoflegends", tournament="2026 World Championship")
        )
    )
    print(text)
    assert "Not started yet – no matches played, so there is no leader." in text
    assert "Participants: Bilibili Gaming, FlyQuest, Fnatic" in text
    assert "Leader" not in text
    assert "1." not in text


def test_swiss_text_has_no_game_record():
    from liquipedia_mcp.standings import build_group, latest_rounds

    group = build_group("p", 0, None, latest_rounds(load("lol_swiss_bo1_entries.json")["result"]))
    text = fmt.format_group(group)
    assert "games" not in text
    assert "1. T1 – matches 2–0" in text


def test_standings_not_found_text(api, client):
    api.add("standingstable", {"result": []})
    text = fmt.format_standings(
        run(standings.get_standings(client, "rocketleague", tournament="Worlds"))
    )
    assert "No standings table found" in text
    assert ATTRIBUTION in text
