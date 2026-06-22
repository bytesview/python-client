"""Exception hierarchy for :mod:`newsdataapi`.

All errors raised by the SDK derive from :class:`NewsdataException`, so
callers can use ``except NewsdataException`` as a catch-all. More specific
subclasses are provided for cases where callers want to react differently
(rate limiting, auth, validation, network, etc.).
"""

from __future__ import annotations

from typing import Any


class NewsdataException(Exception):
    """Base class for every error raised by :mod:`newsdataapi`."""


class NewsdataValidationError(NewsdataException, ValueError):
    """A user-provided parameter failed client-side validation.

    Subclasses :class:`ValueError` so existing ``except ValueError`` paths
    still catch it.
    """

    def __init__(self, message: str, *, param: str | None = None) -> None:
        super().__init__(message)
        self.param = param


class NewsdataAPIError(NewsdataException):
    """The API returned a structured error response.

    Attributes:
        status_code: HTTP status returned by the API.
        response_body: Parsed JSON body of the error response, when available.
    """

    def __init__(
        self,
        message: Any,
        *,
        status_code: int | None = None,
        response_body: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class NewsdataAuthError(NewsdataAPIError):
    """Raised on 401 / 403 responses (missing, invalid, or unauthorized API key)."""


class NewsdataRateLimitError(NewsdataAPIError):
    """Raised on 429 responses when retries are exhausted.

    Attributes:
        retry_after: Seconds to wait before retrying, parsed from the
            ``Retry-After`` header when available. May be ``None`` if the
            server did not provide a parseable value.
    """

    def __init__(
        self,
        message: Any,
        *,
        status_code: int | None = 429,
        response_body: dict[str, Any] | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=status_code,
            response_body=response_body,
        )
        self.retry_after = retry_after


class NewsdataServerError(NewsdataAPIError):
    """Raised on 5xx responses when retries are exhausted."""


class NewsdataNetworkError(NewsdataException):
    """A network-level failure prevented the request from completing.

    Attributes:
        original: The underlying exception (typically a
            :class:`requests.exceptions.RequestException`).
    """

    def __init__(
        self,
        message: Any,
        *,
        original: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.original = original


class NewsdataWebSocketError(NewsdataException):
    """A real-time WebSocket consumer error
    (:class:`newsdataapi.NewsDataApiWebSocket`)."""


class NewsdataWebSocketAuthError(NewsdataWebSocketError):
    """The server rejected the WebSocket connection — bad API key, missing
    WebSocket entitlement, unknown ``registration_id``, device limit reached,
    or exhausted quota. Not retried."""
