"""Tolerant converters for LPDB values (types in responses differ from the docs)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

_SUFFIX_RE = re.compile(r"_\(.*\)$")


def to_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"-?\d+", text):
            return int(text)
    return None


def to_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def to_dict(value: Any) -> dict[str, Any]:
    """LPDB sometimes returns nested objects as JSON strings, or ``[]`` for empty ones."""
    if isinstance(value, str) and value.strip().startswith("{"):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def to_list(value: Any) -> list[Any]:
    if isinstance(value, str) and value.strip().startswith("["):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    if isinstance(value, dict):
        # Some arrays come back as {"1": ..., "2": ...}
        return [value[k] for k in sorted(value, key=lambda k: to_int(k) or 0)]
    return value if isinstance(value, list) else []


def to_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_date(value: Any) -> datetime | None:
    """LPDB dates look like ``2026-09-14 18:00:00`` and are UTC."""
    text = to_str(value)
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.year < 1980:  # 1970-01-01 placeholders
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def clean_player_name(name: str) -> str:
    """``Diaz_(Brazilian_Player)`` -> ``Diaz``; underscores become spaces."""
    return _SUFFIX_RE.sub("", name).replace("_", " ").strip()
