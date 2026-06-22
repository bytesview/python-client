<div align="center">

[![NewsData.io logo](https://raw.githubusercontent.com/newsdataapi/python-client/main/newsdata-logo.png)](https://newsdata.io)

# NewsData.io Python Client

[![Build Status](https://img.shields.io/github/actions/workflow/status/newsdataapi/python-client/ci.yml)](https://github.com/newsdataapi/python-client/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-blue)](https://github.com/newsdataapi/python-client/blob/main/LICENSE)
[![PyPI](https://img.shields.io/pypi/v/newsdataapi?color=084298)](https://pypi.org/project/newsdataapi)
[![PyPI - Downloads](https://img.shields.io/pypi/dm/newsdataapi)](https://pypi.org/project/newsdataapi)
[![Supported Python versions](https://img.shields.io/pypi/pyversions/newsdataapi)](https://pypi.org/project/newsdataapi)
[![OpenAPI](https://img.shields.io/badge/OpenAPI-3.1-85EA2D)](https://newsdata.io/openapi.json)

</div>

`newsdataapi` is the official Python SDK for the [NewsData.io](https://newsdata.io) REST API. It wraps every endpoint (`latest`, `archive`, `sources`, `crypto`, `market`, `count`, `crypto/count`, `market/count`) with consistent retry, pagination, and error handling. It also includes a real-time WebSocket consumer (`NewsDataApiWebSocket`) for streaming matched news as it is published.

## Installation

```bash
pip install newsdataapi
```

If you use [uv](https://github.com/astral-sh/uv):

```bash
uv add newsdataapi
```

For real-time WebSocket streaming, install the optional `websocket` extra (requires Python 3.10+):

```bash
pip install "newsdataapi[websocket]"
```

Supports Python 3.8 through 3.14. The only runtime dependency is `requests`; the optional `websocket` extra adds `websockets`.

## Quickstart

```python
from newsdataapi import NewsDataApiClient

with NewsDataApiClient("YOUR_API_KEY") as client:
    response = client.latest_api(q="bitcoin", country="us", language="en")
    for article in response["results"]:
        print(article["title"], "-", article["link"])
```

The context-manager form closes the underlying HTTP session cleanly when the block exits. If you prefer not to use `with`, create the client directly and call `client.close()` yourself:

```python
from newsdataapi import NewsDataApiClient

client = NewsDataApiClient("YOUR_API_KEY")
try:
    response = client.latest_api(q="bitcoin", country="us", language="en")
    for article in response["results"]:
        print(article["title"], "-", article["link"])
finally:
    client.close()
```

## Endpoints

| Method | Endpoint | Notes |
|--------|----------|-------|
| `latest_api()` | `/latest` | Real-time news |
| `archive_api()` | `/archive` | Historical news |
| `sources_api()` | `/sources` | Available news sources |
| `crypto_api()` | `/crypto` | Cryptocurrency news |
| `market_api()` | `/market` | Market / financial news |
| `count_api(from_date, to_date)` | `/count` | Aggregate counts |
| `crypto_count_api(from_date, to_date)` | `/crypto/count` | Aggregate crypto counts |
| `market_count_api(from_date, to_date)` | `/market/count` | Aggregate market counts |

All endpoint parameters are keyword-only (except the required `from_date` / `to_date` on the count endpoints). Most accept either a single string or a `list[str]`; lists are comma-joined for the API.

See the [NewsData.io documentation](https://newsdata.io/documentation) — or the [OpenAPI 3.1 spec](https://newsdata.io/openapi.json) — for the full parameter reference.

## Three ways to consume an endpoint

```python
# 1. Single request (the default).
response = client.latest_api(q="news")

# 2. Auto-merge — follow nextPage cursors and return one combined dict.
merged = client.latest_api(q="news", scroll=True, max_result=200)

# 3. Iterate one response per page (a generator).
for page in client.latest_api(q="news", paginate=True, max_pages=5):
    process(page["results"])
```

`scroll` and `paginate` are mutually exclusive. `scroll=True` truncates strictly to `max_result`; `paginate=True` stops at `max_pages` or when the API returns no `nextPage`.

## Real-time news (WebSocket)

Stream the articles that match a registered percolator query as they are published. This needs the optional `websocket` extra (Python 3.10+):

```bash
pip install "newsdataapi[websocket]"
```

Pass your API key and a `registration_id` (the `doc_id` returned when the percolator query was registered), then iterate:

```python
from newsdataapi import NewsDataApiWebSocket

ws = NewsDataApiWebSocket(apikey, registration_id)
for article in ws:                      # or: for article in ws.stream()
    print(article["title"], "-", article["link"])
```

Use it as a context manager to close the connection promptly when you stop early (otherwise it closes when iteration ends):

```python
with NewsDataApiWebSocket(apikey, registration_id) as ws:
    for article in ws:
        print(article["title"])
        break
```

Transient drops (network errors, server restarts, abnormal closes) are reconnected automatically with a capped exponential backoff. Pass `reconnect=False` to stop on the first disconnect instead. A permanent rejection — bad API key, missing WebSocket entitlement, unknown `registration_id`, device limit reached, or exhausted quota — raises `NewsdataWebSocketAuthError` and is **not** retried:

```python
from newsdataapi import NewsdataWebSocketAuthError, NewsdataWebSocketError

try:
    for article in NewsDataApiWebSocket(apikey, registration_id):
        ...
except NewsdataWebSocketAuthError as e:
    print(f"rejected: {e}")
except NewsdataWebSocketError as e:
    print(f"stream error: {e}")
```

All connection options are keyword-only:

```python
ws = NewsDataApiWebSocket(
    apikey,
    registration_id,
    base_url="wss://newsdata.io/ws",  # override for staging / self-hosted / proxied
    reconnect=True,                   # auto-reconnect on transient drops; default True
    reconnect_delay=1.0,              # seconds before first reconnect (doubles each retry)
    reconnect_delay_max=30.0,         # cap on the reconnect delay
    open_timeout=10.0,                # handshake timeout (None disables)
    ping_interval=20.0,               # keepalive ping interval (None disables)
    ping_timeout=20.0,                # wait for ping reply before dropping (None disables)
    additional_headers={"X-Trace": "abc"},  # extra handshake headers
    proxy="http://host:port",         # proxy URL
)
```

## Error handling

```python
from newsdataapi import (
    NewsdataAPIError,
    NewsdataAuthError,
    NewsdataNetworkError,
    NewsdataRateLimitError,
)

try:
    client.latest_api(q="news")
except NewsdataAuthError as e:
    print(f"bad API key (HTTP {e.status_code})")
except NewsdataRateLimitError as e:
    print(f"rate limited; retry after {e.retry_after}s")
except NewsdataAPIError as e:
    print(f"API error {e.status_code}: {e.response_body}")
except NewsdataNetworkError as e:
    print(f"network failure: {e.original}")
```

The full hierarchy:

```
NewsdataException
├── NewsdataValidationError      (also a ValueError; carries .param)
├── NewsdataAPIError             (carries .status_code, .response_body)
│   ├── NewsdataAuthError        (401 / 403)
│   ├── NewsdataRateLimitError   (429; carries .retry_after)
│   └── NewsdataServerError      (5xx)
├── NewsdataNetworkError         (carries .original)
└── NewsdataWebSocketError       (real-time stream)
    └── NewsdataWebSocketAuthError  (handshake 401 / 403, or policy-violation close 1008)
```

`NewsdataException` is always a valid catch-all.

## Save results to CSV

```python
client.save_to_csv(response, folder_path="./out", filename="latest_news")

# Or set folder_path once on the client and reuse:
client = NewsDataApiClient(apikey, folder_path="./out")
client.save_to_csv(response, filename="latest_news")
```

`save_to_csv` returns a `pathlib.Path`. Cell values that are dicts or lists are stringified (`key:value,key:value` for dicts, comma-joined for lists). Quoting is delegated to the standard `csv.DictWriter`, so the output round-trips correctly through any CSV reader.

The function is also importable as a standalone:

```python
from newsdataapi import save_to_csv
save_to_csv(response, folder_path="./out", filename="latest_news")
```

## Configuration

```python
client = NewsDataApiClient(
    apikey="...",
    request_timeout=30,         # seconds; default 30
    max_retries=5,              # default 5
    retry_backoff=2.0,          # base seconds, exponential; default 2.0
    retry_backoff_max=60.0,     # cap on a single retry sleep; default 60.0
    pagination_delay=1.0,       # seconds between pages; default 1.0
    max_result=None,            # cap on merged results in scroll mode; default None (no cap)
    max_pages=None,             # cap on pages yielded in paginate mode; default None (no cap)
    proxies={"https": "..."},   # passed to requests.Session.get
    accept_language="en",       # Accept-Language header
    include_headers=False,      # if True, returned dicts include response_headers
    base_url="...",             # override for staging / proxied environments
    session=my_session,         # inject your own requests.Session
    folder_path="./out",        # default folder for save_to_csv; default None
)
```

Defaults sleep about a minute total across all retries (2 s → 4 s → 8 s → 16 s → 32 s, capped at 60 s); 429 responses honor `Retry-After` (both integer-seconds and HTTP-date forms are parsed). The API key is redacted in log output.

## Development

This project uses [uv](https://github.com/astral-sh/uv) for environment and lock management.

```bash
git clone https://github.com/newsdataapi/python-client
cd python-client
uv sync                                # creates .venv, installs runtime + dev deps from uv.lock
```

Run the suite:

```bash
uv run pytest                                         # unit tests only (default)
PYTEST_TOKEN=<api-key> uv run pytest -m integration   # live-API tests
PYTEST_TOKEN=<api-key> uv run pytest -m ""            # all tests

uv run ruff check src/ tests/ examples/
uv run mypy src/
```

Dev dependencies live in PEP 735 `[dependency-groups].dev` (uv-native). Plain `pip install -e ".[dev]"` will not pick them up; if you can't use uv, install the contents of the `dev` group in `pyproject.toml` by hand.

## Related libraries

Official Newsdata.io clients across languages and runtimes:

- **Node.js** — [newsdataapi/newsdata-nodejs-client](https://github.com/newsdataapi/newsdata-nodejs-client) ([npm](https://www.npmjs.com/package/newsdata-nodejs-client))
- **React (hooks)** — [newsdataapi/newsdata-reactjs-client](https://github.com/newsdataapi/newsdata-reactjs-client) ([npm](https://www.npmjs.com/package/newsdataapi))
- **PHP** — [newsdataapi/php-client](https://github.com/newsdataapi/php-client) ([Packagist](https://packagist.org/packages/newsdataio/newsdataapi))
- **Java** — [newsdataapi/newsdata-java-sdk](https://github.com/newsdataapi/newsdata-java-sdk) ([Maven Central](https://central.sonatype.com/artifact/io.newsdata/newsdataapi))
- **.NET** — [newsdataapi/newsdata-dotnet-sdk](https://github.com/newsdataapi/newsdata-dotnet-sdk) ([NuGet](https://www.nuget.org/packages/Newsdata.Api/))
- **Go** — [newsdataapi/newsdata-go-client](https://github.com/newsdataapi/newsdata-go-client) ([pkg.go.dev](https://pkg.go.dev/github.com/newsdataapi/newsdata-go-client))
- **Dart / Flutter** — [newsdataapi/newsdata-flutter-client](https://github.com/newsdataapi/newsdata-flutter-client) ([pub.dev](https://pub.dev/packages/newsdataapi))
- **MCP Server (AI assistants)** — [newsdataapi/newsdata.io-mcp](https://github.com/newsdataapi/newsdata.io-mcp) ([PyPI](https://pypi.org/project/newsdata-mcp/))

Also see [free news datasets](https://github.com/newsdataapi/newsdata.io-free-datasets) for ML / NLP work.

## License

MIT. See the [LICENSE](LICENSE) file.
