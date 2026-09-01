"""Mocked unit tests for newsdataapi.

These tests use the ``responses`` library to intercept HTTP traffic and
exercise every interesting path in the client without a real network or
API key.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

import pytest
import requests
import responses

from newsdataapi import (
    NewsDataApiClient,
    NewsdataAPIError,
    NewsDataApiWebSocket,
    NewsdataAuthError,
    NewsdataException,
    NewsdataNetworkError,
    NewsdataRateLimitError,
    NewsdataServerError,
    NewsdataValidationError,
    save_to_csv,
)
from newsdataapi.client import (
    _parse_raw_query,
    _parse_retry_after,
    _redact_url,
    _validate_params,
)

LATEST_URL = "https://newsdata.io/api/1/latest"


# ===========================================================================
# Parameter validation
# ===========================================================================


def test_validate_drops_none_values() -> None:
    out = _validate_params({"q": "foo", "country": None, "size": None})
    assert out == {"q": "foo"}


def test_validate_string_param_accepts_string() -> None:
    assert _validate_params({"q": "hello"}) == {"q": "hello"}


def test_validate_string_param_accepts_list_of_strings() -> None:
    assert _validate_params({"country": ["us", "gb", "in"]}) == {"country": "us,gb,in"}


def test_validate_id_accepts_list() -> None:
    """id is a comma-list filter on the server (in comma_to_list_filter)."""
    assert _validate_params({"id": ["a", "b", "c"]}) == {"id": "a,b,c"}


def test_validate_string_param_rejects_non_string() -> None:
    with pytest.raises(NewsdataValidationError) as exc_info:
        _validate_params({"q": 123})
    assert exc_info.value.param == "q"


def test_validate_string_param_rejects_list_with_non_string_element() -> None:
    with pytest.raises(NewsdataValidationError) as exc_info:
        _validate_params({"country": ["us", 5, "gb"]})
    assert exc_info.value.param == "country"


def test_validate_bool_param_true_to_one() -> None:
    assert _validate_params({"image": True}) == {"image": 1}


def test_validate_bool_param_false_to_zero() -> None:
    assert _validate_params({"image": False}) == {"image": 0}


def test_validate_bool_param_rejects_non_bool() -> None:
    with pytest.raises(NewsdataValidationError) as exc_info:
        _validate_params({"image": "yes"})
    assert exc_info.value.param == "image"


def test_validate_int_param_accepts_int() -> None:
    assert _validate_params({"size": 10}) == {"size": 10}


def test_validate_int_param_rejects_bool() -> None:
    """``bool`` is an ``int`` subclass — must still be rejected for size."""
    with pytest.raises(NewsdataValidationError) as exc_info:
        _validate_params({"size": True})
    assert exc_info.value.param == "size"


def test_validate_int_param_rejects_str() -> None:
    with pytest.raises(NewsdataValidationError):
        _validate_params({"size": "10"})


def test_validate_size_at_cap_accepted() -> None:
    """size=50 (the paid-plan cap) is accepted."""
    assert _validate_params({"size": 50}) == {"size": 50}


def test_validate_size_above_cap_rejected() -> None:
    """size > 50 is rejected client-side."""
    with pytest.raises(NewsdataValidationError) as exc_info:
        _validate_params({"size": 51})
    assert exc_info.value.param == "size"


def test_validate_size_well_above_cap_rejected() -> None:
    with pytest.raises(NewsdataValidationError):
        _validate_params({"size": 1000})


def test_validate_size_at_min_accepted() -> None:
    """size=1 (the minimum) is accepted."""
    assert _validate_params({"size": 1}) == {"size": 1}


def test_validate_size_below_min_rejected() -> None:
    """size < 1 is rejected client-side."""
    with pytest.raises(NewsdataValidationError) as exc_info:
        _validate_params({"size": 0})
    assert exc_info.value.param == "size"


def test_validate_size_negative_rejected() -> None:
    with pytest.raises(NewsdataValidationError):
        _validate_params({"size": -5})


@pytest.mark.parametrize(
    ("params", "first_conflict"),
    [
        # q-variants 3-way mutex
        ({"q": "news", "qInTitle": "bar"}, "q"),
        ({"q": "news", "qInMeta": "bar"}, "q"),
        ({"qInTitle": "foo", "qInMeta": "bar"}, "qInTitle"),
        ({"q": "news", "qInTitle": "bar", "qInMeta": "baz"}, "q"),
        # Include/exclude pairs
        ({"country": "us", "excludecountry": "gb"}, "country"),
        ({"category": "business", "excludecategory": "sports"}, "category"),
        ({"language": "en", "excludelanguage": "fr"}, "language"),
        # Domain 3-way mutex (any two of domain/domainurl/excludedomain)
        ({"domain": "cnn.com", "domainurl": "https://bbc.com"}, "domain"),
        ({"domain": "cnn.com", "excludedomain": "fox.com"}, "domain"),
        (
            {"domainurl": "https://bbc.com", "excludedomain": "fox.com"},
            "domainurl",
        ),
        (
            {
                "domain": "cnn.com",
                "domainurl": "https://bbc.com",
                "excludedomain": "fox.com",
            },
            "domain",
        ),
    ],
)
def test_validate_mutex_groups_raise(
    params: dict[str, str],
    first_conflict: str,
) -> None:
    """Server-rejected mutex combinations are caught client-side."""
    with pytest.raises(NewsdataValidationError) as exc_info:
        _validate_params(params)
    assert "mutually exclusive" in str(exc_info.value)
    assert exc_info.value.param == first_conflict


def test_validate_no_mutex_when_one_per_group_set() -> None:
    """One member from each mutex group plus other params is fine."""
    out = _validate_params(
        {
            "q": "news",
            "country": "us",
            "category": "business",
            "language": "en",
            "domain": "cnn.com",
            "tag": "tech",
        }
    )
    assert out == {
        "q": "news",
        "country": "us",
        "category": "business",
        "language": "en",
        "domain": "cnn.com",
        "tag": "tech",
    }


def test_validate_float_param_accepts_float() -> None:
    out = _validate_params({"sentiment": "positive", "sentiment_score": 44.5})
    assert out == {"sentiment": "positive", "sentiment_score": 44.5}


def test_validate_float_param_accepts_int() -> None:
    """int is accepted alongside float — urlencode handles the conversion."""
    out = _validate_params({"sentiment": "positive", "sentiment_score": 50})
    assert out == {"sentiment": "positive", "sentiment_score": 50}


def test_validate_float_param_rejects_bool() -> None:
    """``bool`` is an ``int`` subclass — must still be rejected for sentiment_score."""
    with pytest.raises(NewsdataValidationError) as exc_info:
        _validate_params({"sentiment": "positive", "sentiment_score": True})
    assert exc_info.value.param == "sentiment_score"
    assert "must be a number" in str(exc_info.value)


def test_validate_float_param_rejects_str() -> None:
    with pytest.raises(NewsdataValidationError) as exc_info:
        _validate_params({"sentiment": "positive", "sentiment_score": "44.5"})
    assert exc_info.value.param == "sentiment_score"
    assert "must be a number" in str(exc_info.value)


def test_sentiment_score_requires_sentiment() -> None:
    """sentiment_score alone (without sentiment) is rejected."""
    with pytest.raises(NewsdataValidationError) as exc_info:
        _validate_params({"sentiment_score": 44.5})
    assert exc_info.value.param == "sentiment_score"
    assert "sentiment" in str(exc_info.value).lower()


def test_sentiment_score_with_sentiment_passes() -> None:
    """sentiment_score paired with sentiment passes through."""
    out = _validate_params({"sentiment": "positive", "sentiment_score": 44.5})
    assert out == {"sentiment": "positive", "sentiment_score": 44.5}


def test_sentiment_alone_passes() -> None:
    """sentiment without sentiment_score is allowed (regression)."""
    out = _validate_params({"sentiment": "positive"})
    assert out == {"sentiment": "positive"}


def test_validate_unknown_param_passes_through() -> None:
    """Endpoint methods restrict which kwargs reach validation, so we
    deliberately don't reject unclassified params here."""
    out = _validate_params({"q": "foo", "made_up_param": "bar"})
    assert out == {"q": "foo", "made_up_param": "bar"}


