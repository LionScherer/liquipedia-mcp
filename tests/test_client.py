import logging

import pytest

from liquipedia_mcp import __version__
from liquipedia_mcp.client import LiquipediaClient, validate_user_agent
from liquipedia_mcp.errors import (
    ApiError,
    AuthenticationError,
    ConfigurationError,
    InvalidInputError,
    LocalRateLimitError,
    ServerRateLimitError,
)
from liquipedia_mcp.ratelimit import RequestBudget

from .conftest import TEST_KEY, TEST_UA, run

OK = {"result": [{"tournament": "X"}]}


def query(client, **kwargs):
    kwargs.setdefault("conditions", "[[finished::1]]")
    return run(client.query("match", "rocketleague", **kwargs))


# ------------------------------------------------------------------ request shape


def test_request_headers_and_params(api, client):
    api.add("match", OK)
    rows = query(client, fields="tournament", order="date DESC", limit=5000)
    assert rows == OK["result"]
    (call,) = api.calls
    assert call.url == "https://api.liquipedia.net/api/v3/match"
    assert call.headers["Authorization"] == f"Apikey {TEST_KEY}"
    assert call.headers["User-Agent"] == f"{TEST_UA} liquipedia-mcp/{__version__}"
    assert call.headers["Accept-Encoding"] == "gzip"
    assert call.params == {
        "wiki": "rocketleague",
        "conditions": "[[finished::1]]",
        "query": "tournament",
        "order": "date DESC",
        "limit": "1000",  # clamped
    }
    # the key never travels in the URL / params
    assert TEST_KEY not in str(call.params)


def test_multiple_wikis_in_one_request(api, client):
    api.add("match", OK)
    run(client.query("match", ["rocketleague", "leagueoflegends"]))
    assert api.calls[0].params["wiki"] == "rocketleague|leagueoflegends"


def test_unknown_endpoint_and_bad_wiki_rejected_without_request(api, client):
    with pytest.raises(InvalidInputError):
        run(client.query("player", "rocketleague"))
    with pytest.raises(InvalidInputError):
        run(client.query("match", "rocketleague|x]]"))
    assert api.calls == []


# ------------------------------------------------------------------ secrets


def test_key_never_in_repr_or_errors(api, client, caplog):
    caplog.set_level(logging.DEBUG)
    assert TEST_KEY not in repr(client)
    assert TEST_KEY not in str(vars(client))
    api.add("match", status=401, text="nope")
    with pytest.raises(AuthenticationError) as info:
        query(client)
    assert TEST_KEY not in str(info.value)
    assert TEST_KEY not in repr(info.value)
    assert TEST_KEY not in caplog.text


def test_network_error_message_is_safe(clock):
    async def broken(url, params, headers):
        raise OSError(f"connection failed with headers {headers}")

    client = LiquipediaClient(TEST_KEY, TEST_UA, fetch=broken, clock=clock)
    with pytest.raises(ApiError) as info:
        query(client)
    assert TEST_KEY not in str(info.value)
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__


# ------------------------------------------------------------------ configuration


@pytest.mark.parametrize(
    "ua",
    [
        "",
        "   ",
        "python-requests/2.32",
        "Mozilla/5.0 (X11; Linux x86_64)",
        "curl/8.0 (me@example.org)",
        "httpx",
        "<your-project>/<version> (<contact>)",
        "my-cool-bot/1.0",  # no contact
        "liquipedia-mcp/0.1.0 (a@b.cd)",  # the library itself is not a project name
    ],
)
def test_user_agent_must_be_specific(ua):
    with pytest.raises(ConfigurationError):
        validate_user_agent(ua)


@pytest.mark.parametrize(
    "ua",
    [
        "esports-helper/1.2 (https://github.com/someone/esports-helper)",
        "MyDiscordBot/0.3 (contact: someone@example.org)",
    ],
)
def test_good_user_agents(ua):
    assert validate_user_agent(ua) == ua


