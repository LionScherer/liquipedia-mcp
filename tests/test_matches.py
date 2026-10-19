from datetime import UTC, datetime

import pytest

from liquipedia_mcp import matches
from liquipedia_mcp.errors import InvalidInputError
from liquipedia_mcp.matches import MATCH_FIELDS, parse_match

from .conftest import load, run

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


def test_results_query_shape(api, client):
    api.add("match", "rl_results.json")
    run(matches.get_results(client, "rocketleague", limit=3))
    (call,) = api.calls
    assert call.params["conditions"] == "[[finished::1]] AND [[liquipediatier::<2]]"
    assert call.params["order"] == "date DESC"
    assert call.params["query"] == MATCH_FIELDS
    assert call.params["limit"] == "3"


def test_results_parsing(api, client):
    api.add("match", "rl_results.json")
    result = run(matches.get_results(client, "rocketleague", team="Team Falcons", limit=3))
    final, semi, quarter = result.matches

    assert final.opponent1.name == "Team Falcons"
    assert (final.opponent1.score, final.opponent2.score) == (4, 1)
    assert final.winner_name == "Team Falcons"
    assert final.score_line == "Team Falcons 4–1 Karmine Corp"
    assert final.round == "Grand Final"
    assert final.section == "Playoffs"
    assert final.best_of == 7
    assert final.tier == 1
    assert final.date == datetime(2026, 9, 14, 18, 30, tzinfo=UTC)
    # not-played games are skipped; per-game score from Team1's view; OT flagged
    assert [(g.number, g.score1, g.score2, g.overtime) for g in final.games] == [
        (1, 1, 0, True),
        (2, 2, 1, False),
        (3, 0, 3, False),
        (4, 1, 0, True),
        (5, 3, 2, False),
    ]
    assert final.games[0].length == "6:21"
    assert final.games[0].map == "DFH Stadium"
    assert final.games[2].winner_name == "Karmine Corp"

    # "!l4!x" is a wiki shorthand: omitted, the section is the only stage info
    assert semi.round is None
    assert semi.section == "Playoffs"
    # 4:0 made of one-goal wins; the "np" game and notplayed games are skipped
    assert [(g.score1, g.score2) for g in semi.games] == [(1, 0)] * 4

    # winner "2" (a string) maps to the second opponent, by name
    assert quarter.winner_name == "Team Vitality"
    assert quarter.opponent2.players == ["Zen", "Alpha54", "Diaz"]
    assert quarter.opponent1.players[0] == "Daniel"

    # team query: no tier filter
    assert api.calls[0].params["conditions"] == "[[finished::1]] AND [[opponent::Team Falcons]]"
    assert result.max_tier is None
    assert result.source.text == "Source: Liquipedia (liquipedia.net), CC-BY-SA 3.0"


def test_tournament_filter_has_no_tier(api, client):
    api.add("match", "rl_results.json")
    run(matches.get_results(client, "rocketleague", tournament="RLCS 2026 - World Championship"))
    assert api.calls[0].params["conditions"] == (
        "[[finished::1]] AND [[tournament::RLCS 2026 - World Championship]]"
    )


def test_max_tier_filter(api, client):
    api.add("match", {"result": []})
    run(matches.get_results(client, "rocketleague", max_tier=3))
    assert api.calls[0].params["conditions"].endswith("[[liquipediatier::<4]]")


def test_winner_from_scores_not_index():
    row = load("rl_results.json")["result"][0]
    row["winner"] = "2"  # contradicts the scores 4:1
    assert parse_match(row).winner_name == "Team Falcons"


def test_forfeit_uses_winner_field():
    row = load("rl_results.json")["result"][2]
    row["match2opponents"][0].update(score=-1, status="FF")
    row["match2opponents"][1].update(score=-1, status="W")
    match = parse_match(row)
    assert match.opponent1.score is None
    assert match.opponent1.status == "FF"
    assert match.winner_name == "Team Vitality"
    assert match.score_line is None


def test_picks_only_for_three_or_fewer(api, client):
    api.add("match", "lol_match_details.json")
    result = run(matches.get_results(client, "leagueoflegends", team="T1", limit=1))
    assert result.includes_picks
    assert result.matches[0].games[0].picks1
    rows = load("lol_match_details.json")["result"] * 4
    many, _, picks = matches.parse_matches(rows, "leagueoflegends", 4)
    assert not picks
    assert all(not g.picks1 for m in many for g in m.games)


def test_upcoming(api, client):
    api.add("match", "rl_upcoming.json")
    result = run(matches.get_upcoming(client, "rocketleague", now=NOW, limit=5))
    (call,) = api.calls
    assert call.params["conditions"] == (
        "[[finished::0]] AND [[date::>2026-10-19 12:00:00]] AND [[liquipediatier::<2]]"
    )
    assert call.params["order"] == "date ASC"
    assert len(result.matches) == 2  # the TBD pairing is left out
    assert result.omitted_tbd == 1
    first, second = result.matches
    assert (first.opponent1.name, first.opponent2.name) == ("Team Falcons", "Karmine Corp")
    # -1 placeholders are never scores
    assert first.opponent1.score is None
    assert first.opponent2.score is None
    assert first.winner_name is None
    assert first.games == []
    assert second.date_exact is False
    assert second.round is None  # "!r2!h"