def test_validation_error_is_also_value_error() -> None:
    with pytest.raises(ValueError):
        _validate_params({"q": 123})


# ===========================================================================
# raw_query parsing
# ===========================================================================


def test_raw_query_plain_query_string() -> None:
    out = _parse_raw_query(
        "q=foo&country=us",
        allowed_keys={"q", "country", "raw_query"},
    )
    assert out == {"q": "foo", "country": "us"}


def test_raw_query_with_question_mark_prefix() -> None:
    out = _parse_raw_query(
        "?q=foo&country=us",
        allowed_keys={"q", "country", "raw_query"},
    )
    assert out == {"q": "foo", "country": "us"}


def test_raw_query_full_url() -> None:
    out = _parse_raw_query(
        "https://example.com/path?q=foo&country=us",
        allowed_keys={"q", "country", "raw_query"},
    )
    assert out == {"q": "foo", "country": "us"}


def test_raw_query_rejects_unknown_key() -> None:
    with pytest.raises(NewsdataValidationError) as exc_info:
        _parse_raw_query(
            "q=foo&fake=bar",
            allowed_keys={"q", "raw_query"},
        )
    assert exc_info.value.param == "fake"


def test_raw_query_rejects_non_string() -> None:
    with pytest.raises(NewsdataValidationError):
        _parse_raw_query(123, allowed_keys={"q"})  # type: ignore[arg-type]


def test_raw_query_rejects_empty_string() -> None:
    """An empty raw_query string is rejected."""
    with pytest.raises(NewsdataValidationError) as exc_info:
        _parse_raw_query("", allowed_keys={"q", "raw_query"})
    assert exc_info.value.param == "raw_query"
    assert "non-empty" in str(exc_info.value)


def test_validate_raw_query_empty_string_raises() -> None:
    """raw_query="" via _validate_params surfaces the non-empty error."""
    with pytest.raises(NewsdataValidationError) as exc_info:
        _validate_params({"q": None, "raw_query": ""})
    assert exc_info.value.param == "raw_query"
    assert "non-empty" in str(exc_info.value)


def test_validate_raw_query_short_circuits_normal_validation() -> None:
    """When ``raw_query`` is the only non-None param, normal type-checking is bypassed."""
    out = _validate_params({"q": None, "country": None, "raw_query": "?q=hi"})
    assert out == {"q": "hi"}


def test_raw_query_with_other_param_raises() -> None:
    """raw_query rejects co-occurrence with a normal endpoint param."""
    with pytest.raises(NewsdataValidationError) as exc_info:
        _validate_params({"q": "news", "raw_query": "?country=us"})
    assert exc_info.value.param == "raw_query"


