"""Validation of everything that ends up in an LPDB request.

User-supplied names (teams, tournaments) are interpolated into ``conditions`` strings
like ``[[opponent::Team Liquid]]``. Anything that could close the bracket, start a new
condition, change the comparison operator or chain conditions is rejected rather than
escaped, because LPDB has no documented escaping mechanism.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime

from liquipedia_mcp.errors import InvalidInputError

WIKI_RE = re.compile(r"^[a-z0-9]+$")
MAX_WIKIS = 10
MAX_NAME_LENGTH = 100
MAX_TIER = 5

_FORBIDDEN_SUBSTRINGS = ("[", "]", "{", "}", "|", "::")
# A leading operator character would turn `[[field::value]]` into `::!`, `::<`, `::>`
# or a LIKE match (`::~`).
_FORBIDDEN_PREFIXES = ("!", "<", ">", "~")
_KEYWORD_RE = re.compile(r"(?:^|\s)(AND|OR)(?:\s|$)", re.IGNORECASE)


def validate_wiki(wiki: str) -> str:
    """Return a single wiki name (e.g. ``rocketleague``) or raise."""
    if not isinstance(wiki, str):
        raise InvalidInputError("Wiki name must be a string.")
    wiki = wiki.strip()
    if not WIKI_RE.fullmatch(wiki) or len(wiki) > 50:
        raise InvalidInputError(
            f"Invalid wiki name {wiki!r}: use the lowercase Liquipedia wiki id, "
            "e.g. 'rocketleague' or 'leagueoflegends'."
        )
    return wiki


def validate_wikis(wikis: str | Iterable[str]) -> list[str]:
    """Accept ``"a|b"``, ``"a,b"`` or an iterable; return a de-duplicated list."""
    parts = re.split(r"[|,\s]+", wikis) if isinstance(wikis, str) else list(wikis)
    result: list[str] = []
    for part in parts:
        if isinstance(part, str) and not part.strip():
            continue
        wiki = validate_wiki(part)
        if wiki not in result:
            result.append(wiki)
    if not result:
        raise InvalidInputError("At least one wiki is required.")
    if len(result) > MAX_WIKIS:
        raise InvalidInputError(f"At most {MAX_WIKIS} wikis per request.")
    return result


def validate_name(value: str, what: str = "name") -> str:
    """Validate a team or tournament name for use inside ``[[field::value]]``."""
    if not isinstance(value, str):
        raise InvalidInputError(f"The {what} must be a string.")
    value = " ".join(value.split())  # collapse whitespace, strip, drop newlines/tabs
    if not value:
        raise InvalidInputError(f"The {what} must not be empty.")
    if len(value) > MAX_NAME_LENGTH:
        raise InvalidInputError(f"The {what} is too long (max {MAX_NAME_LENGTH} characters).")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise InvalidInputError(f"The {what} contains control characters.")
    for bad in _FORBIDDEN_SUBSTRINGS:
        if bad in value:
            raise InvalidInputError(f"The {what} must not contain {bad!r}.")
    if value.startswith(_FORBIDDEN_PREFIXES):
        raise InvalidInputError(f"The {what} must not start with {value[0]!r}.")
    if _KEYWORD_RE.search(value):
        raise InvalidInputError(
            f"The {what} must not contain the stand-alone words AND/OR "
            "(they would change the query)."
        )
    return value


def validate_tier(max_tier: int) -> int:
    """Liquipedia tiers: 1=S, 2=A, 3=B, 4=C, 5=D."""
    if isinstance(max_tier, bool) or not isinstance(max_tier, int):
        raise InvalidInputError("max_tier must be an integer between 1 (S-Tier) and 5 (D-Tier).")
    if not 1 <= max_tier <= MAX_TIER:
        raise InvalidInputError("max_tier must be between 1 (S-Tier) and 5 (D-Tier).")
    return max_tier


def clamp(value: int, lo: int, hi: int) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise InvalidInputError("Expected an integer.") from None
    return max(lo, min(hi, value))


def parse_utc(value: str | datetime, what: str = "timestamp") -> datetime:
    """Parse ISO 8601; naive values are taken as UTC. Returns an aware UTC datetime."""
    if isinstance(value, datetime):
        dt = value
    else:
        if not isinstance(value, str) or len(value) > 40:
            raise InvalidInputError(f"Invalid {what}: expected an ISO 8601 string.")
        text = value.strip()
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            raise InvalidInputError(
                f"Invalid {what} {value!r}: expected ISO 8601, e.g. 2026-10-19T18:00:00Z."
            ) from None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def lpdb_datetime(dt: datetime) -> str:
    """Format a UTC datetime the way LPDB stores ``date`` values."""
    return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")