def test_upcoming_limit_respected(api, client):
    api.add("match", "rl_upcoming.json")
    result = run(matches.get_upcoming(client, "rocketleague", now=NOW, limit=1))
    assert len(result.matches) == 1
    assert result.omitted_tbd == 0  # the TBD row lies outside the returned window


def test_between_multiple_wikis_one_request(api, client):
    api.add("match", "rl_upcoming.json")
    result = run(
        matches.get_matches_between(
            client,
            "rocketleague|leagueoflegends",
            "2026-10-24T00:00:00Z",
            "2026-10-26T00:00:00+00:00",
            max_tier=2,
        )
    )
    (call,) = api.calls
    assert call.params["wiki"] == "rocketleague|leagueoflegends"
    assert call.params["conditions"] == (
        "[[date::>2026-10-24 00:00:00]] AND [[date::<2026-10-26 00:00:00]] "
        "AND [[liquipediatier::<3]]"
    )
    assert call.params["order"] == "date ASC"
    assert result.wikis == ["rocketleague", "leagueoflegends"]
    assert len(result.matches) == 2


def test_between_range_cached_longer(api, client, clock):
    api.add("match", "rl_upcoming.json")
    args = (client, "rocketleague", "2026-10-24", "2026-10-25")
    run(matches.get_matches_between(*args))
    clock.advance(500)
    run(matches.get_matches_between(*args))
    assert len(api.calls) == 1


@pytest.mark.parametrize(
    ("start", "end"),
    [("2026-10-25", "2026-10-24"), ("2026-01-01", "2026-03-01"), ("tomorrow", "2026-10-24")],
)
def test_between_rejects_bad_ranges(api, client, start, end):
    with pytest.raises(InvalidInputError):
        run(matches.get_matches_between(client, "rocketleague", start, end))
    assert api.calls == []


def test_lol_details(api, client):
    api.add("match", "lol_match_details.json")
    result = run(matches.get_match_details(client, "leagueoflegends", "T1"))
    (match,) = result.matches
    assert match.winner_name == "T1"
    assert match.round == "Semifinal"
    assert match.mvp == "Faker (Game 1+2), Chovy (Game 3), Oner (Game 4)"
    assert len(match.games) == 4  # game 5 not played
    g1 = match.games[0]
    assert (g1.kills1, g1.kills2, g1.length) == (18, 9, "31:22")
    assert g1.picks1[2].player == "Faker"
    assert g1.picks1[2].character == "Azir"
    # an empty player slot is skipped, the rest kept
    assert len(g1.picks2) == 5
    assert {p.player for p in g1.picks2} == {"Kiin", "Canyon", "Chovy", "Ruler", "Duro"}
    assert match.games[2].winner_name == "Gen.G"
    assert api.calls[0].params["conditions"] == "[[finished::1]] AND [[opponent::T1]]"


def test_details_opponent_filter_is_local(api, client):
    api.add("match", "lol_match_details.json")
    result = run(matches.get_match_details(client, "leagueoflegends", "T1", opponent="gen.g"))
    assert len(result.matches) == 1
    result = run(matches.get_match_details(client, "leagueoflegends", "T1", opponent="Fnatic"))
    assert result.matches == []
    assert "Fnatic" not in api.calls[0].params["conditions"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"team": "T1]] OR [[finished::0"},
        {"tournament": "~%World%"},
        {"team": "!T1"},
        {"max_tier": 9},
    ],
)
def test_injection_never_reaches_api(api, client, kwargs):
    with pytest.raises(InvalidInputError):
        run(matches.get_results(client, "rocketleague", **kwargs))
    assert api.calls == []


def test_mvp_variants():
    from liquipedia_mcp.matches import _mvp

    assert _mvp({}) is None
    assert _mvp({"mvp": {"players": {"2": {"displayname": "Faker"}, "1": {"name": "Faker"}}}}) == (
        "Faker (Game 1+2)"
    )
    assert _mvp({"mvp": {"players": [{"name": "Keria"}]}}) == "Keria"
    assert _mvp({"mvp": {"players": {"3": [{"name": "A_(Korean_Player)"}, {"name": "B"}]}}}) == (
        "A (Game 3), B (Game 3)"
    )


def test_tolerates_string_encoded_and_odd_values():
    row = load("rl_results.json")["result"][0]
    row["finished"] = "1"
    row["bestof"] = "7"
    row["match2bracketdata"] = '{"header": "Grand Final"}'
    match = parse_match(row)
    assert match.finished
    assert match.best_of == 7
    assert match.round == "Grand Final"
    row["match2opponents"] = row["match2opponents"][:1]
    assert parse_match(row) is None
