"""OpenRouter chat completions with structured output (technical PRD 6.2, 8.1).

One pinned free model per configuration: never a random free router, never a
paid fallback. Each call is a single provider *attempt*. Retrying is the
caller's decision, because the per-request attempt budget (3) and deadline
(90s) span several calls.

Errors are typed by what the caller should do, not by HTTP code:

- ProviderTimeout      -> transient; may retry within the deadline (504 if spent)
- ProviderUnavailable  -> transient 5xx, upstream 429, or network; may retry once
- QuotaExhausted       -> the account's daily free allowance; never retry
- ProviderRejected     -> auth or request error; never retry, fix configuration
- MalformedOutput      -> 200 but no parseable JSON; the one allowed retry may help
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

BASE_URL = "https://openrouter.ai/api/v1"
MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
"""Verified in Milestone 1 to honour strict JSON schemas (feasibility report 4a)."""

REQUEST_TIMEOUT = 45.0
"""Individual provider request. The PRD 8.1 starting default was 25s; raised on
2026-09-24 after development generations took 19-24s (the model reasons
before answering), so ordinary slow answers would have timed out. The 90s
request deadline still bounds the total."""


class ProviderError(RuntimeError):
    retryable = False


class ProviderTimeout(ProviderError):
    retryable = True


class ProviderUnavailable(ProviderError):
    retryable = True


class QuotaExhausted(ProviderError):
    pass


class ProviderRejected(ProviderError):
    pass


class MalformedOutput(ProviderError):
    retryable = True


@dataclass(frozen=True)
class Completion:
    content: dict[str, Any]
    requested_model: str
    returned_model: str | None
    provider: str | None
    usage: dict[str, Any] | None
    """Token counts as reported; missing usage is None, never zero (8.1)."""
    latency_ms: float
    cached: bool = False
    """True when served from the evaluation cache (latency is the original)."""


class OpenRouter:
    def __init__(
        self,
        api_key: str,
        model: str = MODEL,
        http: httpx.Client | None = None,
        timeout: float = REQUEST_TIMEOUT,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.model = model
        self._http = http or httpx.Client(base_url=BASE_URL)
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "X-Title": "biomedical-literature-assistant",
        }
        self._timeout = timeout
        self._clock = clock

    def complete(
        self,
        system: str,
        user: str,
        schema_name: str,
        schema: dict[str, Any],
        timeout: float | None = None,
    ) -> Completion:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            },
            "temperature": 0,
            # Private reasoning stays private (technical PRD 6.2): excluded
            # from the response rather than filtered afterwards.
            "reasoning": {"exclude": True},
        }
        started = self._clock()
        try:
            response = self._http.post(
                "/chat/completions",
                json=payload,
                headers=self._headers,
                timeout=min(self._timeout, timeout) if timeout else self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeout("provider request timed out") from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailable(f"transport error: {exc.__class__.__name__}") from exc
        latency = (self._clock() - started) * 1000

        _raise_for_status(response)
        try:
            body = response.json()
        except ValueError as exc:
            raise ProviderUnavailable("provider returned a non-JSON body") from exc
        if "error" in body:  # OpenRouter can report upstream failures inside a 200
            raise _from_error_body(body["error"])
        try:
            text = body["choices"][0]["message"]["content"]
            content = json.loads(_strip_fence(text))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise MalformedOutput("response content was not a JSON object") from exc
        if not isinstance(content, dict):
            raise MalformedOutput("response content was not a JSON object")
        return Completion(
            content=content,
            requested_model=self.model,
            returned_model=body.get("model"),
            provider=body.get("provider"),
            usage=body.get("usage"),
            latency_ms=round(latency, 1),
        )


def _strip_fence(text: str) -> str:
    """Some providers wrap JSON in a Markdown code fence despite the schema."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else ""
        stripped = stripped.rsplit("```", 1)[0]
    return stripped


def _raise_for_status(response: httpx.Response) -> None:
    status = response.status_code
    if status == 200:
        return
    try:
        error = response.json().get("error", {})
    except ValueError:
        error = {}
    raise _from_error_body({**error, "code": error.get("code", status)})


def _from_error_body(error: dict) -> ProviderError:
    code = error.get("code")
    message = str(error.get("message", ""))
    metadata = error.get("metadata") or {}
    if code in (401, 402, 403):
        return ProviderRejected(f"provider rejected the request (HTTP {code})")
    if code == 429:
        # OpenRouter's own daily free-model limit, as opposed to a busy
        # upstream shared pool (feasibility report 4a), which is transient.
        text = f"{message} {metadata.get('raw', '')}".lower()
        if "per-day" in text or "per day" in text or "free-models-per-day" in text:
            return QuotaExhausted("daily free-model allowance exhausted")
        return ProviderUnavailable("rate limited upstream (HTTP 429)")
    if code == 408:
        return ProviderTimeout("provider timed out (HTTP 408)")
    if isinstance(code, int) and code >= 500:
        return ProviderUnavailable(f"provider error (HTTP {code})")
    return ProviderRejected(f"provider rejected the request (HTTP {code})")
