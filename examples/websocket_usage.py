"""Real-time news streaming example for the newsdataapi SDK.

Requires the optional ``websocket`` extra (Python 3.10+)::

    pip install "newsdataapi[websocket]"

Run with::

    NEWSDATA_API_KEY=<key> NEWSDATA_REGISTRATION_ID=<id> \\
        python examples/websocket_usage.py

Set NEWSDATA_WS_MODE=async to run the asyncio example instead of the sync one.

The ``registration_id`` is the ``doc_id`` returned by the NewsData.io API when
you register a percolator query; the WebSocket streams the articles that match
it as they are published.
"""

from __future__ import annotations

import asyncio
import os

from newsdataapi import (
    NewsDataApiWebSocket,
    NewsDataApiWebSocketAsync,
    NewsdataWebSocketAuthError,
)


def _credentials() -> tuple[str, str]:
    apikey = os.environ.get("NEWSDATA_API_KEY")
    registration_id = os.environ.get("NEWSDATA_REGISTRATION_ID")
    if not apikey or not registration_id:
        raise SystemExit(
            "Set NEWSDATA_API_KEY and NEWSDATA_REGISTRATION_ID in your "
            "environment before running this example."
        )
    return apikey, registration_id


def sync_example() -> None:
    apikey, registration_id = _credentials()
    ws = NewsDataApiWebSocket(apikey, registration_id)

    # Iterate to receive matched articles as they arrive. Transient drops are
    # reconnected automatically; press Ctrl+C to stop. The context manager is
    # optional — it just closes the socket promptly when the block exits.
    with ws:
        for article in ws:
            print(article.get("title"), "-", article.get("link"))


async def async_example() -> None:
    apikey, registration_id = _credentials()
    ws = NewsDataApiWebSocketAsync(apikey, registration_id)

    # The async counterpart — same behavior, awaited iteration.
    async with ws:
        async for article in ws:
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
