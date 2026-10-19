"""Exception hierarchy.

Messages are written to be shown to end users and language models. They never contain
the API key or request headers.
"""


class LiquipediaError(Exception):
    """Base class for all errors raised by this package."""


class ConfigurationError(LiquipediaError):
    """Missing or unacceptable configuration (API key, User-Agent, limits)."""


class InvalidInputError(LiquipediaError, ValueError):
    """User input that cannot be safely turned into an LPDB query."""


class LocalRateLimitError(LiquipediaError):
    """The built-in request budget is used up; no request was sent."""

    def __init__(self, message: str, retry_after: float) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ApiError(LiquipediaError):
    """The API answered with an error, or could not be reached."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class AuthenticationError(ApiError):
    """HTTP 401/403: the key was rejected or lacks access."""


class ServerRateLimitError(ApiError):
    """HTTP 429, or a request refused locally while the post-429 lockout is active."""

    def __init__(self, message: str, retry_after: float) -> None:
        super().__init__(message, status=429)
        self.retry_after = retry_after
