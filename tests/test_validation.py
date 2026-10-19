from datetime import UTC, datetime

import pytest

from liquipedia_mcp.errors import InvalidInputError
from liquipedia_mcp.validation import (
    clamp,
    lpdb_datetime,
    parse_utc,
    same_team,
    shorter_team_name,
    validate_name,
    validate_tier,
    validate_wiki,
    validate_wikis,
)


@pytest.mark.parametrize(
    "name",
    [
        "Team Liquid",
        "T1",
        "Gen.G",
        "Karmine Corp",
        "100 Thieves",
        "Ninjas in Pyjamas",
        "RLCS 2026 - World Championship",
        "Movistar KOI",
        "Team BDS",
        "Oxygen Esports",
        "LCK 2026 Rounds 3-5",
        "Rogue (2026)",
        "MAD Lions KOI",
        "Fnatic",
        "ORDER",
    ],
)
def test_valid_names(name):
    assert validate_name(name) == name


@pytest.mark.parametrize(
    "name",
    [
        "Team Liquid]] OR [[opponent::G2 Esports",  # close the condition and add one
        "T1]]",
        "[[finished::0]]",
        "Team|Other",
        "a::b",
        "!Team Liquid",  # turns ::value into ::!value (negation)
        ">2020",  # comparison operator
        "<5",
        "~%World%",  # LIKE match
        "Team Liquid OR Fnatic",
        "Team Liquid AND x",
        "x and y",
        "or",
        "{{template}}",
        "Team\nLiquid]]",
        "Team\x00Liquid",
        "",
        "   ",
        "x" * 101,
    ],
)
def test_injection_attempts_are_rejected(name):
    with pytest.raises(InvalidInputError):
        validate_name(name)


def test_name_whitespace_is_normalised():
    assert validate_name("  Team   Liquid ") == "Team Liquid"
    with pytest.raises(InvalidInputError):
        validate_name(123)  # type: ignore[arg-type]


@pytest.mark.parametrize("wiki", ["rocketleague", "leagueoflegends", "counterstrike", "dota2"])
def test_valid_wikis(wiki):
    assert validate_wiki(wiki) == wiki


@pytest.mark.parametrize(
    "wiki", ["RocketLeague", "rocket league", "rocketleague|x]]", "../etc", "", "lol;drop", "ü"]
)
def test_invalid_wikis(wiki):
    with pytest.raises(InvalidInputError):
        validate_wiki(wiki)


def test_wikis_list_forms():
    assert validate_wikis("rocketleague|leagueoflegends") == ["rocketleague", "leagueoflegends"]
    assert validate_wikis("rocketleague, leagueoflegends,rocketleague") == [
        "rocketleague",
        "leagueoflegends",
    ]
    assert validate_wikis(["dota2"]) == ["dota2"]
    with pytest.raises(InvalidInputError):
        validate_wikis("")
    with pytest.raises(InvalidInputError):
        validate_wikis([f"wiki{i}" for i in range(11)])
    with pytest.raises(InvalidInputError):
        validate_wikis("rocketleague|Bad Wiki")


def test_tier_and_clamp():
    assert validate_tier(1) == 1
    assert validate_tier(5) == 5
    for bad in (0, 6, -1, True, "1"):
        with pytest.raises(InvalidInputError):
            validate_tier(bad)  # type: ignore[arg-type]
    assert clamp(5000, 1, 1000) == 1000
    assert clamp(-3, 1, 1000) == 1
    with pytest.raises(InvalidInputError):
        clamp("x", 1, 2)  # type: ignore[arg-type]


def test_parse_utc():
    assert parse_utc("2026-10-19T18:00:00Z") == datetime(2026, 10, 19, 18, tzinfo=UTC)
    assert parse_utc("2026-10-19T20:00:00+02:00") == datetime(2026, 10, 19, 18, tzinfo=UTC)
    assert parse_utc("2026-10-19") == datetime(2026, 10, 19, tzinfo=UTC)
    assert lpdb_datetime(parse_utc("2026-10-19T20:00:00+02:00")) == "2026-10-19 18:00:00"
    for bad in ("yesterday", "2026-13-01", "]] OR [[", 12):
        with pytest.raises(InvalidInputError):
            parse_utc(bad)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        ("FURIA Esports", "FURIA", True),
        ("furia", "FURIA Esports", True),
        ("Team Liquid", "Liquid", True),
        ("Gen.G", "Gen.G Esports", True),
        ("Karmine Corp", "Karmine", True),
        ("T1", "T1 Academy", False),
        ("G2 Esports", "Gen.G", False),
        ("Cloud9", "FURIA", False),
    ],
)
def test_same_team(a, b, same):
    assert same_team(a, b) is same


def test_shorter_team_name():
    assert shorter_team_name("FURIA Esports") == "FURIA"
    assert shorter_team_name("Team Liquid") == "Liquid"
    assert shorter_team_name("Fnatic") is None
    assert shorter_team_name("Team") is None
