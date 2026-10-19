"""Low-level LPDB v3 client: authentication, User-Agent, budget, cache, errors.

All network access of this package goes through :meth:`LiquipediaClient.query`. The
HTTP function is injectable (``fetch=``) so tests and embedding applications never need
a real connection.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from liquipedia_mcp.cache import TTLCache
from liquipedia_mcp.errors import (
    ApiError,
    AuthenticationError,
    ConfigurationError,
    InvalidInputError,
    ServerRateLimitError,
)
from liquipedia_mcp.ratelimit import (
    DEFAULT_LOCKOUT_SECONDS,
    MAX_REQUESTS_PER_HOUR,
    RequestBudget,
)
from liquipedia_mcp.validation import clamp, validate_wikis

log = logging.getLogger(__name__)

BASE_URL = "https://api.liquipedia.net/api/v3"
ENDPOINTS = frozenset({"match", "standingstable", "standingsentry"})
MAX_LIMIT = 1000

DEFAULT_TTL = 300.0
"""Default cache lifetime for successful answers (seconds)."""
RANGE_TTL = 600.0
"""Cache lifetime for date-range queries, which change slowly."""
ERROR_TTL = 60.0
"""Negative cache: identical failing requests are not repeated within this time."""

ENV_API_KEY = "LIQUIPEDIA_API_KEY"
ENV_USER_AGENT = "LIQUIPEDIA_USER_AGENT"
ENV_MAX_PER_HOUR = "LIQUIPEDIA_MAX_REQUESTS_PER_HOUR"
ENV_LOCKOUT = "LIQUIPEDIA_LOCKOUT_SECONDS"


@dataclass(frozen=True)
class RawResponse:
    """What an injected ``fetch`` function returns."""

    status: int
    text: str
    headers: Mapping[str, str] = field(default_factory=dict)


Fetch = Callable[[str, Mapping[str, str], Mapping[str, str]], Awaitable[RawResponse]]
"""``async fetch(url, params, headers) -> RawResponse``"""


_GENERIC_UA = re.compile(
    r"^(python|python-requests|python-httpx|httpx|aiohttp|requests|urllib|curl|wget|"
    r"mozilla|java|go-http-client|node-fetch|axios|okhttp|test|user-?agent|unknown|bot|"
    r"liquipedia-mcp|my-?app|example)(?=[/\s;(]|$)",
    re.IGNORECASE,
)
_CONTACT = re.compile(r"(@[\w-]+\.\w|https?://|\bwww\.|github\.com/)", re.IGNORECASE)


def library_user_agent() -> str:
    from liquipedia_mcp import __version__

    return f"liquipedia-mcp/{__version__}"


def validate_user_agent(user_agent: str | None) -> str:
    """Require a project-specific User-Agent with contact information.

    Liquipedia asks API users to identify themselves so they can reach out instead of
    blocking. Generic library defaults and the README placeholder are refused.
    """
    ua = " ".join((user_agent or "").split())
    if not ua:
        raise ConfigurationError(
            f"{ENV_USER_AGENT} is not set. Use something like "
            '"my-project/1.0 (https://github.com/me/my-project; me@example.org)".'
        )
    if any(ch in ua for ch in "<>") or "your-project" in ua.lower():
        raise ConfigurationError(
            f"{ENV_USER_AGENT} still contains the placeholder from the README; "
            "put in your own project name, version and contact."
        )
    if len(ua) < 12 or _GENERIC_UA.match(ua):
        raise ConfigurationError(
            f"{ENV_USER_AGENT} is too generic ({ua!r}). Name your project and version."
        )
    if not _CONTACT.search(ua):
        raise ConfigurationError(
            f"{ENV_USER_AGENT} must include a way to contact you (an e-mail address or a "
            "URL such as your repository), so Liquipedia can reach you."
        )
    return ua


def validate_api_key(api_key: str | None) -> str:
    key = (api_key or "").strip()
    if not key:
        raise ConfigurationError(
            f"{ENV_API_KEY} is not set. Request your own key at https://liquipedia.net/api."
        )
    if any(ch.isspace() or ord(ch) < 32 for ch in key):
        raise ConfigurationError(f"{ENV_API_KEY} contains whitespace or control characters.")
    return key


class _Secret:
    """Holds the API key; never reveals it through ``str``/``repr``."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "<redacted>"

    __str__ = __repr__


