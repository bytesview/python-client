"""Mocked unit tests for both stream modes of NewsDataApiWebSocket.

Patch ``websockets.sync.client.connect`` / ``websockets.asyncio.client.connect``
with a scripted fake. Async tests drive the coroutines with ``asyncio.run`` so
no ``pytest-asyncio`` plugin is needed.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosedError, InvalidStatus
from websockets.frames import Close
from websockets.http11 import Response

from newsdataapi import (
    NewsDataApiClient,
    NewsDataApiWebSocket,
    NewsdataValidationError,
    NewsdataWebSocketAuthError,
    NewsdataWebSocketError,
)

CONNECT = "websockets.sync.client.connect"
CONNECT_ASYNC = "websockets.asyncio.client.connect"


def _news(*titles: str) -> str:
    """One server frame, shaped exactly like the live dispatcher's payload."""
    return json.dumps(
        {
            "status": "success",
            "totalResults": len(titles),
            "results": [{"title": t} for t in titles],
        }
    )


def _closed(code: int, reason: str = "") -> ConnectionClosedError:
    return ConnectionClosedError(Close(code, reason), None)


def _invalid_status(status: int) -> InvalidStatus:
    return InvalidStatus(Response(status, "x", Headers(), b""))


class _FakeWS:
    """A scripted sync connection: yields ``messages`` then raises ``terminal``
    (a ConnectionClosedError) or ends normally if ``terminal`` is None."""

    def __init__(self, messages: list, terminal: BaseException | None) -> None:
        self._messages = messages
        self._terminal = terminal
        self.closed = False

    def __enter__(self) -> _FakeWS:
        return self

    def __exit__(self, *exc: object) -> bool:
        self.close()  # the real sync client closes the socket on context exit
        return False

    def __iter__(self):
        yield from self._messages
        if self._terminal is not None:
            raise self._terminal

    def close(self) -> None:
        self.closed = True


class _FakeConnect:
    """Scripted ``connect``: each attempt is ``(messages, terminal)``.

    ``terminal`` raised from ``connect()`` itself if it is an ``InvalidStatus``
    or ``OSError`` (handshake / network failure), otherwise during iteration.
    Once the script is exhausted it closes with 1008 to stop any reconnect loop.
    """

    def __init__(self, *attempts: tuple[list, BaseException | None]) -> None:
        self._attempts = list(attempts)
        self.calls = 0
        self.urls: list[str] = []
        self.kwargs: list[dict] = []
        self.conns: list[_FakeWS] = []

    def __call__(self, url: str, **kwargs: object) -> _FakeWS:
        self.calls += 1
        self.urls.append(url)
        self.kwargs.append(kwargs)
        if self._attempts:
            messages, terminal = self._attempts.pop(0)
        else:
            messages, terminal = [], _closed(1008, "exhausted")
        if isinstance(terminal, (InvalidStatus, OSError)):
            raise terminal
        conn = _FakeWS(messages, terminal)
        self.conns.append(conn)
        return conn


async def _anoop(*_a: object, **_k: object) -> None:
    return None


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("newsdataapi.websocket.time.sleep", lambda *_a: None)
    monkeypatch.setattr("newsdataapi.websocket.asyncio.sleep", _anoop)


def _ws(apikey: str = "k", **kwargs: object) -> NewsDataApiWebSocket:
    return NewsDataApiWebSocket(NewsDataApiClient(apikey), **kwargs)


def _collect(ws: NewsDataApiWebSocket, sink: list[str], registration_id: str = "r") -> None:
    for response in ws.stream(registration_id):
        sink.extend(article["title"] for article in response["results"])


# --- basics -----------------------------------------------------------------


def test_url_includes_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeConnect(([_news("A")], None))
    monkeypatch.setattr(CONNECT, fake)
    list(_ws("KEY", reconnect=False).stream("REG"))
    assert fake.urls[0] == "wss://ws.newsdata.io/ws/event?apikey=KEY&registration_id=REG"


def test_custom_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeConnect(([_news("A")], None))
    monkeypatch.setattr(CONNECT, fake)
    ws = _ws("KEY", base_url="wss://staging.example/ws", reconnect=False)
    list(ws.stream("REG"))
    assert fake.urls[0] == "wss://staging.example/ws?apikey=KEY&registration_id=REG"


