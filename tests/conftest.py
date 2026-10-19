"""Shared test helpers. No test touches the network: every request goes to ``FakeApi``."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

import pytest

from liquipedia_mcp.client import LiquipediaClient, RawResponse

FIXTURES = Path(__file__).parent / "fixtures"
TEST_KEY = "test-key-0123456789abcdef"
TEST_UA = "liquipedia-mcp-tests/0.1 (https://github.com/LionScherer/liquipedia-mcp)"


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


T = TypeVar("T")


def run(coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


class FakeClock:
    def __init__(self, start: float = 10_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class Call:
    url: str
    params: dict[str, str]
    headers: dict[str, str]

    @property
    def endpoint(self) -> str:
        return self.url.rsplit("/", 1)[-1]


@dataclass
class Route:
    endpoint: str
    contains: tuple[str, ...]
    status: int
    text: str
    headers: Mapping[str, str] = field(default_factory=dict)


class FakeApi:
    """Answers requests from fixtures, matched by endpoint and condition substrings."""

    def __init__(self) -> None:
        self.routes: list[Route] = []
        self.calls: list[Call] = []

    def add(
        self,
        endpoint: str,
        body: Any = None,
        *,
        contains: tuple[str, ...] | str = (),
        status: int = 200,
        text: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> FakeApi:
        if isinstance(contains, str):
            contains = (contains,)
        if isinstance(body, str) and body.endswith(".json"):
            body = load(body)
        payload = text if text is not None else json.dumps(body if body is not None else {})
        self.routes.append(Route(endpoint, contains, status, payload, headers or {}))
        return self

    async def __call__(
        self, url: str, params: Mapping[str, str], headers: Mapping[str, str]
    ) -> RawResponse:
        call = Call(url, dict(params), dict(headers))
        self.calls.append(call)
        conditions = call.params.get("conditions", "")
        for route in self.routes:
            if route.endpoint == call.endpoint and all(c in conditions for c in route.contains):
                return RawResponse(route.status, route.text, route.headers)
        raise AssertionError(f"Unexpected request: {call.endpoint} {call.params}")


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def client(api: FakeApi, clock: FakeClock) -> LiquipediaClient:
    return LiquipediaClient(TEST_KEY, TEST_UA, fetch=api, clock=clock)