class LiquipediaClient:
    """Rate-limited, caching client for the LPDB v3 API.

    One instance per process is intended: the request budget lives on the instance.
    Use :meth:`from_env` for the standard environment-based configuration.
    """

    def __init__(
        self,
        api_key: str,
        user_agent: str,
        *,
        fetch: Fetch | None = None,
        max_requests_per_hour: int = MAX_REQUESTS_PER_HOUR,
        lockout_seconds: float = DEFAULT_LOCKOUT_SECONDS,
        cache_size: int = 256,
        default_ttl: float = DEFAULT_TTL,
        error_ttl: float = ERROR_TTL,
        timeout: float = 20.0,
        clock: Callable[[], float] = time.monotonic,
        base_url: str = BASE_URL,
    ) -> None:
        self._key = _Secret(validate_api_key(api_key))
        self.user_agent = f"{validate_user_agent(user_agent)} {library_user_agent()}"
        self.budget = RequestBudget(max_requests_per_hour, lockout_seconds, clock)
        self.cache = TTLCache(cache_size, clock)
        self.default_ttl = default_ttl
        self.error_ttl = error_ttl
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")
        self._fetch = fetch
        self._http: Any = None  # lazily created httpx.AsyncClient
        self._lock: asyncio.Lock | None = None
        self.requests_sent = 0

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, **kwargs: Any) -> LiquipediaClient:
        """Build a client from ``LIQUIPEDIA_*`` environment variables.

        Raises :class:`ConfigurationError` if the key or User-Agent is missing/unusable.
        """
        env = os.environ if env is None else env
        if ENV_MAX_PER_HOUR in env and "max_requests_per_hour" not in kwargs:
            try:
                kwargs["max_requests_per_hour"] = int(env[ENV_MAX_PER_HOUR])
            except ValueError:
                raise ConfigurationError(f"{ENV_MAX_PER_HOUR} must be an integer.") from None
        if ENV_LOCKOUT in env and "lockout_seconds" not in kwargs:
            try:
                kwargs["lockout_seconds"] = float(env[ENV_LOCKOUT])
            except ValueError:
                raise ConfigurationError(f"{ENV_LOCKOUT} must be a number.") from None
        return cls(env.get(ENV_API_KEY, ""), env.get(ENV_USER_AGENT, ""), **kwargs)

    def __repr__(self) -> str:
        return (
            f"LiquipediaClient(user_agent={self.user_agent!r}, "
            f"budget={self.budget.max_per_hour}/h, api_key=<redacted>)"
        )

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def __aenter__(self) -> LiquipediaClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ requests

    async def query(
        self,
        endpoint: str,
        wiki: str | list[str],
        *,
        conditions: str | None = None,
        fields: str | None = None,
        order: str | None = None,
        limit: int = 20,
        offset: int = 0,
        groupby: str | None = None,
        ttl: float | None = None,
    ) -> list[dict[str, Any]]:
        """Run one LPDB query and return the ``result`` rows.

        Answers are served from the cache when possible. A cache miss costs one request
        from the hourly budget; when the budget is exhausted a
        :class:`~liquipedia_mcp.errors.LocalRateLimitError` is raised and nothing is sent.
        """
        if endpoint not in ENDPOINTS:
            raise InvalidInputError(f"Unsupported endpoint {endpoint!r}.")
        params: dict[str, str] = {
            "wiki": "|".join(validate_wikis(wiki)),
            "limit": str(clamp(limit, 1, MAX_LIMIT)),
        }
        if offset:
            params["offset"] = str(clamp(offset, 0, 100_000))
        for name, value in (
            ("conditions", conditions),
            ("query", fields),
            ("order", order),
            ("groupby", groupby),
        ):
            if value:
                params[name] = value
        key = (endpoint, tuple(sorted(params.items())))

        hit, value = self.cache.get(key)
        if hit:
            return _replay(value)

        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            # Another task may have fetched the same thing while we waited.
            hit, value = self.cache.get(key)
            if hit:
                return _replay(value)
            # Over budget or locked out after a 429: raise without sending. Not cached,
            # because nothing was asked of the server.
            self.budget.acquire()
            try:
                rows = await self._send(endpoint, params)
            except ApiError as exc:  # negative cache: don't hammer on errors
                self.cache.set(key, exc, self.error_ttl)
                raise
            self.cache.set(key, rows, self.default_ttl if ttl is None else ttl)
            return _replay(rows)

    async def _send(self, endpoint: str, params: dict[str, str]) -> list[dict[str, Any]]:
        self.requests_sent += 1
        url = f"{self.base_url}/{endpoint}"
        headers = {
            "Authorization": f"Apikey {self._key.reveal()}",
            "User-Agent": self.user_agent,
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
        }
        log.debug("LPDB request %s %s", endpoint, params)
        try:
            response = await (self._fetch or self._default_fetch)(url, params, headers)
        except ApiError:
            raise
        except Exception as exc:  # network errors: report, never retry automatically
            raise ApiError(f"Could not reach the Liquipedia API ({type(exc).__name__}).") from None
        return self._parse(response)

    def _parse(self, response: RawResponse) -> list[dict[str, Any]]:
        status = response.status
        if status == 429:
            retry_after = _retry_after(response.headers)
            seconds = self.budget.lock_out(retry_after)
            raise ServerRateLimitError(
                "Liquipedia answered HTTP 429 (too many requests). No retry is made; "
                f"all requests are paused for {seconds:.0f} s.",
                retry_after=seconds,
            )
        if status == 401:
            raise AuthenticationError(
                "Liquipedia rejected the API key (HTTP 401). Check LIQUIPEDIA_API_KEY.",
                status=401,
            )
        if status == 403:
            raise AuthenticationError(
                "Liquipedia refused access (HTTP 403). The key may not cover this wiki or "
                "endpoint, or the request was blocked.",
                status=403,
            )
        if status >= 400:
            raise ApiError(f"Liquipedia API error (HTTP {status}).", status=status)
        try:
            payload = json.loads(response.text)
        except ValueError:
            raise ApiError("Liquipedia API returned invalid JSON.", status=status) from None
        if not isinstance(payload, dict):
            raise ApiError("Unexpected response format from the Liquipedia API.", status=status)
        error = payload.get("error")
        if error:
            raise ApiError(f"Liquipedia API error: {_join(error)}", status=status)
        warning = payload.get("warning")
        if warning:
            log.warning("LPDB warning: %s", _join(warning))
        rows = payload.get("result")
        if rows is None:
            return []
        if not isinstance(rows, list):
            raise ApiError("Unexpected 'result' format from the Liquipedia API.", status=status)
        return [row for row in rows if isinstance(row, dict)]

    async def _default_fetch(
        self, url: str, params: Mapping[str, str], headers: Mapping[str, str]
    ) -> RawResponse:
        import httpx

        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self.timeout, follow_redirects=False)
        response = await self._http.get(url, params=params, headers=headers)
        return RawResponse(response.status_code, response.text, dict(response.headers))


def _replay(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, BaseException):
        raise value
    # Callers may mutate rows; hand out copies so the cache stays intact.
    return json.loads(json.dumps(value))


def _join(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(str(v) for v in value)
    return str(value)


def _retry_after(headers: Mapping[str, str]) -> float | None:
    for name, value in headers.items():
        if name.lower() == "retry-after":
            try:
                return max(0.0, float(value))
            except ValueError:
                return None
    return None
