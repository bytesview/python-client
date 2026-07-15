"""HTTP client for the NewsData.io REST API."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterator, Mapping
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlparse, urlunparse

import requests
from requests.exceptions import RequestException

from . import constants, csv_export
from .exceptions import (
    NewsdataAPIError,
    NewsdataAuthError,
    NewsdataException,
    NewsdataNetworkError,
    NewsdataRateLimitError,
    NewsdataServerError,
    NewsdataValidationError,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Parameter validation.
# ---------------------------------------------------------------------------

_BOOL_PARAMS = frozenset({"full_content", "image", "video", "removeduplicate"})
_INT_PARAMS = frozenset({"size"})
_FLOAT_PARAMS = frozenset({"sentiment_score"})
_STRING_PARAMS = frozenset(
    {
        "q",
        "qInTitle",
        "qInMeta",
        "country",
        "category",
        "language",
        "domain",
        "domainurl",
        "excludedomain",
        "timezone",
        "from_date",
        "to_date",
        "prioritydomain",
        "timeframe",
        "tag",
        "sentiment",
        "region",
        "coin",
        "excludefield",
        "excludecategory",
        "id",
        "excludelanguage",
        "organization",
        "url",
        "sort",
        "symbol",
        "market_id",
        "excludecountry",
        "page",
        "interval",
        "creator",
        "datatype",
    }
)

# Filter pairs / groups that the server rejects with HTTP 422 when more than
# one is set. Mirrored on the client to fail fast and avoid a wasted round
# trip. Order within each tuple defines which name shows up as
# ``NewsdataValidationError.param`` when the conflict is detected.
_MUTEX_GROUPS: tuple[tuple[str, ...], ...] = (
    ("q", "qInTitle", "qInMeta"),
    ("country", "excludecountry"),
    ("category", "excludecategory"),
    ("language", "excludelanguage"),
    ("domain", "domainurl", "excludedomain"),
)


def _validate_params(user_params: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize user-provided endpoint parameters.

    * ``None`` values are dropped.
    * Lists are joined into comma-separated strings (after element-wise
      string check).
    * Booleans for known bool params become ``1`` / ``0``.
    * Integer params are checked for type (rejecting ``bool``, which would
      otherwise pass ``isinstance(x, int)``).
    * ``raw_query`` is mutually exclusive with all other endpoint params:
      passing any other non-None param alongside ``raw_query`` raises
      ``NewsdataValidationError``. When set alone, the query string is
      parsed and validated against the calling method's keyset.
    * Server-side mutex groups (``q``/``qInTitle``/``qInMeta``,
      ``country``/``excludecountry``, ``category``/``excludecategory``,
      ``language``/``excludelanguage``, and
      ``domain``/``domainurl``/``excludedomain``) are enforced client-side;
      setting more than one from any group raises
      ``NewsdataValidationError`` before the request leaves.
    * ``sentiment_score`` requires ``sentiment`` to be set; passing
      ``sentiment_score`` alone raises ``NewsdataValidationError``.

    Raises:
        NewsdataValidationError: On any type mismatch, unknown raw_query
            parameter, raw_query combined with other endpoint params, or
            mutually-exclusive params set together.
    """
    raw_query = user_params.get("raw_query")
    if raw_query is not None:
        conflicting = sorted(
            k for k, v in user_params.items()
            if k != "raw_query" and v is not None
        )
        if conflicting:
            raise NewsdataValidationError(
                "raw_query cannot be combined with other endpoint "
                f"parameters; got both raw_query and {conflicting}",
                param="raw_query",
            )
        return _parse_raw_query(raw_query, allowed_keys=set(user_params.keys()))

    for group in _MUTEX_GROUPS:
        set_in_group = [k for k in group if user_params.get(k) is not None]
        if len(set_in_group) > 1:
            raise NewsdataValidationError(
                f"these parameters are mutually exclusive: {set_in_group}",
                param=set_in_group[0],
            )

    if (
        user_params.get("sentiment_score") is not None
        and user_params.get("sentiment") is None
    ):
        raise NewsdataValidationError(
            "sentiment_score requires sentiment to be set",
            param="sentiment_score",
        )

    validated: dict[str, Any] = {}
    for param, value in user_params.items():
        if value is None or param == "raw_query":
            continue

        if param in _STRING_PARAMS:
            value = _coerce_string_param(param, value)
        elif param in _BOOL_PARAMS:
            value = _coerce_bool_param(param, value)
        elif param in _INT_PARAMS:
            _check_int_param(param, value)
        elif param in _FLOAT_PARAMS:
            _check_float_param(param, value)
        # else: unknown param — pass through unmodified. Endpoint methods
        # restrict kwargs at the signature level.

        validated[param] = value

    return validated


