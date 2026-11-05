"""Custom exceptions raised by the HTTP layer.

Each exception carries an HTTP-like status code so the Flask layer can forward it directly.
"""


class ApiError(Exception):
    """Base class for every error coming from (or about) an API call."""

    status_code = 502  # default: upstream failure

    def __init__(self, message: str, status_code: int | None = None, url: str | None = None):
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code
        self.url = url


class InvalidIdentifierError(ApiError):
    """The identifier is malformed: rejected locally, no request is sent."""

    status_code = 400


class BadRequestError(ApiError):
    status_code = 400


class UnauthorizedError(ApiError):
    """401: token missing or invalid."""

    status_code = 401


class ForbiddenError(ApiError):
    """403: authenticated but not allowed to access the resource."""

    status_code = 403


class NotFoundError(ApiError):
    """404: unknown Pokémon, type or route."""

    status_code = 404


class RateLimitError(ApiError):
    """429: still rate-limited after every retry."""

    status_code = 429


class ServerError(ApiError):
    """5xx: upstream server still failing after every retry."""

    status_code = 503


class NetworkError(ApiError):
    """Timeout or connection failure after every retry."""

    status_code = 504