def test_raw_query_with_multiple_other_params_lists_them() -> None:
    """Error message names every non-None conflicting param."""
    with pytest.raises(NewsdataValidationError) as exc_info:
        _validate_params({
            "q": "news",
            "country": "us",
            "language": None,
            "raw_query": "?language=en",
        })
    msg = str(exc_info.value)
    assert "q" in msg
    assert "country" in msg


def test_raw_query_apikey_is_dropped() -> None:
    """apikey in raw_query is dropped; client uses constructor apikey."""
    out = _parse_raw_query(
        "apikey=USER_PROVIDED&q=news",
        allowed_keys={"q", "raw_query"},
    )
    assert out == {"q": "news"}


def test_raw_query_apikey_case_insensitive_drop() -> None:
    """apikey drop is case-insensitive."""
    out = _parse_raw_query(
        "APIKEY=USER&q=news",
        allowed_keys={"q", "raw_query"},
    )
    assert out == {"q": "news"}


def test_raw_query_rejects_key_with_empty_value() -> None:
    """A key with an empty value (e.g., q=) is rejected."""
    with pytest.raises(NewsdataValidationError) as exc_info:
        _parse_raw_query("q=", allowed_keys={"q", "raw_query"})
    assert exc_info.value.param == "q"


def test_raw_query_rejects_key_with_no_value() -> None:
    """A bare key with no '=' (e.g., q&country=us) is rejected."""
    with pytest.raises(NewsdataValidationError) as exc_info:
        _parse_raw_query("q&country=us", allowed_keys={"q", "country", "raw_query"})
    assert exc_info.value.param == "q"


# ===========================================================================
# Retry-After parsing
# ===========================================================================


def test_retry_after_none_input() -> None:
    assert _parse_retry_after(None) is None


def test_retry_after_empty_string() -> None:
    assert _parse_retry_after("") is None
    assert _parse_retry_after("   ") is None


def test_retry_after_integer_seconds() -> None:
    assert _parse_retry_after("60") == 60


def test_retry_after_negative_clamped_to_zero() -> None:
    assert _parse_retry_after("-5") == 0


def test_retry_after_unparseable_returns_none() -> None:
    assert _parse_retry_after("not a date or number") is None


def test_retry_after_http_date_future() -> None:
    future = datetime.now(tz=timezone.utc) + timedelta(seconds=60)
    header = format_datetime(future, usegmt=True)
    result = _parse_retry_after(header)
    assert result is not None
    # Allow small drift between format/parse.
    assert 55 <= result <= 65


def test_retry_after_http_date_in_past_clamped_to_zero() -> None:
    past = datetime.now(tz=timezone.utc) - timedelta(seconds=300)
    header = format_datetime(past, usegmt=True)
    assert _parse_retry_after(header) == 0


# ===========================================================================
# URL redaction
# ===========================================================================


def test_redact_url_replaces_apikey() -> None:
    url = "https://newsdata.io/api/1/latest?apikey=SECRET&q=foo"
    redacted = _redact_url(url)
    assert "SECRET" not in redacted
    assert "REDACTED" in redacted
    assert "q=foo" in redacted


def test_redact_url_no_apikey_unchanged() -> None:
    url = "https://newsdata.io/api/1/latest?q=foo"
    assert _redact_url(url) == url


def test_redact_url_only_apikey_param() -> None:
    url = "https://newsdata.io/api/1/latest?apikey=SECRET"
    assert _redact_url(url) == "https://newsdata.io/api/1/latest?apikey=REDACTED"


# ===========================================================================
# CSV export
# ===========================================================================


def test_csv_basic_write(tmp_path: Path) -> None:
    response = {
        "status": "success",
        "results": [
            {"title": "First", "country": "us"},
            {"title": "Second", "country": "gb"},
        ],
    }
    out = save_to_csv(response, tmp_path, filename="test")
    assert out == tmp_path / "test.csv"
    content = out.read_text()
    assert "title,country" in content
    assert "First,us" in content
    assert "Second,gb" in content


def test_csv_empty_results_writes_empty_file(tmp_path: Path) -> None:
    out = save_to_csv({"status": "success", "results": []}, tmp_path, filename="empty")
    assert out.exists()
    assert out.read_text() == ""


def test_csv_nonexistent_folder_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        save_to_csv({"results": []}, tmp_path / "does_not_exist", filename="x")


def test_csv_existing_file_no_overwrite_raises(tmp_path: Path) -> None:
    target = tmp_path / "exists.csv"
    target.write_text("existing")
    with pytest.raises(FileExistsError):
        save_to_csv({"results": [{"a": 1}]}, tmp_path, filename="exists")
    # Original content preserved.
    assert target.read_text() == "existing"


def test_csv_existing_file_with_overwrite_succeeds(tmp_path: Path) -> None:
    target = tmp_path / "overwrite.csv"
    target.write_text("old")
    save_to_csv(
        {"results": [{"col": "new"}]},
        tmp_path,
        filename="overwrite",
        overwrite=True,
    )
    content = target.read_text()
    assert "new" in content
    assert "old" not in content


def test_csv_dict_cell_value_is_stringified(tmp_path: Path) -> None:
    response = {"results": [{"title": "T", "meta": {"a": 1, "b": 2}}]}
    out = save_to_csv(response, tmp_path, filename="dictcell")
    content = out.read_text()
    assert "a:1,b:2" in content


def test_csv_list_cell_value_is_comma_joined(tmp_path: Path) -> None:
    response = {"results": [{"title": "T", "tags": ["news", "us"]}]}
    out = save_to_csv(response, tmp_path, filename="listcell")
    content = out.read_text()
    assert "news,us" in content


