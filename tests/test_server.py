import pytest
from mcp import Client

from liquipedia_mcp import cli
from liquipedia_mcp.models import ATTRIBUTION
from liquipedia_mcp.server import build_server

from .conftest import TEST_KEY, run

TOOLS = {"get_results", "get_upcoming", "get_matches_between", "get_standings", "get_match_details"}


async def _call(server, name, args):
    async with Client(server) as mcp_client:
        return await mcp_client.call_tool(name, args)


def test_tools_are_listed_with_descriptions(client):
    async def go():
        async with Client(build_server(client)) as mcp_client:
            return await mcp_client.list_tools()

    tools = {t.name: t for t in run(go()).tools}
    assert set(tools) == TOOLS
    for tool in tools.values():
        assert "Liquipedia" in tool.description
        assert tool.annotations.read_only_hint


def test_tool_returns_text_and_structure(api, client):
    api.add("match", "rl_results.json")
    result = run(_call(build_server(client), "get_results", {"wiki": "rocketleague", "limit": 3}))
    assert not result.is_error
    text = result.content[0].text
    assert "Winner: Team Falcons" in text
    assert ATTRIBUTION in text
    data = result.structured_content
    assert data["source"]["text"] == ATTRIBUTION
    assert data["matches"][0]["winner_name"] == "Team Falcons"
    assert data["matches"][0]["date"] == "2026-09-14T18:30:00+00:00"


def test_standings_tool(api, client):
    api.add("standingstable", "rl_tournament_tables.json")
    api.add("standingsentry", "rl_tournament_entries.json")
    result = run(
        _call(
            build_server(client),
            "get_standings",
            {"wiki": "rocketleague", "tournament": "RLCS 2026 - World Championship"},
        )
    )
    assert not result.is_error
    assert len(result.structured_content["groups"]) == 2


def test_errors_become_tool_errors(api, client):
    api.add("match", status=401, text="")
    result = run(_call(build_server(client), "get_results", {"wiki": "rocketleague"}))
    assert result.is_error
    assert "HTTP 401" in result.content[0].text
    assert TEST_KEY not in result.content[0].text


def test_injection_becomes_tool_error(api, client):
    result = run(
        _call(
            build_server(client),
            "get_results",
            {"wiki": "rocketleague", "team": "T1]] OR [[finished::0"},
        )
    )
    assert result.is_error
    assert api.calls == []


def test_cli_refuses_without_configuration(monkeypatch, capsys):
    monkeypatch.delenv("LIQUIPEDIA_API_KEY", raising=False)
    monkeypatch.delenv("LIQUIPEDIA_USER_AGENT", raising=False)
    assert cli.main([]) == 2
    assert "LIQUIPEDIA_API_KEY" in capsys.readouterr().err


def test_cli_refuses_generic_user_agent(monkeypatch, capsys):
    monkeypatch.setenv("LIQUIPEDIA_API_KEY", "abc")
    monkeypatch.setenv("LIQUIPEDIA_USER_AGENT", "python-httpx/0.28.1")
    assert cli.main([]) == 2
    err = capsys.readouterr().err
    assert "LIQUIPEDIA_USER_AGENT" in err
    assert "abc" not in err


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "example.org", "::"])  # noqa: S104
def test_cli_refuses_public_bind(monkeypatch, capsys, host):
    monkeypatch.setenv("LIQUIPEDIA_API_KEY", "abc")
    assert cli.main(["--transport", "streamable-http", "--host", host]) == 2
    assert "Refusing to bind" in capsys.readouterr().err


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_loopback_hosts(host):
    assert cli._is_loopback(host)


def test_include_minor_types_reaches_query(api, client):
    api.add("match", "rl_tier_mixed.json")
    result = run(
        _call(
            build_server(client),
            "get_results",
            {"wiki": "rocketleague", "include_minor_types": True},
        )
    )
    assert not result.is_error
    assert "liquipediatiertype" not in api.calls[0].params["conditions"]
    assert "Showmatch" in result.content[0].text
    assert "Dropshot" not in result.content[0].text