def _coerce_string_param(param: str, value: Any) -> str:
    if isinstance(value, list):
        if not all(isinstance(item, str) for item in value):
            raise NewsdataValidationError(
                f"All items in {param!r} must be strings",
                param=param,
            )
        return ",".join(value)
    if not isinstance(value, str):
        raise NewsdataValidationError(
            f"{param!r} must be a string or list of strings, "
            f"got {type(value).__name__}",
            param=param,
        )
    return value


def _coerce_bool_param(param: str, value: Any) -> int:
    if not isinstance(value, bool):
        raise NewsdataValidationError(
            f"{param!r} must be a bool, got {type(value).__name__}",
            param=param,
        )
    return 1 if value else 0


def _check_int_param(param: str, value: Any) -> None:
    # ``bool`` is a subclass of ``int`` in Python, so the obvious
    # ``isinstance(value, int)`` would silently accept ``True`` / ``False``.
    if isinstance(value, bool) or not isinstance(value, int):
        raise NewsdataValidationError(
            f"{param!r} must be an int, got {type(value).__name__}",
            param=param,
        )
    if param == "size" and (value > 50 or value < 1):
        raise NewsdataValidationError(
            f"size must be between 1 and 50 (got {value})",
            param="size",
        )


def _check_float_param(param: str, value: Any) -> None:
    # Accept both int and float. ``bool`` is a subclass of ``int`` and
    # would otherwise be silently accepted; reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NewsdataValidationError(
            f"{param!r} must be a number (int or float), got {type(value).__name__}",
            param=param,
        )


def _parse_raw_query(raw_query: Any, *, allowed_keys: set[str]) -> dict[str, Any]:
    """Parse a ``raw_query`` value into a validated param dict.

    ``raw_query`` may be either a query-string fragment (``"q=foo&country=us"``,
    optionally prefixed with ``?``) or a full URL.
    """
    if not isinstance(raw_query, str):
        raise NewsdataValidationError(
            f"raw_query must be a string, got {type(raw_query).__name__}",
            param="raw_query",
        )
    if not raw_query:
        raise NewsdataValidationError(
            "raw_query must be a non-empty string",
            param="raw_query",
        )

    parsed = urlparse(raw_query)
    if parsed.netloc:
        query_string = parse_qs(parsed.query, keep_blank_values=True)
    else:
        query_string = parse_qs(raw_query.lstrip("?"), keep_blank_values=True)

    allowed_lower = {key.lower() for key in allowed_keys}
    result: dict[str, Any] = {}
    for key, values in query_string.items():
        normalized = key.strip().lstrip("?").lower()
        if not normalized:
            continue
        if normalized == "apikey":
            # apikey is supplied from the client constructor; ignore
            # any apikey embedded in raw_query.
            continue
        if normalized not in allowed_lower:
            raise NewsdataValidationError(
                f"Unknown parameter in raw_query: {key!r}",
                param=key,
            )
        if not values or not values[0]:
            raise NewsdataValidationError(
                f"Parameter {key!r} must have a value",
                param=key,
            )
        result[normalized] = values[0]
    return result


def _parse_retry_after(value: str | None) -> int | None:
    """Parse a ``Retry-After`` header value into seconds.

    RFC 7231 allows two forms:

    * an integer number of seconds, or
    * an HTTP-date.

    Returns ``None`` for unparseable input so callers can fall back to
    their own backoff strategy.
    """
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None

    # Form 1: integer seconds.
    try:
        seconds = int(value)
    except ValueError:
        pass
    else:
        return max(seconds, 0)

    # Form 2: HTTP-date.
    try:
        target = parsedate_to_datetime(value)
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        delta_seconds = (target - datetime.now(tz=timezone.utc)).total_seconds()
        return max(int(delta_seconds), 0)
    except (TypeError, ValueError, AttributeError):
        return None


def _redact_url(url: str, param: str = "apikey") -> str:
    """Return ``url`` with the value of ``param`` replaced by ``REDACTED``.

    Used to keep credentials out of log messages.
    """
    parsed = urlparse(url)
    pairs: list[tuple[str, str]] = []
    for key, values in parse_qs(parsed.query, keep_blank_values=True).items():
        if key == param:
            pairs.append((key, "REDACTED"))
        else:
            pairs.extend((key, value) for value in values)
    return urlunparse(parsed._replace(query=urlencode(pairs)))


# ---------------------------------------------------------------------------
# Client.
# ---------------------------------------------------------------------------


