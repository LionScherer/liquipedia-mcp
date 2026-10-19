"""Rate-limited, cache-first access to the Liquipedia LPDB v3 API.

The core (``client``, ``matches``, ``standings``, ``format``) works without MCP and
returns structured dataclasses. ``server`` wraps it as an MCP server.

Data retrieved through this package comes from Liquipedia (https://liquipedia.net)
and is licensed under CC-BY-SA 3.0; see ``ATTRIBUTION``.
"""

__version__ = "0.1.0"

from liquipedia_mcp.client import LiquipediaClient, RawResponse
from liquipedia_mcp.errors import (
    ApiError,
    AuthenticationError,
    ConfigurationError,
    InvalidInputError,
    LiquipediaError,
    LocalRateLimitError,
    ServerRateLimitError,
)
from liquipedia_mcp.models import ATTRIBUTION

__all__ = [
    "ATTRIBUTION",
    "ApiError",
    "AuthenticationError",
    "ConfigurationError",
    "InvalidInputError",
    "LiquipediaClient",
    "LiquipediaError",
    "LocalRateLimitError",
    "RawResponse",
    "ServerRateLimitError",
    "__version__",
]
