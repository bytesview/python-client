"""Real-time WebSocket support for NewsData.io.

:class:`NewsDataApiWebSocket` registers / lists / deletes the account's
real-time queries and streams the responses for a registered query —
synchronously via ``stream()`` or inside asyncio applications via
``stream_async()``.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Iterator
from typing import Any

from websockets.asyncio import client as _asyncio_client
from websockets.exceptions import ConnectionClosedError, InvalidStatus
from websockets.sync import client as _sync_client

from . import constants
from .client import NewsDataApiClient, _validate_params
from .exceptions import (
    NewsdataValidationError,
    NewsdataWebSocketAuthError,
    NewsdataWebSocketError,
)


def _check_registration_id(registration_id: str) -> None:
    if not isinstance(registration_id, str) or not registration_id:
        raise NewsdataValidationError(
            "registration_id must be a non-empty string",
            param="registration_id",
        )


def _permanent_auth_error(exc: Exception) -> NewsdataWebSocketAuthError | None:
    """Return the auth error to raise if ``exc`` is a permanent rejection.

    Returns ``None`` for transient failures (which the caller reconnects on):
    handshake 401/403 and policy-violation close 1008 are permanent; anything
    else (other handshake status, other close codes, network ``OSError``) is
    transient.
    """
    if isinstance(exc, InvalidStatus):
        if exc.response.status_code in (401, 403):
            return NewsdataWebSocketAuthError("connection rejected")
        return None
    if isinstance(exc, ConnectionClosedError):
        close = exc.rcvd
        if close is not None and close.code == constants.WS_POLICY_VIOLATION:
            return NewsdataWebSocketAuthError(close.reason or "connection rejected")
        return None
    return None


def _transient_error(exc: Exception) -> NewsdataWebSocketError:
    """Wrap a transient failure as a :class:`NewsdataWebSocketError` (used only
    when ``reconnect=False`` so the caller stops instead of retrying)."""
    if isinstance(exc, InvalidStatus):
        return NewsdataWebSocketError(f"handshake failed (HTTP {exc.response.status_code})")
    if isinstance(exc, ConnectionClosedError):
        return NewsdataWebSocketError("connection closed")
    return NewsdataWebSocketError(f"connection error: {exc}")


class NewsDataApiWebSocket:
    """NewsData.io real-time WebSocket service.

    Registers, lists, and deletes the account's real-time queries
    (:meth:`websocket_register`, :meth:`websocket_fetch`,
    :meth:`websocket_delete`) and streams the responses for a registered
    query (:meth:`stream` / :meth:`stream_async`). The management calls go
    through the wrapped :class:`~newsdataapi.NewsDataApiClient`::

        client = NewsDataApiClient(apikey)
        ws = NewsDataApiWebSocket(client)

        response = ws.websocket_register(q="bitcoin")
        registration_id = response["results"]["registration_id"]

        for response in ws.stream(registration_id):
            for article in response["results"]:
                print(article["title"])

    Use it as a context manager to close the connection promptly when you stop
    early (otherwise it closes when iteration ends or is garbage-collected)::

        with NewsDataApiWebSocket(client) as ws:
            for response in ws.stream(registration_id):
                ...
                break

    Inside asyncio applications use :meth:`stream_async` — the asyncio
    counterpart of :meth:`stream` — with the async context-manager form::

        async with NewsDataApiWebSocket(client) as ws:
            async for response in ws.stream_async(registration_id):
                for article in response["results"]:
                    print(article["title"])

    Transient drops are reconnected automatically with a capped exponential
    backoff (pass ``reconnect=False`` to stop on the first disconnect). A
    permanent rejection (e.g. a bad API key or unknown ``registration_id``)
    always raises :class:`~newsdataapi.NewsdataWebSocketAuthError` and is
    never retried.

    Args:
        api_client: The :class:`~newsdataapi.NewsDataApiClient` that supplies
            the API key and performs the management HTTP calls. Not closed by
            this class.
        base_url: WebSocket endpoint. Defaults to
            :data:`newsdataapi.constants.WS_BASE_URL`; override for staging,
            self-hosted, or proxied environments.
        reconnect: Reconnect automatically on transient drops (default
            ``True``). When ``False``, the stream stops on the first
            disconnect.
        reconnect_delay: Seconds to wait before the first reconnect; doubles
            after each consecutive failure.
        reconnect_delay_max: Upper bound on the reconnect delay.
        open_timeout: Seconds to wait for the opening handshake (``None``
            disables the timeout).
        ping_interval: Seconds between keepalive pings (``None`` disables
            keepalive).
        ping_timeout: Seconds to wait for a ping reply before considering the
            connection dead (``None`` disables).
        additional_headers: Extra HTTP headers for the opening handshake.
        proxy: Proxy URL for the WebSocket connection
            (e.g. ``"http://host:port"``).
    """

    def __init__(
        self,
        api_client: NewsDataApiClient,
        *,
        base_url: str = constants.WS_BASE_URL,
        reconnect: bool = True,
        reconnect_delay: float = constants.WS_RECONNECT_DELAY,
        reconnect_delay_max: float = constants.WS_RECONNECT_DELAY_MAX,
        open_timeout: float | None = 10.0,
        ping_interval: float | None = 20.0,
        ping_timeout: float | None = 20.0,
        additional_headers: dict[str, str] | None = None,
        proxy: str | None = None,
    ) -> None:
        self.api_client = api_client
        self._base_url = base_url
        self._reconnect = reconnect
        self._reconnect_delay = reconnect_delay
        self._reconnect_delay_max = reconnect_delay_max
        self._open_timeout = open_timeout
        self._ping_interval = ping_interval
        self._ping_timeout = ping_timeout
        self._additional_headers = additional_headers
        self._proxy = proxy
        self._ws_sync: Any = None   # the live sync connection, while one is open
        self._ws_async: Any = None  # the live async connection, while one is open

    # ---- query management -------------------------------------------------

    def websocket_register(
        self,
        *,
        q: str | None = None,
        qInTitle: str | None = None,
        qInMeta: str | None = None,
        country: str | list[str] | None = None,
        excludecountry: str | list[str] | None = None,
        category: str | list[str] | None = None,
        excludecategory: str | list[str] | None = None,
        language: str | list[str] | None = None,
        excludelanguage: str | list[str] | None = None,
        domain: str | list[str] | None = None,
        domainurl: str | list[str] | None = None,
        excludedomain: str | list[str] | None = None,
        prioritydomain: str | None = None,
        timezone: str | None = None,
        full_content: bool | None = None,
        image: bool | None = None,
        video: bool | None = None,
        removeduplicate: bool | None = None,
        tag: str | list[str] | None = None,
        sentiment: str | None = None,
        sentiment_score: float | None = None,
        region: str | list[str] | None = None,
        organization: str | list[str] | None = None,
        creator: str | list[str] | None = None,
        datatype: str | list[str] | None = None,
        excludefield: str | list[str] | None = None,
        raw_query: str | None = None,
    ) -> dict[str, Any]:
        """Register a real-time WebSocket query.

        See https://newsdata.io/documentation for parameter descriptions.
        The new query's ``registration_id`` is in ``response["results"]``.
        """
        params = _validate_params(
            {
                "q": q,
                "qInTitle": qInTitle,
                "qInMeta": qInMeta,
                "country": country,
                "excludecountry": excludecountry,
                "category": category,
                "excludecategory": excludecategory,
                "language": language,
                "excludelanguage": excludelanguage,
                "domain": domain,
                "domainurl": domainurl,
                "excludedomain": excludedomain,
                "prioritydomain": prioritydomain,
                "timezone": timezone,
                "full_content": full_content,
                "image": image,
                "video": video,
                "removeduplicate": removeduplicate,
                "tag": tag,
                "sentiment": sentiment,
                "sentiment_score": sentiment_score,
                "region": region,
                "organization": organization,
                "creator": creator,
                "datatype": datatype,
                "excludefield": excludefield,
                "raw_query": raw_query,
            }
        )
        params["news_type"] = constants.WS_NEWS_TYPE
        return self.api_client._request(
            constants.WEBSOCKET_REGISTER_ENDPOINT, params, method="POST"
        )

    def websocket_fetch(self) -> dict[str, Any]:
        """List the registered WebSocket queries.

        ``response["results"]["queries"]`` holds one entry per query.
        """
        return self.api_client._request(constants.WEBSOCKET_FETCH_ENDPOINT, {})

    def websocket_delete(self, registration_id: str) -> dict[str, Any]:
        """Delete the registered WebSocket query with ``registration_id``."""
        _check_registration_id(registration_id)
        return self.api_client._request(
            constants.WEBSOCKET_DELETE_ENDPOINT,
            {"registration_id": registration_id},
            method="DELETE",
        )

    # ---- streaming --------------------------------------------------------

    def _url(self, registration_id: str) -> str:
        return (
            f"{self._base_url}?apikey={self.api_client._apikey}"
            f"&registration_id={registration_id}"
        )

    def _connect_kwargs(self) -> dict[str, Any]:
        return {
            "open_timeout": self._open_timeout,
            "ping_interval": self._ping_interval,
            "ping_timeout": self._ping_timeout,
            "additional_headers": self._additional_headers,
            "proxy": self._proxy,
        }

    def _next_delay(self, delay: float) -> float:
        return min(delay * 2, self._reconnect_delay_max)

    def stream(self, registration_id: str) -> Iterator[dict[str, Any]]:
        """Connect and yield each response for ``registration_id`` as it
        arrives. Responses have the familiar ``status`` / ``totalResults`` /
        ``results`` shape."""
        _check_registration_id(registration_id)
        delay = self._reconnect_delay
        while True:
            try:
                with _sync_client.connect(
                    self._url(registration_id), **self._connect_kwargs()
                ) as websocket:
                    self._ws_sync = websocket
                    delay = self._reconnect_delay  # reset after a successful connect
                    for message in websocket:
                        try:
                            response = json.loads(message)
                        except ValueError:
                            continue  # skip malformed frames
                        if isinstance(response, dict):
                            yield response
            except (InvalidStatus, ConnectionClosedError, OSError) as exc:
                auth = _permanent_auth_error(exc)
                if auth is not None:
                    raise auth from exc
                if not self._reconnect:
                    raise _transient_error(exc) from exc
            else:
                if not self._reconnect:
                    return  # normal close, reconnect disabled
            # Transient failure, or a normal close with reconnect enabled:
            # wait (capped exponential backoff) and reconnect.
            time.sleep(delay)
            delay = self._next_delay(delay)

    async def stream_async(self, registration_id: str) -> AsyncIterator[dict[str, Any]]:
        """Asyncio counterpart of :meth:`stream`."""
        _check_registration_id(registration_id)
        delay = self._reconnect_delay
        while True:
            try:
                async with _asyncio_client.connect(
                    self._url(registration_id), **self._connect_kwargs()
                ) as websocket:
                    self._ws_async = websocket
                    delay = self._reconnect_delay  # reset after a successful connect
                    async for message in websocket:
                        try:
                            response = json.loads(message)
                        except ValueError:
                            continue  # skip malformed frames
                        if isinstance(response, dict):
                            yield response
            except (InvalidStatus, ConnectionClosedError, OSError) as exc:
                auth = _permanent_auth_error(exc)
                if auth is not None:
                    raise auth from exc
                if not self._reconnect:
                    raise _transient_error(exc) from exc
            else:
                if not self._reconnect:
                    return  # normal close, reconnect disabled
            await asyncio.sleep(delay)
            delay = self._next_delay(delay)

    def __enter__(self) -> NewsDataApiWebSocket:
        return self

    def __exit__(self, *exc: object) -> None:
        # Close the active sync connection promptly (e.g. after an early break).
        if self._ws_sync is not None:
            self._ws_sync.close()
            self._ws_sync = None

    async def __aenter__(self) -> NewsDataApiWebSocket:
        return self

    async def __aexit__(self, *exc: object) -> None:
        # Close the active async connection promptly (e.g. after an early break).
        if self._ws_async is not None:
            await self._ws_async.close()
            self._ws_async = None