class NewsDataApiClient:
    """Synchronous HTTP client for the NewsData.io REST API.

    Example::

        with NewsDataApiClient("YOUR_API_KEY") as client:
            response = client.latest_api(q="bitcoin", country="us")

    The client owns a single :class:`requests.Session` for connection
    pooling. Pass ``session=...`` to inject your own (it will not be closed
    by the client). Use the context manager (``with``) form, or call
    :meth:`close` explicitly, to release the session.

    All endpoint parameters are keyword-only except for the required
    ``from_date`` / ``to_date`` on the count endpoints. Most parameters
    accept either a single string or a ``list[str]``; lists are
    comma-joined before being sent to the API.
    """

    proxies: dict[str, Any] | None
    max_retries: int
    retry_backoff: float
    retry_backoff_max: float
    request_timeout: float
    pagination_delay: float
    max_result: int | None
    max_pages: int | None
    include_headers: bool
    accept_language: str
    folder_path: str | os.PathLike[str] | None

    def __init__(
        self,
        apikey: str,
        *,
        session: requests.Session | None = None,
        proxies: dict[str, Any] | None = None,
        max_retries: int = constants.DEFAULT_MAX_RETRIES,
        retry_backoff: float = constants.DEFAULT_RETRY_BACKOFF,
        retry_backoff_max: float = constants.DEFAULT_RETRY_BACKOFF_MAX,
        request_timeout: float = constants.DEFAULT_REQUEST_TIMEOUT,
        pagination_delay: float = constants.PAGINATION_DELAY,
        max_result: int | None = None,
        max_pages: int | None = None,
        include_headers: bool = False,
        accept_language: str = "en",
        base_url: str = constants.BASE_URL,
        folder_path: str | os.PathLike[str] | None = None,
    ) -> None:
        if not isinstance(apikey, str) or not apikey:
            raise NewsdataValidationError(
                "apikey must be a non-empty string",
                param="apikey",
            )

        # API key is stored privately so it doesn't appear in repr() or
        # casual attribute introspection.
        self._apikey = apikey
        self._session = session if session is not None else requests.Session()
        self._owns_session = session is None
        self._closed = False

        self.proxies = proxies
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.retry_backoff_max = retry_backoff_max
        self.request_timeout = request_timeout
        self.pagination_delay = pagination_delay
        self.max_result = max_result
        self.max_pages = max_pages
        self.include_headers = include_headers
        self.accept_language = accept_language
        self.folder_path = folder_path

        self._base_url = base_url if base_url.endswith("/") else base_url + "/"
        logger.debug(
            "NewsDataApiClient initialized (base_url=%s, max_retries=%d)",
            self._base_url,
            self.max_retries,
        )

    # ---- context-manager / lifetime --------------------------------------

    def __enter__(self) -> NewsDataApiClient:
        return self

    def __exit__(
        self,
        exc_type: object,
        exc: object,
        tb: object,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP session if this client owns it.

        Safe to call multiple times. Sessions injected via ``session=...``
        are *not* closed (the caller owns them).
        """
        if self._closed or not self._owns_session:
            return
        self._session.close()
        self._closed = True

    def __del__(self) -> None:
        # Best-effort cleanup. Don't fail on partially-initialised objects
        # or during interpreter shutdown.
        try:
            if not getattr(self, "_closed", True) and getattr(
                self, "_owns_session", False
            ):
                session = getattr(self, "_session", None)
                if session is not None:
                    session.close()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass

    # ---- configuration ---------------------------------------------------

    def set_base_url(self, new_base_url: str) -> None:
        """Override the base URL (e.g. for a staging or proxied environment).

        The new URL is normalized to end with a trailing slash so that
        :func:`urllib.parse.urljoin` resolves endpoint paths correctly.
        """
        if not isinstance(new_base_url, str) or not new_base_url:
            raise ValueError("base_url must be a non-empty string")
        self._base_url = (
            new_base_url if new_base_url.endswith("/") else new_base_url + "/"
        )

    # ---- endpoint methods ------------------------------------------------

    def latest_api(
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
        timeframe: int | str | None = None,
        timezone: str | None = None,
        size: int | None = None,
        full_content: bool | None = None,
        image: bool | None = None,
        video: bool | None = None,
        page: str | None = None,
        tag: str | list[str] | None = None,
        sentiment: str | None = None,
        region: str | list[str] | None = None,
        excludefield: str | list[str] | None = None,
        removeduplicate: bool | None = None,
        id: str | list[str] | None = None,
        organization: str | list[str] | None = None,
        url: str | None = None,
        sort: str | None = None,
        creator: str | list[str] | None = None,
        datatype: str | list[str] | None = None,
        sentiment_score: float | None = None,
        raw_query: str | None = None,
        scroll: bool = False,
        paginate: bool = False,
        max_result: int | None = None,
        max_pages: int | None = None,
    ) -> dict[str, Any] | Iterator[dict[str, Any]]:
        """Fetch latest news.

        See https://newsdata.io/documentation for parameter descriptions.

        Returns a dict by default, the merged dict if ``scroll=True``, or
        an iterator of per-page dicts if ``paginate=True``.
        """
        return self._dispatch(
            constants.LATEST_ENDPOINT,
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
                "timeframe": str(timeframe) if timeframe is not None else None,
                "timezone": timezone,
                "size": size,
                "full_content": full_content,
                "image": image,
                "video": video,
                "page": page,
                "tag": tag,
                "sentiment": sentiment,
                "region": region,
                "excludefield": excludefield,
                "removeduplicate": removeduplicate,
                "id": id,
                "organization": organization,
                "url": url,
                "sort": sort,
                "creator": creator,
                "datatype": datatype,
                "sentiment_score": sentiment_score,
                "raw_query": raw_query,
            },
            scroll=scroll,
            paginate=paginate,
            max_result=max_result,
            max_pages=max_pages,
        )

    def archive_api(
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
        size: int | None = None,
        full_content: bool | None = None,
        image: bool | None = None,
        video: bool | None = None,
        page: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        excludefield: str | list[str] | None = None,
        id: str | list[str] | None = None,
        url: str | None = None,
        sort: str | None = None,
        tag: str | list[str] | None = None,
        sentiment: str | None = None,
        sentiment_score: float | None = None,
        region: str | list[str] | None = None,
        organization: str | list[str] | None = None,
        creator: str | list[str] | None = None,
        datatype: str | list[str] | None = None,
        removeduplicate: bool | None = None,
        raw_query: str | None = None,
        scroll: bool = False,
        paginate: bool = False,
        max_result: int | None = None,
        max_pages: int | None = None,
    ) -> dict[str, Any] | Iterator[dict[str, Any]]:
        """Fetch news from the archive.

        See https://newsdata.io/documentation for parameter descriptions.
        """
        return self._dispatch(
            constants.ARCHIVE_ENDPOINT,
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
                "size": size,
                "full_content": full_content,
                "image": image,
                "video": video,
                "page": page,
                "from_date": from_date,
                "to_date": to_date,
                "excludefield": excludefield,
                "id": id,
                "url": url,
                "sort": sort,
                "tag": tag,
                "sentiment": sentiment,
                "sentiment_score": sentiment_score,
                "region": region,
                "organization": organization,
                "creator": creator,
                "datatype": datatype,
                "removeduplicate": removeduplicate,
                "raw_query": raw_query,
            },
            scroll=scroll,
            paginate=paginate,
            max_result=max_result,
            max_pages=max_pages,
        )

    def sources_api(
        self,
        *,
        country: str | list[str] | None = None,
        category: str | list[str] | None = None,
        language: str | list[str] | None = None,
        prioritydomain: str | None = None,
        domainurl: str | list[str] | None = None,
        raw_query: str | None = None,
    ) -> dict[str, Any]:
        """List available news sources.

        Sources is a single-page endpoint; ``scroll`` and ``paginate`` are
        not supported.
        """
        params = _validate_params(
            {
                "country": country,
                "category": category,
                "language": language,
                "prioritydomain": prioritydomain,
                "domainurl": domainurl,
                "raw_query": raw_query,
            }
        )
        return self._request(constants.SOURCES_ENDPOINT, params)

    def crypto_api(
        self,
        *,
        q: str | None = None,
        qInTitle: str | None = None,
        qInMeta: str | None = None,
        language: str | list[str] | None = None,
        excludelanguage: str | list[str] | None = None,
        domain: str | list[str] | None = None,
        domainurl: str | list[str] | None = None,
        excludedomain: str | list[str] | None = None,
        prioritydomain: str | None = None,
        timeframe: int | str | None = None,
        timezone: str | None = None,
        size: int | None = None,
        full_content: bool | None = None,
        image: bool | None = None,
        video: bool | None = None,
        page: str | None = None,
        tag: str | list[str] | None = None,
        sentiment: str | None = None,
        coin: str | list[str] | None = None,
        excludefield: str | list[str] | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        removeduplicate: bool | None = None,
        id: str | list[str] | None = None,
        url: str | None = None,
        sort: str | None = None,
        raw_query: str | None = None,
        scroll: bool = False,
        paginate: bool = False,
        max_result: int | None = None,
        max_pages: int | None = None,
    ) -> dict[str, Any] | Iterator[dict[str, Any]]:
        """Fetch cryptocurrency news.

        See https://newsdata.io/documentation for parameter descriptions.
        """
        return self._dispatch(
            constants.CRYPTO_ENDPOINT,
            {
                "q": q,
                "qInTitle": qInTitle,
                "qInMeta": qInMeta,
                "language": language,
                "excludelanguage": excludelanguage,
                "domain": domain,
                "domainurl": domainurl,
                "excludedomain": excludedomain,
                "prioritydomain": prioritydomain,
                "timeframe": str(timeframe) if timeframe is not None else None,
                "timezone": timezone,
                "size": size,
                "full_content": full_content,
                "image": image,
                "video": video,
                "page": page,
                "tag": tag,
                "sentiment": sentiment,
                "coin": coin,
                "excludefield": excludefield,
                "from_date": from_date,
                "to_date": to_date,
                "removeduplicate": removeduplicate,
                "id": id,
                "url": url,
                "sort": sort,
                "raw_query": raw_query,
            },
            scroll=scroll,
            paginate=paginate,
            max_result=max_result,
            max_pages=max_pages,
        )

    def market_api(
        self,
        *,
        q: str | None = None,
        qInTitle: str | None = None,
        qInMeta: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        country: str | list[str] | None = None,
        excludecountry: str | list[str] | None = None,
        domain: str | list[str] | None = None,
        domainurl: str | list[str] | None = None,
        excludedomain: str | list[str] | None = None,
        language: str | list[str] | None = None,
        excludelanguage: str | list[str] | None = None,
        prioritydomain: str | None = None,
        timezone: str | None = None,
        timeframe: int | str | None = None,
        size: int | None = None,
        full_content: bool | None = None,
        image: bool | None = None,
        video: bool | None = None,
        page: str | None = None,
        tag: str | list[str] | None = None,
        sentiment: str | None = None,
        excludefield: str | list[str] | None = None,
        removeduplicate: bool | None = None,
        organization: str | list[str] | None = None,
        symbol: str | list[str] | None = None,
        market_id: str | list[str] | None = None,
        id: str | list[str] | None = None,
        url: str | None = None,
        sort: str | None = None,
        creator: str | list[str] | None = None,
        datatype: str | list[str] | None = None,
        sentiment_score: float | None = None,
        raw_query: str | None = None,
        scroll: bool = False,
        paginate: bool = False,
        max_result: int | None = None,
        max_pages: int | None = None,
    ) -> dict[str, Any] | Iterator[dict[str, Any]]:
        """Fetch market / financial news.

        See https://newsdata.io/documentation for parameter descriptions.
        """
        return self._dispatch(
            constants.MARKET_ENDPOINT,
            {
                "q": q,
                "qInTitle": qInTitle,
                "qInMeta": qInMeta,
                "from_date": from_date,
                "to_date": to_date,
                "country": country,
                "excludecountry": excludecountry,
                "domain": domain,
                "domainurl": domainurl,
                "excludedomain": excludedomain,
                "language": language,
                "excludelanguage": excludelanguage,
                "prioritydomain": prioritydomain,
                "timezone": timezone,
                "timeframe": str(timeframe) if timeframe is not None else None,
                "size": size,
                "full_content": full_content,
                "image": image,
                "video": video,
                "page": page,
                "tag": tag,
                "sentiment": sentiment,
                "excludefield": excludefield,
                "removeduplicate": removeduplicate,
                "organization": organization,
                "symbol": symbol,
                "market_id": market_id,
                "id": id,
                "url": url,
                "sort": sort,
                "creator": creator,
                "datatype": datatype,
                "sentiment_score": sentiment_score,
                "raw_query": raw_query,
            },
            scroll=scroll,
            paginate=paginate,
            max_result=max_result,
            max_pages=max_pages,
        )

    def count_api(
        self,
        from_date: str,
        to_date: str,
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
        full_content: bool | None = None,
        image: bool | None = None,
        video: bool | None = None,
        prioritydomain: str | None = None,
        page: str | None = None,
        size: int | None = None,
        sort: str | None = None,
        interval: str | None = None,
        tag: str | list[str] | None = None,
        sentiment: str | None = None,
        sentiment_score: float | None = None,
        region: str | list[str] | None = None,
        organization: str | list[str] | None = None,
        creator: str | list[str] | None = None,
        datatype: str | list[str] | None = None,
        removeduplicate: bool | None = None,
        raw_query: str | None = None,
        scroll: bool = False,
        paginate: bool = False,
        max_result: int | None = None,
        max_pages: int | None = None,
    ) -> dict[str, Any] | Iterator[dict[str, Any]]:
        """Fetch aggregate counts of news for a date range.

        ``from_date`` and ``to_date`` are required. Returns a dict by
        default, the merged dict if ``scroll=True`` (concatenates per-bucket
        rows from every page; the final aggregate dict, if any, is captured
        under the ``aggregate`` key of the merged response), or an iterator
        of per-page dicts if ``paginate=True``.
        """
        return self._dispatch(
            constants.COUNT_ENDPOINT,
            {
                "from_date": from_date,
                "to_date": to_date,
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
                "full_content": full_content,
                "image": image,
                "video": video,
                "prioritydomain": prioritydomain,
                "page": page,
                "size": size,
                "sort": sort,
                "interval": interval,
                "tag": tag,
                "sentiment": sentiment,
                "sentiment_score": sentiment_score,
                "region": region,
                "organization": organization,
                "creator": creator,
                "datatype": datatype,
                "removeduplicate": removeduplicate,
                "raw_query": raw_query,
            },
            scroll=scroll,
            paginate=paginate,
            max_result=max_result,
            max_pages=max_pages,
            is_count=True,
        )

    def crypto_count_api(
        self,
        from_date: str,
        to_date: str,
        *,
        q: str | None = None,
        qInTitle: str | None = None,
        qInMeta: str | None = None,
        language: str | list[str] | None = None,
        excludelanguage: str | list[str] | None = None,
        coin: str | list[str] | None = None,
        domain: str | list[str] | None = None,
        domainurl: str | list[str] | None = None,
        excludedomain: str | list[str] | None = None,
        full_content: bool | None = None,
        image: bool | None = None,
        video: bool | None = None,
        prioritydomain: str | None = None,
        page: str | None = None,
        sentiment: str | None = None,
        size: int | None = None,
        sort: str | None = None,
        tag: str | list[str] | None = None,
        interval: str | None = None,
        removeduplicate: bool | None = None,
        raw_query: str | None = None,
        scroll: bool = False,
        paginate: bool = False,
        max_result: int | None = None,
        max_pages: int | None = None,
    ) -> dict[str, Any] | Iterator[dict[str, Any]]:
        """Fetch aggregate counts of crypto news for a date range.

        ``from_date`` and ``to_date`` are required. Returns a dict by
        default, the merged dict if ``scroll=True`` (final aggregate dict,
        if any, captured under ``aggregate`` key), or an iterator of
        per-page dicts if ``paginate=True``.
        """
        return self._dispatch(
            constants.CRYPTO_COUNT_ENDPOINT,
            {
                "from_date": from_date,
                "to_date": to_date,
                "q": q,
                "qInTitle": qInTitle,
                "qInMeta": qInMeta,
                "language": language,
                "excludelanguage": excludelanguage,
                "coin": coin,
                "domain": domain,
                "domainurl": domainurl,
                "excludedomain": excludedomain,
                "full_content": full_content,
                "image": image,
                "video": video,
                "prioritydomain": prioritydomain,
                "page": page,
                "sentiment": sentiment,
                "size": size,
                "sort": sort,
                "tag": tag,
                "interval": interval,
                "removeduplicate": removeduplicate,
                "raw_query": raw_query,
            },
            scroll=scroll,
            paginate=paginate,
            max_result=max_result,
            max_pages=max_pages,
            is_count=True,
        )

    def market_count_api(
        self,
        from_date: str,
        to_date: str,
        *,
        q: str | None = None,
        qInTitle: str | None = None,
        qInMeta: str | None = None,
        country: str | list[str] | None = None,
        excludecountry: str | list[str] | None = None,
        domain: str | list[str] | None = None,
        domainurl: str | list[str] | None = None,
        excludedomain: str | list[str] | None = None,
        language: str | list[str] | None = None,
        excludelanguage: str | list[str] | None = None,
        full_content: bool | None = None,
        image: bool | None = None,
        video: bool | None = None,
        organization: str | list[str] | None = None,
        symbol: str | list[str] | None = None,
        market_id: str | list[str] | None = None,
        prioritydomain: str | None = None,
        page: str | None = None,
        sentiment: str | None = None,
        removeduplicate: bool | None = None,
        size: int | None = None,
        sort: str | None = None,
        tag: str | list[str] | None = None,
        interval: str | None = None,
        creator: str | list[str] | None = None,
        datatype: str | list[str] | None = None,
        sentiment_score: float | None = None,
        raw_query: str | None = None,
        scroll: bool = False,
        paginate: bool = False,
        max_result: int | None = None,
        max_pages: int | None = None,
    ) -> dict[str, Any] | Iterator[dict[str, Any]]:
        """Fetch aggregate counts of market news for a date range.

        ``from_date`` and ``to_date`` are required. Returns a dict by
        default, the merged dict if ``scroll=True`` (final aggregate dict,
        if any, captured under ``aggregate`` key), or an iterator of
        per-page dicts if ``paginate=True``.
        """
        return self._dispatch(
            constants.MARKET_COUNT_ENDPOINT,
            {
                "from_date": from_date,
                "to_date": to_date,
                "q": q,
                "qInTitle": qInTitle,
                "qInMeta": qInMeta,
                "country": country,
                "excludecountry": excludecountry,
                "domain": domain,
                "domainurl": domainurl,
                "excludedomain": excludedomain,
                "language": language,
                "excludelanguage": excludelanguage,
                "full_content": full_content,
                "image": image,
                "video": video,
                "organization": organization,
                "symbol": symbol,
                "market_id": market_id,
                "prioritydomain": prioritydomain,
                "page": page,
                "sentiment": sentiment,
                "removeduplicate": removeduplicate,
                "size": size,
                "sort": sort,
                "tag": tag,
                "interval": interval,
                "creator": creator,
                "datatype": datatype,
                "sentiment_score": sentiment_score,
                "raw_query": raw_query,
            },
            scroll=scroll,
            paginate=paginate,
            max_result=max_result,
            max_pages=max_pages,
            is_count=True,
        )

    # ---- CSV export convenience -----------------------------------------

    def save_to_csv(
        self,
        response: Mapping[str, Any],
        folder_path: str | os.PathLike[str] | None = None,
        filename: str | None = None,
        *,
        overwrite: bool = False,
    ) -> Path:
        """Write ``response['results']`` to a CSV file.

        Thin wrapper around :func:`newsdataapi.csv_export.save_to_csv` that
        falls back to ``self.folder_path`` (set in the constructor) when
        ``folder_path`` is omitted at the call site.
        """
        target = folder_path if folder_path is not None else self.folder_path
        if target is None:
            raise ValueError(
                "folder_path must be provided either at call time or via "
                "the client constructor"
            )
        return csv_export.save_to_csv(response, target, filename, overwrite=overwrite)

    # ---- internals -------------------------------------------------------

    def _dispatch(
        self,
        endpoint: str,
        params: Mapping[str, Any],
        *,
        scroll: bool = False,
        paginate: bool = False,
        max_result: int | None = None,
        max_pages: int | None = None,
        is_count: bool = False,
    ) -> dict[str, Any] | Iterator[dict[str, Any]]:
        """Validate ``params`` and route to single / scroll / paginate execution."""
        if scroll and paginate:
            raise ValueError("scroll and paginate are mutually exclusive")
        validated = _validate_params(params)
        if scroll:
            return self._scroll_all(endpoint, validated, max_result, is_count=is_count)
        if paginate:
            return self._paginate(endpoint, validated, max_pages, is_count=is_count)
        return self._request(endpoint, validated)

    def _request(
        self,
        endpoint: str,
        params: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Execute a single GET request, with retries.

        Returns the parsed JSON body on success. Raises a
        :class:`NewsdataException` subclass on permanent failure.
        """
        url = self._endpoint_url(endpoint)

        for attempt in range(1, self.max_retries + 1):
            request_params = dict(params)
            request_params["apikey"] = self._apikey
            full_url = f"{url}?{urlencode(request_params, quote_via=quote)}"

            t0 = time.perf_counter()
            try:
                logger.info("GET %s", _redact_url(full_url))
                response = self._session.get(
                    full_url,
                    proxies=self.proxies,
                    timeout=self.request_timeout,
                    headers={"Accept-Language": self.accept_language},
                )
            except RequestException as exc:
                if attempt >= self.max_retries:
                    raise NewsdataNetworkError(
                        f"Network error after {self.max_retries} attempts: {exc}",
                        original=exc,
                    ) from exc
                logger.warning(
                    "Network error on attempt %d/%d: %s",
                    attempt,
                    self.max_retries,
                    exc,
                )
                self._sleep_for_retry(attempt)
                continue

            elapsed = time.perf_counter() - t0
            logger.debug(
                "%d %s (%.2fs) X-API-Limit-Remaining=%s",
                response.status_code,
                response.reason,
                elapsed,
                response.headers.get("X-API-Limit-Remaining"),
            )

            try:
                body: Any = response.json()
            except ValueError as exc:
                # Non-JSON body. Retry on 5xx; fail immediately on 2xx/4xx.
                if response.status_code >= 500 and attempt < self.max_retries:
                    logger.warning(
                        "Non-JSON response (status %d) on attempt %d/%d",
                        response.status_code,
                        attempt,
                        self.max_retries,
                    )
                    self._sleep_for_retry(attempt)
                    continue
                raise NewsdataAPIError(
                    f"Non-JSON response from API (status {response.status_code})",
                    status_code=response.status_code,
                ) from exc

            # Success: 200 + status=success + non-null results.
            if (
                response.status_code == 200
                and isinstance(body, dict)
                and body.get("status") == "success"
                and body.get("results") is not None
            ):
                if self.include_headers:
                    body["response_headers"] = dict(response.headers)
                return body

            # Rate limit.
            if response.status_code == 429:
                retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                if attempt >= self.max_retries:
                    raise NewsdataRateLimitError(
                        body,
                        status_code=429,
                        response_body=body if isinstance(body, dict) else None,
                        retry_after=retry_after,
                    )
                sleep_for = (
                    retry_after
                    if retry_after is not None
                    else self._compute_backoff(attempt)
                )
                logger.warning(
                    "429 rate limit (attempt %d/%d); sleeping %.1fs",
                    attempt,
                    self.max_retries,
                    sleep_for,
                )
                time.sleep(sleep_for)
                continue

            # Server error.
            if response.status_code >= 500:
                if attempt >= self.max_retries:
                    raise NewsdataServerError(
                        body,
                        status_code=response.status_code,
                        response_body=body if isinstance(body, dict) else None,
                    )
                logger.warning(
                    "%d server error (attempt %d/%d)",
                    response.status_code,
                    attempt,
                    self.max_retries,
                )
                self._sleep_for_retry(attempt)
                continue

            # Auth error — never retry.
            if response.status_code in (401, 403):
                raise NewsdataAuthError(
                    body,
                    status_code=response.status_code,
                    response_body=body if isinstance(body, dict) else None,
                )

            # Other 4xx — never retry.
            raise NewsdataAPIError(
                body,
                status_code=response.status_code,
                response_body=body if isinstance(body, dict) else None,
            )

        # Defensive: the loop always either returns or raises. This is
        # reachable only if max_retries < 1, which is a programming error.
        raise NewsdataException(
            f"Request to {endpoint} did not produce a result "
            f"(max_retries={self.max_retries})"
        )

    def _scroll_all(
        self,
        endpoint: str,
        params: Mapping[str, Any],
        max_result: int | None,
        *,
        is_count: bool = False,
    ) -> dict[str, Any]:
        """Follow ``nextPage`` cursors and return one merged response.

        For news endpoints, concatenates list-form ``results`` from every
        page. For count endpoints (``is_count=True``), additionally captures
        the final aggregate dict — when the API returns ``results`` as a
        dict on the final page — under the ``aggregate`` key of the merged
        response.
        """
        if max_result is None:
            max_result = self.max_result

        accumulated: list[dict[str, Any]] = []
        request_params: dict[str, Any] = dict(params)
        total_results: Any = None
        last_headers: dict[str, str] | None = None
        next_page: Any = None
        aggregate: dict[str, Any] | None = None

        while True:
            response = self._request(endpoint, request_params)
            total_results = response.get("totalResults", total_results)
            page_results = response.get("results", [])
            if isinstance(page_results, list):
                accumulated.extend(page_results)
            elif is_count and isinstance(page_results, dict):
                aggregate = page_results
            if self.include_headers:
                last_headers = response.get("response_headers")
            next_page = response.get("nextPage")

            if max_result is not None and len(accumulated) >= max_result:
                accumulated = accumulated[:max_result]
                next_page = None
                break
            if not next_page:
                break

            request_params["page"] = next_page
            time.sleep(self.pagination_delay)

        merged: dict[str, Any] = {
            "totalResults": total_results,
            "results": accumulated,
            "nextPage": next_page,
        }
        if aggregate is not None:
            merged["aggregate"] = aggregate
        if last_headers is not None:
            merged["response_headers"] = last_headers
        return merged

    def _paginate(
        self,
        endpoint: str,
        params: Mapping[str, Any],
        max_pages: int | None,
        *,
        is_count: bool = False,
    ) -> Iterator[dict[str, Any]]:
        """Yield one response per page, up to ``max_pages``."""
        if max_pages is None:
            max_pages = self.max_pages

        request_params: dict[str, Any] = dict(params)
        page_count = 0
        while True:
            response = self._request(endpoint, request_params)
            yield response
            page_count += 1

            # Count APIs return a single dict (not a list) on the final
            # page; that's the signal to stop.
            if is_count and isinstance(response.get("results"), dict):
                return
            if max_pages is not None and page_count >= max_pages:
                return
            next_page = response.get("nextPage")
            if not next_page:
                return

            request_params["page"] = next_page
            time.sleep(self.pagination_delay)

    def _compute_backoff(self, attempt: int) -> float:
        delay: float = self.retry_backoff * (2 ** (attempt - 1))
        return min(delay, self.retry_backoff_max)

    def _sleep_for_retry(self, attempt: int) -> None:
        time.sleep(self._compute_backoff(attempt))

    def _endpoint_url(self, endpoint: str) -> str:
        return urljoin(self._base_url, endpoint)