def test_connect_params_passed_through(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeConnect(([_news("A")], None))
    monkeypatch.setattr(CONNECT, fake)
    headers = {"X-Trace": "1"}
    ws = _ws(
        reconnect=False,
        open_timeout=5.0,
        ping_interval=7.0,
        ping_timeout=8.0,
        additional_headers=headers,
        proxy="http://proxy:3128",
    )
    list(ws.stream("r"))
    kw = fake.kwargs[0]
    assert kw["open_timeout"] == 5.0
    assert kw["ping_interval"] == 7.0
    assert kw["ping_timeout"] == 8.0
    assert kw["additional_headers"] == headers
    assert kw["proxy"] == "http://proxy:3128"


def test_custom_reconnect_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr(
        "newsdataapi.websocket.time.sleep", lambda d: slept.append(d)
    )
    fake = _FakeConnect(
        ([], _closed(1011, "boom")),  # transient -> reconnect after reconnect_delay
        ([_news("A")], _closed(1008, "stop")),  # permanent -> raise
    )
    monkeypatch.setattr(CONNECT, fake)
    ws = _ws(reconnect_delay=2.5, reconnect_delay_max=99.0)
    with pytest.raises(NewsdataWebSocketAuthError):
        list(ws.stream("r"))
    assert slept == [2.5]  # used the configured base delay


def test_yields_whole_server_responses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CONNECT, _FakeConnect(([_news("A", "B"), _news("C")], None)))
    got = list(_ws(reconnect=False).stream("r"))
    assert [r["status"] for r in got] == ["success", "success"]
    assert [r["totalResults"] for r in got] == [2, 1]
    assert [[a["title"] for a in r["results"]] for r in got] == [["A", "B"], ["C"]]


def test_malformed_frames_are_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    frames = ["not json", json.dumps(["not", "a", "dict"]), _news("A")]
    monkeypatch.setattr(CONNECT, _FakeConnect((frames, None)))
    got = list(_ws(reconnect=False).stream("r"))
    assert [r["totalResults"] for r in got] == [1]


@pytest.mark.parametrize("bad_id", ["", None, 123])
def test_stream_rejects_bad_registration_id(bad_id: object) -> None:
    with pytest.raises(NewsdataValidationError) as exc_info:
        next(_ws().stream(bad_id))  # type: ignore[arg-type]
    assert exc_info.value.param == "registration_id"


# --- context manager: prompt close on early break ---------------------------


def test_context_manager_returns_self() -> None:
    ws = _ws(reconnect=False)
    with ws as entered:
        assert entered is ws