def test_csv_does_not_mutate_response(tmp_path: Path) -> None:
    """save_to_csv must not mutate the input response."""
    original_results = [{"title": "T", "tags": ["a", "b"], "meta": {"k": "v"}}]
    response = {"results": original_results}
    save_to_csv(response, tmp_path, filename="immutable")

    assert response["results"] is original_results
    assert response["results"][0]["tags"] == ["a", "b"]
    assert response["results"][0]["meta"] == {"k": "v"}
    assert response["results"][0]["title"] == "T"


def test_csv_mixed_schemas_use_union_of_keys(tmp_path: Path) -> None:
    response = {"results": [{"a": 1, "b": 2}, {"a": 3, "c": 4}]}
    out = save_to_csv(response, tmp_path, filename="mixed")
    header = out.read_text().splitlines()[0]
    assert "a" in header
    assert "b" in header
    assert "c" in header


def test_csv_filename_appends_extension(tmp_path: Path) -> None:
    out = save_to_csv({"results": [{"a": 1}]}, tmp_path, filename="noext")
    assert out.suffix == ".csv"


def test_csv_filename_keeps_extension(tmp_path: Path) -> None:
    out = save_to_csv({"results": [{"a": 1}]}, tmp_path, filename="hasext.csv")
    assert out.name == "hasext.csv"


def test_csv_default_filename_is_timestamp(tmp_path: Path) -> None:
    out = save_to_csv({"results": [{"a": 1}]}, tmp_path)
    assert out.parent == tmp_path
    assert out.suffix == ".csv"
    assert out.stem.isdigit()


