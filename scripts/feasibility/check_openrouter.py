"""Milestone 1 probe: OpenRouter access, free-model inventory, and structured output.

Why this exists: the technical PRD (section 8.1) requires the daily provider
ceiling to come from the *account's verified allowance*, not from published
documentation. This script reads the allowance from the account itself.

Budget note: `--list` and the default run spend no chat quota. Only `--generate`
consumes a request against the free-model daily limit, so it is opt-in.

    uv run python ../scripts/feasibility/check_openrouter.py
    uv run python ../scripts/feasibility/check_openrouter.py --generate <model-id>
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import httpx

BASE = "https://openrouter.ai/api/v1"
TIMEOUT = 30.0

# A deliberately non-benchmark question. Real BioASQ items must never be spent on
# smoke tests (technical PRD section 10: "live smoke suite on non-test examples").
SMOKE_QUESTION = "Which enzyme is inhibited by the drug allopurinol?"
SMOKE_EVIDENCE = (
    "S1: Allopurinol is a xanthine oxidase inhibitor used to lower serum urate "
    "concentrations in the management of gout."
)

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "outcome": {"type": "string", "enum": ["answered", "insufficient_evidence"]},
        "items": {"type": "array", "items": {"type": "string"}},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "source_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["text", "source_ids"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["outcome", "items", "claims"],
    "additionalProperties": False,
}


def client(key: str) -> httpx.Client:
    return httpx.Client(
        base_url=BASE,
        headers={"Authorization": f"Bearer {key}"},
        timeout=TIMEOUT,
    )


def report_key(c: httpx.Client) -> None:
    """The measured allowance. This is the number to configure limits from."""
    r = c.get("/key")
    r.raise_for_status()
    data = r.json().get("data", {})
    print("== account allowance (measured, not documented) ==")
    print(f"  label:             {data.get('label')}")
    print(f"  is_free_tier:      {data.get('is_free_tier')}")
    print(f"  usage:             {data.get('usage')}")
    print(f"  credit limit:      {data.get('limit')}")
    print(f"  limit remaining:   {data.get('limit_remaining')}")
    print(f"  rate_limit:        {data.get('rate_limit')}")
    print()
    print("  NOTE: a missing usage value is null, not zero (technical PRD 8.1).")
    print()


def report_free_models(c: httpx.Client, limit: int) -> list[str]:
    r = c.get("/models")
    r.raise_for_status()
    free = []
    for m in r.json().get("data", []):
        pricing = m.get("pricing") or {}
        if str(pricing.get("prompt")) in ("0", "0.0") and str(pricing.get("completion")) in ("0", "0.0"):
            free.append(m)
    free.sort(key=lambda m: -(m.get("context_length") or 0))
    print(f"== free models available: {len(free)} (showing {min(limit, len(free))}) ==")
    for m in free[:limit]:
        params = (m.get("supported_parameters") or [])
        structured = "structured" if "response_format" in params else "-"
        print(f"  {m['id']:<55} ctx={m.get('context_length'):<9} {structured}")
    print()
    print("  Pick ONE model and pin it for an evaluation run (technical PRD 6.2).")
    print("  Do not use a randomly-selecting free router for controlled comparisons.")
    print()
    return [m["id"] for m in free]


def try_generate(c: httpx.Client, model: str) -> bool:
    """Spends one request. Verifies the model can return parseable structured output."""
    print(f"== structured-output check: {model} (spends 1 request) ==")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Answer only from the supplied sources. Cite source IDs. "
                    "If the sources do not support an answer, return outcome "
                    "'insufficient_evidence'."
                ),
            },
            {"role": "user", "content": f"Question: {SMOKE_QUESTION}\n\nSources:\n{SMOKE_EVIDENCE}"},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "answer", "strict": True, "schema": ANSWER_SCHEMA},
        },
    }
    r = c.post("/chat/completions", json=payload)
    print(f"  HTTP {r.status_code}")
    for h in ("x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset", "retry-after"):
        if h in r.headers:
            print(f"  {h}: {r.headers[h]}")
    if r.status_code != 200:
        print(f"  body: {r.text[:500]}")
        return False

    body = r.json()
    print(f"  requested model: {model}")
    print(f"  returned model:  {body.get('model')}")
    print(f"  provider:        {body.get('provider')}")
    print(f"  usage:           {body.get('usage')}")
    content = body["choices"][0]["message"]["content"]
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as e:
        print(f"  FAIL: response was not valid JSON ({e})")
        print(f"  raw: {content[:400]}")
        return False
    print(f"  parsed JSON:     {json.dumps(parsed, indent=2)[:600]}")
    ok = parsed.get("outcome") in {"answered", "insufficient_evidence"}
    print(f"  schema honoured: {ok}")
    return ok


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--generate", metavar="MODEL_ID", help="spend one request on this model")
    p.add_argument("--show", type=int, default=15, help="how many free models to list")
    args = p.parse_args()

    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        print("OPENROUTER_API_KEY is not set. Create the key, then:")
        print("  export OPENROUTER_API_KEY=sk-or-...")
        return 2

    with client(key) as c:
        report_key(c)
        report_free_models(c, args.show)
        if args.generate:
            return 0 if try_generate(c, args.generate) else 1
        print("Re-run with --generate <model-id> to verify structured output.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
