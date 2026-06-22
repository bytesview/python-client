"""Constants used by the :mod:`newsdataapi` client."""

from __future__ import annotations

# Base URL for the NewsData.io REST API. Must end with a slash so that
# ``urljoin(BASE_URL, "latest")`` produces the right URL.
BASE_URL = "https://newsdata.io/api/1/"

# Endpoint paths joined to ``BASE_URL`` to form the full request URL.
LATEST_ENDPOINT = "latest"
ARCHIVE_ENDPOINT = "archive"
SOURCES_ENDPOINT = "sources"
CRYPTO_ENDPOINT = "crypto"
MARKET_ENDPOINT = "market"
COUNT_ENDPOINT = "count"
CRYPTO_COUNT_ENDPOINT = "crypto/count"
MARKET_COUNT_ENDPOINT = "market/count"

# HTTP defaults.
DEFAULT_REQUEST_TIMEOUT = 30          # seconds
DEFAULT_MAX_RETRIES = 5
DEFAULT_RETRY_BACKOFF = 2.0           # base seconds; doubles each attempt
DEFAULT_RETRY_BACKOFF_MAX = 60.0      # cap on any single retry sleep
PAGINATION_DELAY = 1.0                # seconds slept between pages

# Real-time WebSocket endpoint (newsdataapi.NewsDataApiWebSocket).
WS_BASE_URL = "wss://newsdata.io/ws"