def test_csv_results_not_a_list_raises_type_error(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        save_to_csv({"results": "not a list"}, tmp_path, filename="x")


# ===========================================================================
# Exception hierarchy
# ===========================================================================


def test_exception_message_round_trips_through_str() -> None:
    """NewsdataException's message round-trips through str(e)."""
    e = NewsdataException("something failed")
    assert str(e) == "something failed"


def test_validation_error_carries_param_and_is_value_error() -> None:
    e = NewsdataValidationError("bad", param="q")
    assert isinstance(e, ValueError)
    assert isinstance(e, NewsdataException)
    assert e.param == "q"


def test_api_error_attributes() -> None:
    e = NewsdataAPIError("oops", status_code=400, response_body={"x": 1})
    assert e.status_code == 400
    assert e.response_body == {"x": 1}


def test_rate_limit_error_default_status_and_retry_after() -> None:
    e = NewsdataRateLimitError("limited", retry_after=120)
    assert e.status_code == 429
    assert e.retry_after == 120


def test_network_error_carries_original_exception() -> None:
    inner = ConnectionError("dns failure")
    e = NewsdataNetworkError("netfail", original=inner)
    assert e.original is inner


def test_specific_api_errors_subclass_api_error() -> None:
    assert issubclass(NewsdataAuthError, NewsdataAPIError)
    assert issubclass(NewsdataRateLimitError, NewsdataAPIError)
    assert issubclass(NewsdataServerError, NewsdataAPIError)


# ===========================================================================
# Client constructor / config
# ===========================================================================


def test_constructor_rejects_empty_apikey() -> None:
    with pytest.raises(NewsdataValidationError):
        NewsDataApiClient("")


def test_constructor_rejects_non_string_apikey() -> None:
    with pytest.raises(NewsdataValidationError):
        NewsDataApiClient(123)  # type: ignore[arg-type]


def test_constructor_rejects_none_apikey() -> None:
    with pytest.raises(NewsdataValidationError):
        NewsDataApiClient(None)  # type: ignore[arg-type]


def test_base_url_normalized_to_trailing_slash() -> None:
    c = NewsDataApiClient("k", base_url="https://example.com/api")
    assert c._base_url.endswith("/")


def test_base_url_keeps_trailing_slash() -> None:
    c = NewsDataApiClient("k", base_url="https://example.com/api/")
    assert c._base_url == "https://example.com/api/"


def test_set_base_url_normalizes() -> None:
    c = NewsDataApiClient("k")
    c.set_base_url("https://staging.example.com")
    assert c._base_url == "https://staging.example.com/"


def test_set_base_url_rejects_empty() -> None:
    c = NewsDataApiClient("k")
    with pytest.raises(ValueError):
        c.set_base_url("")


def test_context_manager_closes_owned_session() -> None:
    c = NewsDataApiClient("k")
    assert not c._closed
    with c:
        pass
    assert c._closed


def test_injected_session_not_closed_by_client() -> None:
    user_session = requests.Session()
    with NewsDataApiClient("k", session=user_session) as c:
        assert c._session is user_session
        assert not c._owns_session
    # Session closing is the caller's responsibility.
    user_session.close()


# ===========================================================================
# Single request: success / error / auth / 4xx
# ===========================================================================


def test_request_success_returns_body(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
) -> None:
    mocked_responses.get(
        LATEST_URL,
        json={"status": "success", "results": [{"id": "1"}]},
        status=200,
    )
    response = client.latest_api(q="test")
    assert isinstance(response, dict)
    assert response["status"] == "success"
    assert response["results"] == [{"id": "1"}]


def test_apikey_appended_to_query(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
) -> None:
    mocked_responses.get(
        LATEST_URL,
        json={"status": "success", "results": []},
        status=200,
    )
    client.latest_api(q="test")
    sent_url = mocked_responses.calls[0].request.url
    assert sent_url is not None
    assert "apikey=test_key_xxx" in sent_url


def test_accept_language_header_sent(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
) -> None:
    mocked_responses.get(
        LATEST_URL,
        json={"status": "success", "results": []},
        status=200,
    )
    client.latest_api()
    headers = mocked_responses.calls[0].request.headers
    assert headers.get("Accept-Language") == "en"


def test_include_headers_merges_into_response(
    mocked_responses: responses.RequestsMock,
) -> None:
    with NewsDataApiClient("k", include_headers=True, max_retries=1) as c:
        mocked_responses.get(
            LATEST_URL,
            json={"status": "success", "results": []},
            status=200,
            headers={"X-API-Limit-Remaining": "100"},
        )
        response = c.latest_api()
    assert isinstance(response, dict)
    assert "response_headers" in response
    assert response["response_headers"]["X-API-Limit-Remaining"] == "100"


def test_status_error_with_200_raises_api_error(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
) -> None:
    mocked_responses.get(
        LATEST_URL,
        json={"status": "error", "results": {"code": "BadRequest"}},
        status=200,
    )
    with pytest.raises(NewsdataAPIError):
        client.latest_api()


def test_results_none_treated_as_error(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
) -> None:
    mocked_responses.get(
        LATEST_URL,
        json={"status": "success", "results": None},
        status=200,
    )
    with pytest.raises(NewsdataAPIError):
        client.latest_api()


def test_401_raises_auth_error(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
) -> None:
    mocked_responses.get(
        LATEST_URL,
        json={"status": "error", "results": {"code": "Unauthorized"}},
        status=401,
    )
    with pytest.raises(NewsdataAuthError) as exc_info:
        client.latest_api()
    assert exc_info.value.status_code == 401


def test_403_raises_auth_error(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
) -> None:
    mocked_responses.get(
        LATEST_URL,
        json={"status": "error"},
        status=403,
    )
    with pytest.raises(NewsdataAuthError):
        client.latest_api()


def test_404_raises_api_error_not_auth(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
) -> None:
    mocked_responses.get(
        LATEST_URL,
        json={"status": "error"},
        status=404,
    )
    with pytest.raises(NewsdataAPIError) as exc_info:
        client.latest_api()
    assert exc_info.value.status_code == 404
    assert not isinstance(exc_info.value, NewsdataAuthError)


# ===========================================================================
# Retries
# ===========================================================================


def test_429_then_200_succeeds(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
    no_sleep: None,
) -> None:
    mocked_responses.get(LATEST_URL, json={"status": "error"}, status=429)
    mocked_responses.get(
        LATEST_URL,
        json={"status": "success", "results": [{"id": "1"}]},
        status=200,
    )
    response = client.latest_api()
    assert isinstance(response, dict)
    assert response["status"] == "success"
    assert len(mocked_responses.calls) == 2


def test_429_exhausted_raises_rate_limit_with_retry_after(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
    no_sleep: None,
) -> None:
    for _ in range(client.max_retries):
        mocked_responses.get(
            LATEST_URL,
            json={"status": "error"},
            status=429,
            headers={"Retry-After": "5"},
        )
    with pytest.raises(NewsdataRateLimitError) as exc_info:
        client.latest_api()
    assert exc_info.value.retry_after == 5


@pytest.mark.parametrize("code", ["ApiKeyLimitExceeded", "ApiLimitExceeded"])
def test_429_quota_exhausted_raises_without_retry(
    code: str,
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
    no_sleep: None,
) -> None:
    """A 429 whose error code means exhausted credits is never retried."""
    body = {"status": "error", "results": {"message": "limit", "code": code}}
    mocked_responses.get(LATEST_URL, json=body, status=429)
    with pytest.raises(NewsdataRateLimitError) as exc_info:
        client.latest_api()
    assert len(mocked_responses.calls) == 1
    assert exc_info.value.response_body == body


def test_500_then_200_succeeds(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
    no_sleep: None,
) -> None:
    mocked_responses.get(LATEST_URL, json={"error": "boom"}, status=500)
    mocked_responses.get(
        LATEST_URL,
        json={"status": "success", "results": []},
        status=200,
    )
    response = client.latest_api()
    assert isinstance(response, dict)
    assert response["status"] == "success"


def test_500_exhausted_raises_server_error(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
    no_sleep: None,
) -> None:
    for _ in range(client.max_retries):
        mocked_responses.get(LATEST_URL, json={"error": "boom"}, status=500)
    with pytest.raises(NewsdataServerError) as exc_info:
        client.latest_api()
    assert exc_info.value.status_code == 500


def test_network_error_then_200_succeeds(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
    no_sleep: None,
) -> None:
    mocked_responses.get(
        LATEST_URL,
        body=requests.exceptions.ConnectionError("dns failed"),
    )
    mocked_responses.get(
        LATEST_URL,
        json={"status": "success", "results": []},
        status=200,
    )
    response = client.latest_api()
    assert isinstance(response, dict)
    assert response["status"] == "success"


def test_network_error_exhausted_raises_network_error(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
    no_sleep: None,
) -> None:
    for _ in range(client.max_retries):
        mocked_responses.get(
            LATEST_URL,
            body=requests.exceptions.ConnectionError("net down"),
        )
    with pytest.raises(NewsdataNetworkError) as exc_info:
        client.latest_api()
    assert exc_info.value.original is not None


def test_non_json_2xx_raises_immediately(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
) -> None:
    mocked_responses.get(LATEST_URL, body="<html>not json</html>", status=200)
    with pytest.raises(NewsdataAPIError):
        client.latest_api()


def test_non_json_5xx_retries(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
    no_sleep: None,
) -> None:
    mocked_responses.get(LATEST_URL, body="<html>500</html>", status=500)
    mocked_responses.get(
        LATEST_URL,
        json={"status": "success", "results": []},
        status=200,
    )
    response = client.latest_api()
    assert isinstance(response, dict)
    assert response["status"] == "success"


def test_backoff_grows_then_caps() -> None:
    """Verifies exponential backoff math; doesn't call time.sleep."""
    c = NewsDataApiClient(
        "k", retry_backoff=2.0, retry_backoff_max=60.0, max_retries=10
    )
    assert c._compute_backoff(1) == 2.0
    assert c._compute_backoff(2) == 4.0
    assert c._compute_backoff(3) == 8.0
    assert c._compute_backoff(5) == 32.0
    assert c._compute_backoff(6) == 60.0  # 64 capped to 60
    assert c._compute_backoff(20) == 60.0  # still capped


# ===========================================================================
# Scroll mode
# ===========================================================================


def test_scroll_merges_pages(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
    no_sleep: None,
) -> None:
    mocked_responses.get(
        LATEST_URL,
        json={
            "status": "success",
            "results": [{"id": "1"}, {"id": "2"}],
            "totalResults": 5,
            "nextPage": "p2",
        },
        status=200,
    )
    mocked_responses.get(
        LATEST_URL,
        json={
            "status": "success",
            "results": [{"id": "3"}, {"id": "4"}],
            "totalResults": 5,
            "nextPage": "p3",
        },
        status=200,
    )
    mocked_responses.get(
        LATEST_URL,
        json={
            "status": "success",
            "results": [{"id": "5"}],
            "totalResults": 5,
            "nextPage": None,
        },
        status=200,
    )
    result = client.latest_api(q="x", scroll=True)
    assert isinstance(result, dict)
    assert result["totalResults"] == 5
    assert [r["id"] for r in result["results"]] == ["1", "2", "3", "4", "5"]
    assert result["nextPage"] is None


def test_scroll_truncates_to_max_result(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
    no_sleep: None,
) -> None:
    mocked_responses.get(
        LATEST_URL,
        json={
            "status": "success",
            "results": [{"id": str(i)} for i in range(5)],
            "nextPage": "p2",
        },
        status=200,
    )
    mocked_responses.get(
        LATEST_URL,
        json={
            "status": "success",
            "results": [{"id": str(i)} for i in range(5, 10)],
            "nextPage": "p3",
        },
        status=200,
    )
    result = client.latest_api(q="x", scroll=True, max_result=7)
    assert isinstance(result, dict)
    assert len(result["results"]) == 7  # hard cap, not approximate
    assert result["nextPage"] is None


def test_scroll_stops_when_no_next_page(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
    no_sleep: None,
) -> None:
    mocked_responses.get(
        LATEST_URL,
        json={"status": "success", "results": [{"id": "a"}], "nextPage": None},
        status=200,
    )
    result = client.latest_api(q="x", scroll=True)
    assert isinstance(result, dict)
    assert len(result["results"]) == 1


def test_scroll_count_merges_bucket_pages(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
    no_sleep: None,
) -> None:
    """Count scroll concatenates per-bucket rows and captures the final aggregate."""
    count_url = "https://newsdata.io/api/1/count"
    mocked_responses.get(
        count_url,
        json={
            "status": "success",
            "results": [{"dateTime": "2026-01-01", "count": 100}],
            "nextPage": "p2",
        },
        status=200,
    )
    mocked_responses.get(
        count_url,
        json={
            "status": "success",
            "results": [{"dateTime": "2025-12-31", "count": 200}],
            "nextPage": "p3",
        },
        status=200,
    )
    mocked_responses.get(
        count_url,
        json={
            "status": "success",
            "results": {"count": 300},
            "nextPage": None,
        },
        status=200,
    )
    result = client.count_api(
        from_date="2025-01-01 00:00:00",
        to_date="2026-01-01 00:00:00",
        scroll=True,
    )
    assert isinstance(result, dict)
    assert result["results"] == [
        {"dateTime": "2026-01-01", "count": 100},
        {"dateTime": "2025-12-31", "count": 200},
    ]
    assert result["aggregate"] == {"count": 300}
    assert result["nextPage"] is None


def test_scroll_count_truncates_to_max_result(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
    no_sleep: None,
) -> None:
    """max_result on count scroll caps the buckets list."""
    count_url = "https://newsdata.io/api/1/count"
    mocked_responses.get(
        count_url,
        json={
            "status": "success",
            "results": [{"d": "1"}, {"d": "2"}, {"d": "3"}],
            "nextPage": "p2",
        },
        status=200,
    )
    result = client.count_api(
        from_date="2025-01-01 00:00:00",
        to_date="2026-01-01 00:00:00",
        scroll=True,
        max_result=2,
    )
    assert isinstance(result, dict)
    assert len(result["results"]) == 2
    assert result["nextPage"] is None


def test_scroll_count_single_aggregate_response(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
    no_sleep: None,
) -> None:
    """Count scroll on a no-buckets response captures the aggregate and stops."""
    mocked_responses.get(
        "https://newsdata.io/api/1/count",
        json={
            "status": "success",
            "results": {"count": 9999},
            "nextPage": None,
        },
        status=200,
    )
    result = client.count_api(
        from_date="2025-01-01 00:00:00",
        to_date="2026-01-01 00:00:00",
        scroll=True,
    )
    assert isinstance(result, dict)
    assert result["results"] == []
    assert result["aggregate"] == {"count": 9999}


def test_scroll_news_does_not_add_aggregate_field(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
    no_sleep: None,
) -> None:
    """News-endpoint scroll merges as before — no aggregate key added."""
    mocked_responses.get(
        LATEST_URL,
        json={"status": "success", "results": [{"id": "1"}], "nextPage": None},
        status=200,
    )
    result = client.latest_api(scroll=True)
    assert isinstance(result, dict)
    assert "aggregate" not in result


# ===========================================================================
# Paginate mode
# ===========================================================================


def test_paginate_yields_one_response_per_page(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
    no_sleep: None,
) -> None:
    mocked_responses.get(
        LATEST_URL,
        json={"status": "success", "results": [{"id": "1"}], "nextPage": "p2"},
        status=200,
    )
    mocked_responses.get(
        LATEST_URL,
        json={"status": "success", "results": [{"id": "2"}], "nextPage": None},
        status=200,
    )
    result = client.latest_api(q="x", paginate=True)
    pages = list(result)
    assert len(pages) == 2
    assert pages[0]["results"] == [{"id": "1"}]
    assert pages[1]["results"] == [{"id": "2"}]


def test_paginate_max_pages_caps(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
    no_sleep: None,
) -> None:
    # Register exactly ``max_pages`` mocks. Each claims another page exists,
    # so if the cap weren't enforced the client would try a 4th call and
    # responses would raise ConnectionError (no mock for it).
    for i in range(3):
        mocked_responses.get(
            LATEST_URL,
            json={
                "status": "success",
                "results": [{"id": str(i)}],
                "nextPage": f"p{i + 1}",
            },
            status=200,
        )
    result = client.latest_api(q="x", paginate=True, max_pages=3)
    pages = list(result)
    assert len(pages) == 3


def test_paginate_count_dict_results_terminate(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
    no_sleep: None,
) -> None:
    """Count APIs return a dict for ``results`` — pagination must stop."""
    mocked_responses.get(
        "https://newsdata.io/api/1/count",
        json={
            "status": "success",
            "results": {"total": 100},
            "nextPage": None,
        },
        status=200,
    )
    pages = list(
        client.count_api(
            from_date="2024-01-01",
            to_date="2024-01-31",
            paginate=True,
        )
    )
    assert len(pages) == 1
    assert pages[0]["results"] == {"total": 100}


def test_scroll_and_paginate_mutually_exclusive(client: NewsDataApiClient) -> None:
    with pytest.raises(ValueError):
        client.latest_api(scroll=True, paginate=True)


# ===========================================================================
# Endpoint URL construction (one mocked round-trip per endpoint)
# ===========================================================================


@pytest.mark.parametrize(
    ("method_name", "endpoint_path"),
    [
        ("latest_api", "latest"),
        ("archive_api", "archive"),
        ("sources_api", "sources"),
        ("crypto_api", "crypto"),
        ("market_api", "market"),
    ],
)
def test_endpoint_url_resolves(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
    method_name: str,
    endpoint_path: str,
) -> None:
    mocked_responses.get(
        f"https://newsdata.io/api/1/{endpoint_path}",
        json={"status": "success", "results": []},
        status=200,
    )
    method = getattr(client, method_name)
    method()
    assert len(mocked_responses.calls) == 1


@pytest.mark.parametrize(
    ("method_name", "endpoint_path"),
    [
        ("count_api", "count"),
        ("crypto_count_api", "crypto/count"),
        ("market_count_api", "market/count"),
    ],
)
def test_count_endpoint_url_resolves(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
    method_name: str,
    endpoint_path: str,
) -> None:
    mocked_responses.get(
        f"https://newsdata.io/api/1/{endpoint_path}",
        json={
            "status": "success",
            "results": [{"date": "2024-01-01", "count": 5}],
        },
        status=200,
    )
    method = getattr(client, method_name)
    method(from_date="2024-01-01", to_date="2024-01-31")
    assert len(mocked_responses.calls) == 1


# ===========================================================================
# WebSocket query management (register / fetch / delete)
# ===========================================================================

WS_REGISTER_URL = "https://newsdata.io/api/1/websocket/register"
WS_FETCH_URL = "https://newsdata.io/api/1/websocket/fetch"
WS_DELETE_URL = "https://newsdata.io/api/1/websocket/delete"


def test_websocket_register_posts_query_params(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
) -> None:
    """register POSTs, with every param (and the apikey) in the query string."""
    mocked_responses.post(
        WS_REGISTER_URL,
        json={
            "status": "success",
            "results": {"message": "registered", "registration_id": "abc123"},
        },
        status=200,
    )
    response = NewsDataApiWebSocket(client).websocket_register(
        q="pizza", country=["us", "gb"], image=True
    )
    assert response["results"]["registration_id"] == "abc123"
    sent = mocked_responses.calls[0].request
    assert sent.url is not None
    assert "q=pizza" in sent.url
    assert "country=us%2Cgb" in sent.url
    assert "image=1" in sent.url
    assert "apikey=test_key_xxx" in sent.url
    assert not sent.body  # params travel in the query string, not a body


def test_websocket_register_always_sends_news_type_latest(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
) -> None:
    mocked_responses.post(
        WS_REGISTER_URL,
        json={"status": "success", "results": {"registration_id": "abc"}},
        status=200,
    )
    NewsDataApiWebSocket(client).websocket_register(q="nvidia")
    sent_url = mocked_responses.calls[0].request.url
    assert sent_url is not None
    assert "news_type=latest" in sent_url


def test_websocket_register_mutex_validation_applies(
    client: NewsDataApiClient,
) -> None:
    """The shared mutex groups guard register too — no request is sent."""
    with pytest.raises(NewsdataValidationError):
        NewsDataApiWebSocket(client).websocket_register(q="a", qInTitle="b")


def test_websocket_register_raw_query(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
) -> None:
    mocked_responses.post(
        WS_REGISTER_URL,
        json={"status": "success", "results": {"registration_id": "abc"}},
        status=200,
    )
    NewsDataApiWebSocket(client).websocket_register(raw_query="q=pizza")
    sent_url = mocked_responses.calls[0].request.url
    assert sent_url is not None
    assert "q=pizza" in sent_url
    assert "news_type=latest" in sent_url


def test_websocket_register_raw_query_rejects_unknown_param(
    client: NewsDataApiClient,
) -> None:
    """size is valid on latest_api but not on websocket/register."""
    with pytest.raises(NewsdataValidationError):
        NewsDataApiWebSocket(client).websocket_register(raw_query="q=pizza&size=10")


def test_websocket_register_duplicate_409(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
) -> None:
    """A duplicate registration raises immediately, carrying the existing id."""
    mocked_responses.post(
        WS_REGISTER_URL,
        json={
            "status": "error",
            "results": {
                "message": "already registered",
                "code": "Conflict",
                "registration_id": "existing123",
            },
        },
        status=409,
    )
    with pytest.raises(NewsdataAPIError) as exc_info:
        NewsDataApiWebSocket(client).websocket_register(q="pizza")
    assert exc_info.value.status_code == 409
    assert exc_info.value.response_body is not None
    assert (
        exc_info.value.response_body["results"]["registration_id"] == "existing123"
    )
    assert len(mocked_responses.calls) == 1  # 4xx is never retried


def test_websocket_register_403_raises_auth(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
) -> None:
    """No WebSocket entitlement on the plan -> NewsdataAuthError."""
    mocked_responses.post(WS_REGISTER_URL, json={"status": "error"}, status=403)
    with pytest.raises(NewsdataAuthError):
        NewsDataApiWebSocket(client).websocket_register(q="pizza")


def test_websocket_register_429_exhausts_to_rate_limit(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
    no_sleep: None,
) -> None:
    """429 retries with backoff, then raises."""
    for _ in range(client.max_retries):
        mocked_responses.post(WS_REGISTER_URL, json={"status": "error"}, status=429)
    with pytest.raises(NewsdataRateLimitError):
        NewsDataApiWebSocket(client).websocket_register(q="pizza")


def test_websocket_fetch_returns_queries(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
) -> None:
    mocked_responses.get(
        WS_FETCH_URL,
        json={
            "status": "success",
            "totalQueries": 1,
            "results": {
                "queries": [
                    {
                        "registration_id": "abc123",
                        "active_clients": 2,
                        "news_type": "latest",
                        "query": {"q": "pizza"},
                    }
                ]
            },
        },
        status=200,
    )
    response = NewsDataApiWebSocket(client).websocket_fetch()
    assert response["totalQueries"] == 1
    assert response["results"]["queries"][0]["registration_id"] == "abc123"
    sent_url = mocked_responses.calls[0].request.url
    assert sent_url is not None
    assert "apikey=test_key_xxx" in sent_url


def test_websocket_delete_sends_registration_id(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
) -> None:
    mocked_responses.delete(
        WS_DELETE_URL,
        json={
            "status": "success",
            "results": {"message": "deleted", "registration_id": "abc123"},
        },
        status=200,
    )
    response = NewsDataApiWebSocket(client).websocket_delete("abc123")
    assert response["results"]["registration_id"] == "abc123"
    sent_url = mocked_responses.calls[0].request.url
    assert sent_url is not None
    assert "registration_id=abc123" in sent_url


def test_websocket_delete_unknown_id_404(
    client: NewsDataApiClient,
    mocked_responses: responses.RequestsMock,
) -> None:
    mocked_responses.delete(WS_DELETE_URL, json={"status": "error"}, status=404)
    with pytest.raises(NewsdataAPIError) as exc_info:
        NewsDataApiWebSocket(client).websocket_delete("nope")
    assert exc_info.value.status_code == 404


@pytest.mark.parametrize("bad_id", ["", None, 123])
def test_websocket_delete_rejects_bad_registration_id(
    client: NewsDataApiClient,
    bad_id: object,
) -> None:
    with pytest.raises(NewsdataValidationError) as exc_info:
        NewsDataApiWebSocket(client).websocket_delete(bad_id)  # type: ignore[arg-type]
    assert exc_info.value.param == "registration_id"


# ===========================================================================
# Client.save_to_csv (instance method delegation + folder fallback)
# ===========================================================================


def test_client_save_to_csv_uses_constructor_folder(tmp_path: Path) -> None:
    with NewsDataApiClient("k", folder_path=tmp_path) as c:
        out = c.save_to_csv({"results": [{"a": 1}]}, filename="frominit")
    assert out == tmp_path / "frominit.csv"


def test_client_save_to_csv_call_arg_overrides_constructor(tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    with NewsDataApiClient("k", folder_path=tmp_path) as c:
        out = c.save_to_csv({"results": [{"a": 1}]}, folder_path=other, filename="x")
    assert out.parent == other


def test_client_save_to_csv_no_folder_raises(client: NewsDataApiClient) -> None:
    with pytest.raises(ValueError):
        client.save_to_csv({"results": [{"a": 1}]}, filename="x")