def test_from_env():
    env = {"LIQUIPEDIA_API_KEY": "abc123", "LIQUIPEDIA_USER_AGENT": TEST_UA}
    client = LiquipediaClient.from_env(env)
    assert client.budget.max_per_hour == 60
    assert client.budget.lockout_seconds == 600
    env["LIQUIPEDIA_MAX_REQUESTS_PER_HOUR"] = "30"
    env["LIQUIPEDIA_LOCKOUT_SECONDS"] = "1800"
    client = LiquipediaClient.from_env(env)
    assert client.budget.max_per_hour == 30
    assert client.budget.lockout_seconds == 1800


@pytest.mark.parametrize(
    "env",
    [
        {"LIQUIPEDIA_USER_AGENT": TEST_UA},
        {"LIQUIPEDIA_API_KEY": "", "LIQUIPEDIA_USER_AGENT": TEST_UA},
        {"LIQUIPEDIA_API_KEY": "abc 123", "LIQUIPEDIA_USER_AGENT": TEST_UA},
        {"LIQUIPEDIA_API_KEY": "abc"},
        {"LIQUIPEDIA_API_KEY": "abc", "LIQUIPEDIA_USER_AGENT": "python-httpx/0.28"},
        {
            "LIQUIPEDIA_API_KEY": "abc",
            "LIQUIPEDIA_USER_AGENT": TEST_UA,
            "LIQUIPEDIA_MAX_REQUESTS_PER_HOUR": "61",
        },
        {
            "LIQUIPEDIA_API_KEY": "abc",
            "LIQUIPEDIA_USER_AGENT": TEST_UA,
            "LIQUIPEDIA_MAX_REQUESTS_PER_HOUR": "many",
        },
        {
            "LIQUIPEDIA_API_KEY": "abc",
            "LIQUIPEDIA_USER_AGENT": TEST_UA,
            "LIQUIPEDIA_LOCKOUT_SECONDS": "5",
        },
    ],
)
def test_from_env_refuses_bad_config(env):
    with pytest.raises(ConfigurationError):
        LiquipediaClient.from_env(env)


def test_budget_can_only_be_lowered():
    assert RequestBudget(10).max_per_hour == 10
    for bad in (0, 61, 1000, True):
        with pytest.raises(ConfigurationError):
            RequestBudget(bad)


# ------------------------------------------------------------------ rate limit


def test_sixty_requests_per_hour_then_error_instead_of_request(api, client, clock):
    api.add("match", OK)
    for i in range(60):
        query(client, conditions=f"[[date::>2026-01-{i:02d}]]")
        clock.advance(1)
    assert len(api.calls) == 60
    with pytest.raises(LocalRateLimitError) as info:
        query(client, conditions="[[date::>2026-02-01]]")
    assert len(api.calls) == 60  # nothing was sent
    assert 3400 < info.value.retry_after <= 3600
    assert client.budget.remaining == 0
    # cached answers keep working while the budget is exhausted
    assert query(client, conditions="[[date::>2026-01-59]]") == OK["result"]
    # the window slides: after an hour the oldest request has expired
    clock.advance(3600 - 59)
    query(client, conditions="[[date::>2026-02-01]]")
    assert len(api.calls) == 61


def test_lowered_budget(api, clock):
    api.add("match", OK)
    client = LiquipediaClient(TEST_KEY, TEST_UA, fetch=api, clock=clock, max_requests_per_hour=2)
    query(client, conditions="[[a::1]]")
    query(client, conditions="[[a::2]]")
    with pytest.raises(LocalRateLimitError):
        query(client, conditions="[[a::3]]")
    assert len(api.calls) == 2


# ------------------------------------------------------------------ cache


def test_cache_hit_and_expiry(api, client, clock):
    api.add("match", OK)
    first = query(client)
    first[0]["tournament"] = "mutated by caller"
    assert query(client) == OK["result"]  # served from cache, unaffected by mutation
    assert len(api.calls) == 1
    clock.advance(299)
    query(client)
    assert len(api.calls) == 1
    clock.advance(2)  # default TTL 300 s
    query(client)
    assert len(api.calls) == 2


