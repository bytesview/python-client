"""Real-time news streaming example for the newsdataapi SDK.

Run with::

    NEWSDATA_API_KEY=<key> python examples/websocket_usage.py

Set NEWSDATA_WS_MODE=async to run the asyncio example instead of the sync one.

Articles are matched by a registered query. If NEWSDATA_REGISTRATION_ID is
set, that query is streamed directly; otherwise the example registers a demo
query (``q="pizza"``) first and prints the resulting ``registration_id`` so
you can reuse it on the next run or remove it later with
``NewsDataApiWebSocket(client).websocket_delete(registration_id)``.
"""

from __future__ import annotations

import asyncio
import os

from newsdataapi import (
    NewsDataApiClient,
    NewsdataAPIError,
    NewsDataApiWebSocket,
    NewsdataWebSocketAuthError,
)


def _client_and_registration() -> tuple[NewsDataApiClient, str]:
    apikey = os.environ.get("NEWSDATA_API_KEY")
    if not apikey:
        raise SystemExit(
            "Set NEWSDATA_API_KEY in your environment before running this example."
        )
    client = NewsDataApiClient(apikey)
    registration_id = os.environ.get("NEWSDATA_REGISTRATION_ID")
    if not registration_id:
        registration_id = _register_demo_query(client)
    return client, registration_id


def _register_demo_query(client: NewsDataApiClient) -> str:
    """Register a demo query and return its ``registration_id``.

    Registering an identical query again answers HTTP 409 with the existing
    id in the response body — reuse it instead of failing.
    """
    try:
        response = NewsDataApiWebSocket(client).websocket_register(q="pizza")
    except NewsdataAPIError as exc:
        if exc.status_code == 409 and exc.response_body:
            registration_id: str = exc.response_body["results"]["registration_id"]
            print(f"query already registered; reusing {registration_id}")
            return registration_id
        raise
    registration_id = response["results"]["registration_id"]
    print(f'registered demo query q="pizza" -> {registration_id}')
    return registration_id


def sync_example() -> None:
    client, registration_id = _client_and_registration()

    # Iterate to receive matched news as it is published. Transient drops are
    # reconnected automatically; press Ctrl+C to stop. The context manager is
    # optional — it just closes the socket promptly when the block exits.
    with NewsDataApiWebSocket(client) as ws:
        for response in ws.stream(registration_id):
            for article in response["results"]:
                print(article.get("title"), "-", article.get("link"))


async def async_example() -> None:
    client, registration_id = _client_and_registration()

    # The async counterpart — same behavior, awaited iteration.
    async with NewsDataApiWebSocket(client) as ws:
        async for response in ws.stream_async(registration_id):
            for article in response["results"]:
                print(article.get("title"), "-", article.get("link"))


def main() -> None:
    try:
        if os.environ.get("NEWSDATA_WS_MODE") == "async":
            asyncio.run(async_example())
        else:
            sync_example()
    except NewsdataWebSocketAuthError as exc:
        # Permanent rejection: bad key, no WebSocket entitlement, unknown
        # registration_id, device limit, or exhausted quota.
        print(f"connection rejected: {exc}")
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