def test_context_manager_closes_on_break(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeConnect(([_news("A"), _news("B")], None))
    monkeypatch.setattr(CONNECT, fake)
    ws = _ws(reconnect=False)
    with ws:
        for _article in ws.stream("r"):
            break
    assert fake.conns[0].closed is True  # closed promptly on context exit
    assert fake.calls == 1


# --- permanent rejection: never retried, even with reconnect=True -----------


def test_handshake_403_raises_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeConnect(([], _invalid_status(403)))
    monkeypatch.setattr(CONNECT, fake)
    with pytest.raises(NewsdataWebSocketAuthError):
        list(_ws().stream("r"))  # reconnect=True default
    assert fake.calls == 1


def test_close_1008_raises_auth_with_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeConnect(([_news("A")], _closed(1008, "device limit")))
    monkeypatch.setattr(CONNECT, fake)
    got: list[str] = []
    with pytest.raises(NewsdataWebSocketAuthError, match="device limit"):
        _collect(_ws(), got)
    assert got == ["A"]
    assert fake.calls == 1


# --- reconnect=False: stop on first drop ------------------------------------


def test_no_reconnect_normal_close_ends(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeConnect(([_news("A")], None))
    monkeypatch.setattr(CONNECT, fake)
    got: list[str] = []
    _collect(_ws(reconnect=False), got)
    assert got == ["A"]
    assert fake.calls == 1


def test_no_reconnect_abnormal_close_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeConnect(([_news("A")], _closed(1011, "boom")))
    monkeypatch.setattr(CONNECT, fake)
    got: list[str] = []
    with pytest.raises(NewsdataWebSocketError) as exc_info:
        _collect(_ws(reconnect=False), got)
    assert not isinstance(exc_info.value, NewsdataWebSocketAuthError)
    assert got == ["A"]
    assert fake.calls == 1


def test_no_reconnect_handshake_5xx_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CONNECT, _FakeConnect(([], _invalid_status(503))))
    with pytest.raises(NewsdataWebSocketError) as exc_info:
        list(_ws(reconnect=False).stream("r"))
    assert not isinstance(exc_info.value, NewsdataWebSocketAuthError)


# --- reconnect=True: retry transient drops ----------------------------------


def test_reconnects_on_transient_close(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeConnect(
        ([_news("A")], _closed(1013, "slow client")),  # transient -> reconnect
        ([_news("B")], _closed(1008, "stop")),  # permanent -> raise (ends test)
    )
    monkeypatch.setattr(CONNECT, fake)
    got: list[str] = []
    with pytest.raises(NewsdataWebSocketAuthError):
        _collect(_ws(), got)
    assert got == ["A", "B"]
    assert fake.calls == 2


def test_reconnects_on_normal_close(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeConnect(
        ([_news("A")], None),  # normal close -> reconnect
        ([_news("B")], _closed(1008, "stop")),
    )
    monkeypatch.setattr(CONNECT, fake)
    got: list[str] = []
    with pytest.raises(NewsdataWebSocketAuthError):
        _collect(_ws(), got)
    assert got == ["A", "B"]
    assert fake.calls == 2


def test_reconnects_on_handshake_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeConnect(
        ([], _invalid_status(503)),  # transient handshake -> reconnect
        ([_news("A")], _closed(1008, "stop")),
    )
    monkeypatch.setattr(CONNECT, fake)
    got: list[str] = []
    with pytest.raises(NewsdataWebSocketAuthError):
        _collect(_ws(), got)
    assert got == ["A"]
    assert fake.calls == 2


def test_reconnects_on_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeConnect(
        ([], OSError("connection refused")),  # network failure -> reconnect
        ([_news("A")], _closed(1008, "stop")),
    )
    monkeypatch.setattr(CONNECT, fake)
    got: list[str] = []
    with pytest.raises(NewsdataWebSocketAuthError):
        _collect(_ws(), got)
    assert got == ["A"]
    assert fake.calls == 2


# ===========================================================================
# Async streaming (NewsDataApiWebSocket.stream_async)
# ===========================================================================


class _FakeAsyncWS:
    """Scripted async connection: yields ``messages`` then raises ``terminal``
    (a ConnectionClosedError) or ends normally if ``terminal`` is None."""

    def __init__(self, messages: list, terminal: BaseException | None) -> None:
        self._messages = messages
        self._terminal = terminal
        self.closed = False

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for message in self._messages:
            yield message
        if self._terminal is not None:
            raise self._terminal

    async def close(self) -> None:
        self.closed = True


class _FakeAsyncCM:
    """The async context manager returned by the fake ``connect()``."""

    def __init__(self, ws: _FakeAsyncWS | None, handshake_exc: BaseException | None) -> None:
        self._ws = ws
        self._handshake_exc = handshake_exc

    async def __aenter__(self) -> _FakeAsyncWS:
        if self._handshake_exc is not None:
            raise self._handshake_exc
        assert self._ws is not None
        return self._ws

    async def __aexit__(self, *exc: object) -> bool:
        if self._ws is not None:
            await self._ws.close()
        return False


class _FakeAsyncConnect:
    """Scripted async ``connect``: each attempt is ``(messages, terminal)``.

    An ``InvalidStatus`` / ``OSError`` terminal is raised from ``__aenter__``
    (handshake failure); otherwise it is raised during async iteration.
    """

    def __init__(self, *attempts: tuple[list, BaseException | None]) -> None:
        self._attempts = list(attempts)
        self.calls = 0
        self.urls: list[str] = []
        self.kwargs: list[dict] = []
        self.conns: list[_FakeAsyncWS] = []

    def __call__(self, url: str, **kwargs: object) -> _FakeAsyncCM:
        self.calls += 1
        self.urls.append(url)
        self.kwargs.append(kwargs)
        if self._attempts:
            messages, terminal = self._attempts.pop(0)
        else:
            messages, terminal = [], _closed(1008, "exhausted")
        if isinstance(terminal, (InvalidStatus, OSError)):
            return _FakeAsyncCM(None, terminal)
        conn = _FakeAsyncWS(messages, terminal)
        self.conns.append(conn)
        return _FakeAsyncCM(conn, None)


def _atitles(ws: NewsDataApiWebSocket, registration_id: str = "r") -> list[str]:
    """Fully consume the async stream and return article titles."""

    async def go() -> list[str]:
        return [
            article["title"]
            async for response in ws.stream_async(registration_id)
            for article in response["results"]
        ]

    return asyncio.run(go())


def _acollect(ws: NewsDataApiWebSocket, sink: list[str], registration_id: str = "r") -> None:
    """Consume into ``sink`` so partial results survive a raised exception."""

    async def go() -> None:
        async for response in ws.stream_async(registration_id):
            sink.extend(article["title"] for article in response["results"])

    asyncio.run(go())


# --- basics -----------------------------------------------------------------


def test_async_url_and_params(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeAsyncConnect(([_news("A")], None))
    monkeypatch.setattr(CONNECT_ASYNC, fake)
    headers = {"X-Trace": "1"}
    ws = _ws(
        "KEY",
        base_url="wss://staging.example/ws",
        reconnect=False,
        open_timeout=5.0,
        additional_headers=headers,
        proxy="http://proxy:3128",
    )
    _atitles(ws, "REG")
    assert fake.urls[0] == "wss://staging.example/ws?apikey=KEY&registration_id=REG"
    assert fake.kwargs[0]["open_timeout"] == 5.0
    assert fake.kwargs[0]["additional_headers"] == headers
    assert fake.kwargs[0]["proxy"] == "http://proxy:3128"


def test_async_yields_whole_server_responses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CONNECT_ASYNC, _FakeAsyncConnect(([_news("A", "B"), _news("C")], None)))

    async def go() -> list[dict]:
        return [r async for r in _ws(reconnect=False).stream_async("r")]

    got = asyncio.run(go())
    assert [r["totalResults"] for r in got] == [2, 1]
    assert [[a["title"] for a in r["results"]] for r in got] == [["A", "B"], ["C"]]


def test_async_malformed_frames_are_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    frames = ["not json", json.dumps(["not", "a", "dict"]), _news("A")]
    monkeypatch.setattr(CONNECT_ASYNC, _FakeAsyncConnect((frames, None)))
    assert _atitles(_ws(reconnect=False)) == ["A"]


# --- context manager --------------------------------------------------------


def test_async_context_manager_closes_on_break(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeAsyncConnect(([_news("A"), _news("B")], None))
    monkeypatch.setattr(CONNECT_ASYNC, fake)

    async def go() -> None:
        ws = _ws(reconnect=False)
        async with ws:
            agen = ws.stream_async("r")
            async for _article in agen:
                break
            await agen.aclose()  # close the suspended generator within the loop

    asyncio.run(go())
    assert fake.conns[0].closed is True
    assert fake.calls == 1


# --- permanent rejection ----------------------------------------------------


def test_async_handshake_403_raises_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeAsyncConnect(([], _invalid_status(403)))
    monkeypatch.setattr(CONNECT_ASYNC, fake)
    with pytest.raises(NewsdataWebSocketAuthError):
        _atitles(_ws())  # reconnect=True default
    assert fake.calls == 1


def test_async_close_1008_raises_auth_with_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeAsyncConnect(([_news("A")], _closed(1008, "device limit")))
    monkeypatch.setattr(CONNECT_ASYNC, fake)
    got: list[str] = []
    with pytest.raises(NewsdataWebSocketAuthError, match="device limit"):
        _acollect(_ws(), got)
    assert got == ["A"]
    assert fake.calls == 1


# --- reconnect=False --------------------------------------------------------


def test_async_no_reconnect_abnormal_close_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeAsyncConnect(([_news("A")], _closed(1011, "boom")))
    monkeypatch.setattr(CONNECT_ASYNC, fake)
    got: list[str] = []
    with pytest.raises(NewsdataWebSocketError) as exc_info:
        _acollect(_ws(reconnect=False), got)
    assert not isinstance(exc_info.value, NewsdataWebSocketAuthError)
    assert got == ["A"]


# --- reconnect=True ---------------------------------------------------------


def test_async_reconnects_on_transient_close(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeAsyncConnect(
        ([_news("A")], _closed(1013, "slow client")),  # transient -> reconnect
        ([_news("B")], _closed(1008, "stop")),  # permanent -> raise
    )
    monkeypatch.setattr(CONNECT_ASYNC, fake)
    got: list[str] = []
    with pytest.raises(NewsdataWebSocketAuthError):
        _acollect(_ws(), got)
    assert got == ["A", "B"]
    assert fake.calls == 2


def test_async_reconnects_on_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeAsyncConnect(
        ([], OSError("connection refused")),  # network failure -> reconnect
        ([_news("A")], _closed(1008, "stop")),
    )
    monkeypatch.setattr(CONNECT_ASYNC, fake)
    got: list[str] = []
    with pytest.raises(NewsdataWebSocketAuthError):
        _acollect(_ws(), got)
    assert got == ["A"]
    assert fake.calls == 2
