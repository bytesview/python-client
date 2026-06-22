"""Synchronous consumer for the NewsData.io real-time WebSocket service.

Requires the optional ``websocket`` extra::

    pip install "newsdataapi[websocket]"
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

from . import constants
from .exceptions import NewsdataWebSocketAuthError, NewsdataWebSocketError

_POLICY_VIOLATION = 1008      # server close code for auth / quota / device-limit
_RECONNECT_DELAY = 1.0        # default seconds before the first reconnect; doubles each retry
_RECONNECT_DELAY_MAX = 30.0   # default cap on the reconnect delay


class NewsDataApiWebSocket:
    """Streams real-time news matched by a registered percolator query.

    ``registration_id`` is the ``doc_id`` returned when the query was
    registered. Call :meth:`stream` (or iterate the object directly) to
    receive matched articles as they arrive::

        ws = NewsDataApiWebSocket(apikey, registration_id)
        for article in ws.stream():        # or: for article in ws
            print(article["title"])

    Use it as a context manager to close the connection promptly when you stop
    early (otherwise it closes when iteration ends or is garbage-collected)::

        with NewsDataApiWebSocket(apikey, registration_id) as ws:
            for article in ws:
                ...
                break

    Transient drops (network errors, server restarts, abnormal closes) are
    reconnected automatically with a capped exponential backoff; pass
    ``reconnect=False`` to stop on the first disconnect instead. A permanent
    rejection (bad key, missing entitlement, unknown ``registration_id``,
    device limit, or exhausted quota) always raises
    :class:`~newsdataapi.NewsdataWebSocketAuthError` and is never retried.

    Args:
        apikey: Your NewsData.io API key.
        registration_id: The ``doc_id`` of a registered percolator query.
        base_url: WebSocket endpoint. Defaults to
            :data:`newsdataapi.constants.WS_BASE_URL`; override for staging,
            self-hosted, or proxied environments.
        reconnect: Reconnect automatically on transient drops (default
            ``True``). When ``False``, the stream stops on the first
            disconnect.
        reconnect_delay: Seconds to wait before the first reconnect; doubles
            after each consecutive failure.
        reconnect_delay_max: Upper bound on the reconnect delay.
        open_timeout: Seconds to wait for the opening handshake before giving
            up (``None`` disables the timeout).
        ping_interval: Seconds between keepalive pings (``None`` disables
            keepalive).
        ping_timeout: Seconds to wait for a ping reply before considering the
            connection dead (``None`` disables).
        additional_headers: Extra HTTP headers for the opening handshake.
        proxy: Proxy URL for the connection (e.g. ``"http://host:port"``).
    """

    def __init__(
        self,
        apikey: str,
        registration_id: str,
        *,
        base_url: str = constants.WS_BASE_URL,
        reconnect: bool = True,
        reconnect_delay: float = _RECONNECT_DELAY,
        reconnect_delay_max: float = _RECONNECT_DELAY_MAX,
        open_timeout: float | None = 10.0,
        ping_interval: float | None = 20.0,
        ping_timeout: float | None = 20.0,
        additional_headers: dict[str, str] | None = None,
        proxy: str | None = None,
    ) -> None:
        self._apikey = apikey
        self._registration_id = registration_id
        self._base_url = base_url
        self._reconnect = reconnect
        self._reconnect_delay = reconnect_delay
        self._reconnect_delay_max = reconnect_delay_max
        self._open_timeout = open_timeout
        self._ping_interval = ping_interval
        self._ping_timeout = ping_timeout
        self._additional_headers = additional_headers
        self._proxy = proxy
        self._ws: Any = None  # the live connection, while one is open

    def stream(self) -> Iterator[dict[str, Any]]:
        """Connect and yield matched articles as they arrive.

        This is the same as iterating the object directly
        (``for article in ws``).
        """
        try:
            from websockets.exceptions import ConnectionClosedError, InvalidStatus
            from websockets.sync.client import connect
        except ImportError as exc:
            raise NewsdataWebSocketError(
                "the websocket extra is required: "
                "pip install 'newsdataapi[websocket]'"
            ) from exc

        url = (
            f"{self._base_url}?apikey={self._apikey}"
            f"&registration_id={self._registration_id}"
        )
        delay = self._reconnect_delay
        while True:
            try:
                with connect(
                    url,
                    open_timeout=self._open_timeout,
                    ping_interval=self._ping_interval,
                    ping_timeout=self._ping_timeout,
                    additional_headers=self._additional_headers,
                    proxy=self._proxy,
                ) as websocket:
                    self._ws = websocket
                    delay = self._reconnect_delay  # reset after a successful connect
                    for message in websocket:
                        event = json.loads(message)
                        yield from event.get("items", [])
            except InvalidStatus as exc:
                status = exc.response.status_code
                if status in (401, 403):
                    raise NewsdataWebSocketAuthError("connection rejected") from exc
                if not self._reconnect:
                    raise NewsdataWebSocketError(
                        f"handshake failed (HTTP {status})"
                    ) from exc
            except ConnectionClosedError as exc:
                close = exc.rcvd
                if close is not None and close.code == _POLICY_VIOLATION:
                    raise NewsdataWebSocketAuthError(
                        close.reason or "connection rejected"
                    ) from exc
                if not self._reconnect:
                    raise NewsdataWebSocketError("connection closed") from exc
            except OSError as exc:
                if not self._reconnect:
                    raise NewsdataWebSocketError(f"connection error: {exc}") from exc
            else:
                if not self._reconnect:
                    return  # normal close, reconnect disabled
            # Transient failure, or a normal close with reconnect enabled:
            # wait (capped exponential backoff) and reconnect.
            time.sleep(delay)
            delay = min(delay * 2, self._reconnect_delay_max)

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return self.stream()

    def __enter__(self) -> NewsDataApiWebSocket:
        return self

    def __exit__(self, *exc: object) -> None:
        # Close the active connection promptly (e.g. after an early break).
        # Closing again on generator finalization is a harmless no-op.
        if self._ws is not None:
            self._ws.close()
            self._ws = None
