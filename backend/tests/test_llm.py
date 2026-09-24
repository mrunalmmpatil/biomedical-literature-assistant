"""OpenRouter error mapping against a mock transport."""

import json

import httpx
import pytest

from bla.llm import (
    MalformedOutput,
    OpenRouter,
    ProviderRejected,
    ProviderTimeout,
    ProviderUnavailable,
    QuotaExhausted,
)


def client(handler):
    http = httpx.Client(base_url="https://openrouter.test", transport=httpx.MockTransport(handler))
    return OpenRouter("key", model="m/free", http=http)


def ok(content):
    body = {
        "model": "m/free",
        "provider": "P",
        "usage": {"total_tokens": 5},
        "choices": [{"message": {"content": content}}],
    }
    return lambda request: httpx.Response(200, json=body)


def call(c):
    return c.complete("sys", "user", "s", {"type": "object"})


def test_structured_content_and_metadata():
    completion = call(client(ok('{"a": 1}')))
    assert completion.content == {"a": 1}
    assert completion.returned_model == "m/free" and completion.provider == "P"


def test_request_pins_model_schema_and_hides_reasoning():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return ok('{"a": 1}')(request)

    call(client(handler))
    assert seen["model"] == "m/free"
    assert seen["response_format"]["json_schema"]["strict"] is True
    assert seen["reasoning"] == {"exclude": True}


def test_code_fenced_json_is_accepted():
    assert call(client(ok('```json\n{"a": 1}\n```'))).content == {"a": 1}


@pytest.mark.parametrize("content", ["not json", "[1, 2]", ""])
def test_unparseable_content_is_malformed_output(content):
    with pytest.raises(MalformedOutput):
        call(client(ok(content)))


def error(status, message="", raw=""):
    body = {"error": {"code": status, "message": message, "metadata": {"raw": raw}}}
    return lambda request: httpx.Response(status, json=body)


def test_daily_free_limit_is_quota_exhausted_and_not_retryable():
    with pytest.raises(QuotaExhausted) as exc:
        call(client(error(429, "Rate limit exceeded: free-models-per-day")))
    assert not exc.value.retryable


def test_upstream_pool_429_is_transient():
    with pytest.raises(ProviderUnavailable) as exc:
        call(client(error(429, "Provider returned error", "temporarily rate-limited upstream")))
    assert exc.value.retryable


@pytest.mark.parametrize("status", [401, 402, 403, 400])
def test_auth_and_request_errors_are_rejected_and_not_retryable(status):
    with pytest.raises(ProviderRejected) as exc:
        call(client(error(status)))
    assert not exc.value.retryable


def test_server_errors_are_transient():
    with pytest.raises(ProviderUnavailable):
        call(client(error(502)))


def test_error_inside_a_200_body_is_not_treated_as_content():
    handler = lambda request: httpx.Response(200, json={"error": {"code": 502, "message": "x"}})
    with pytest.raises(ProviderUnavailable):
        call(client(handler))


def test_timeouts_are_typed():
    def handler(request):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(ProviderTimeout):
        call(client(handler))