def test_custom_ttl(api, client, clock):
    api.add("match", OK)
    query(client, ttl=600)
    clock.advance(500)
    query(client, ttl=600)
    assert len(api.calls) == 1


def test_cache_is_size_bounded(api, clock):
    api.add("match", OK)
    client = LiquipediaClient(TEST_KEY, TEST_UA, fetch=api, clock=clock, cache_size=3)
    for i in range(5):
        query(client, conditions=f"[[a::{i}]]")
    assert len(client.cache) == 3


def test_errors_are_cached_briefly(api, client, clock):
    api.add("match", status=500, text="boom")
    for _ in range(3):
        with pytest.raises(ApiError):
            query(client)
    assert len(api.calls) == 1  # negative cache: no hammering
    clock.advance(61)
    with pytest.raises(ApiError):
        query(client)
    assert len(api.calls) == 2


# ------------------------------------------------------------------ HTTP errors


def test_401(api, client):
    api.add("match", status=401, text='{"error":"Invalid API key"}')
    with pytest.raises(AuthenticationError) as info:
        query(client)
    assert info.value.status == 401
    assert "LIQUIPEDIA_API_KEY" in str(info.value)
    assert len(api.calls) == 1  # no retry


def test_403(api, client):
    api.add("match", status=403, text="Forbidden")
    with pytest.raises(AuthenticationError) as info:
        query(client)
    assert info.value.status == 403
    assert len(api.calls) == 1


def test_429_locks_out_without_retry(api, client, clock):
    api.add("match", status=429, text="Too Many Requests")
    with pytest.raises(ServerRateLimitError) as info:
        query(client)
    assert info.value.retry_after == 600
    assert len(api.calls) == 1  # no automatic retry
    # different query: still refused locally during the lockout
    with pytest.raises(ServerRateLimitError):
        query(client, conditions="[[something::else]]")
    assert len(api.calls) == 1
    clock.advance(599)
    with pytest.raises(ServerRateLimitError):
        query(client, conditions="[[third::query]]")
    assert len(api.calls) == 1
    clock.advance(2)
    api.routes.clear()
    api.add("match", OK)
    assert query(client, conditions="[[third::query]]") == OK["result"]
    assert len(api.calls) == 2


def test_429_honours_longer_retry_after(api, client, clock):
    api.add("match", status=429, text="", headers={"Retry-After": "1800"})
    with pytest.raises(ServerRateLimitError) as info:
        query(client)
    assert info.value.retry_after == 1800
    clock.advance(1000)
    with pytest.raises(ServerRateLimitError):
        query(client, conditions="[[x::y]]")
    assert len(api.calls) == 1


def test_configurable_lockout(api, clock):
    api.add("match", status=429, text="")
    client = LiquipediaClient(TEST_KEY, TEST_UA, fetch=api, clock=clock, lockout_seconds=120)
    with pytest.raises(ServerRateLimitError) as info:
        query(client)
    assert info.value.retry_after == 120


def test_envelope_error_and_warning(api, client, caplog):
    api.add("match", {"result": [], "error": ["Invalid condition"]}, contains="bad")
    api.add("match", {"result": [{"a": 1}], "warning": ["limit capped"]}, contains="good")
    with pytest.raises(ApiError, match="Invalid condition"):
        query(client, conditions="[[bad::1]]")
    with caplog.at_level(logging.WARNING):
        assert query(client, conditions="[[good::1]]") == [{"a": 1}]
    assert "limit capped" in caplog.text


@pytest.mark.parametrize("text", ["not json", "[1,2]", '{"result": "x"}'])
def test_malformed_responses(api, client, text):
    api.add("match", text=text)
    with pytest.raises(ApiError):
        query(client)


def test_missing_result_is_empty(api, client):
    api.add("match", {})
    assert query(client) == []
