"""Milestone 4: controlled outcome cases against the real model.

    cd backend
    uv run --env-file .env python ../scripts/evaluation/run_fixtures.py

Runs evaluation/fixtures/answer-cases-v1.json through the same AnswerService
the API uses, over a BM25 index of the fixture's invented papers only. Every
provider request goes through the daily ledger and the completion cache, so a
re-run spends nothing for unchanged prompts.

Outputs:
    evaluation/results/fixtures-<ts>.json   pass/fail per case (tracked)
    evaluation/runs/fixtures-<ts>/          full diagnostics (untracked)
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from datetime import UTC, date, datetime

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from bla.answering.prompts import PROMPT_VERSION
from bla.answering.service import MESSAGES, AnswerService
from bla.benchmark.llm_budget import CachingLLM, DailyLedger, ceiling_from_allowance
from bla.clarification import ClarificationSigner
from bla.contracts import Outcome, Paper
from bla.corpus import content_hash, normalize_text
from bla.llm import OpenRouter, daily_allowance
from bla.retrieval.bm25 import BM25Retriever

FIXTURES = REPO / "evaluation" / "fixtures" / "answer-cases-v1.json"
LEDGER = REPO / "data" / "openrouter" / "ledger"
CACHE = REPO / "data" / "openrouter" / "cache"


def fixture_papers(spec: dict) -> list[Paper]:
    papers = []
    for p in spec["papers"]:
        title, abstract = normalize_text(p["title"]), normalize_text(p["abstract"])
        papers.append(
            Paper(
                pmid=p["pmid"],
                title=title,
                abstract=abstract,
                retrieved_on=date(2026, 9, 24),
                content_hash=content_hash(title, abstract),
            )
        )
    return papers


def check(expect: dict, response, diag) -> list[str]:
    problems = []
    outcome = response.outcome.value
    if "outcome" in expect and outcome != expect["outcome"]:
        problems.append(f"outcome {outcome}, expected {expect['outcome']}")
    if "outcome_in" in expect and outcome not in expect["outcome_in"]:
        problems.append(f"outcome {outcome}, expected one of {expect['outcome_in']}")
    if expect.get("not_outcome") == outcome:
        problems.append(f"outcome must not be {outcome}")
    items = [i.text.lower() for i in response.answer.items] if response.answer else []
    for needle in expect.get("items_include", []):
        if not any(needle.lower() in item for item in items):
            problems.append(f"no answer item contains {needle!r}")
    for needle in expect.get("items_exclude", []):
        if any(needle.lower() in item for item in items):
            problems.append(f"an answer item contains forbidden {needle!r}")
    if "generation_calls" in expect:
        calls = sum(1 for a in diag.attempts if a["stage"] == "generate")
        if calls != expect["generation_calls"]:
            problems.append(f"{calls} generation calls, expected {expect['generation_calls']}")
    if expect.get("qualifications_required"):
        has = (
            bool(response.answer.qualifications)
            if response.answer
            else response.message != MESSAGES[response.outcome]
        )
        if not has:
            problems.append("no qualification reported")
    return problems


def main() -> int:
    spec = json.loads(FIXTURES.read_text())
    papers = fixture_papers(spec)
    allowance = daily_allowance(os.environ["OPENROUTER_API_KEY"])
    ledger = DailyLedger(LEDGER)
    ledger.ceiling = ceiling_from_allowance(ledger.used(), allowance.remaining)
    print(
        f"== OpenRouter free-model allowance: {allowance.used}/{allowance.limit} used, "
        f"{allowance.remaining} remaining; this run may send {ledger.ceiling - ledger.used()}"
    )
    llm = CachingLLM(OpenRouter(os.environ["OPENROUTER_API_KEY"]), CACHE, ledger)
    service = AnswerService(
        BM25Retriever(papers),
        {p.pmid: p for p in papers},
        llm,
        ClarificationSigner(os.environ["CLARIFICATION_SECRET"]),
        corpus_version=spec["name"],
    )
    print(f"== {len(spec['cases'])} cases; ledger {ledger.used()}/{ledger.ceiling} used today")

    run_id = f"fixtures-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    results, details = [], []
    for case in spec["cases"]:
        response, diag = service.answer(case["question"])
        if "clarification_answer" in case:
            if response.outcome is not Outcome.NEEDS_CLARIFICATION:
                problems = [
                    f"setup: first turn was {response.outcome.value}, not needs_clarification"
                ]
                results.append({"id": case["id"], "passed": False, "problems": problems})
                continue
            response, diag = service.answer(
                case["question"],
                clarification_token=response.clarification.token,
                clarification_answer=case["clarification_answer"],
            )
        problems = check(case["expect"], response, diag)
        results.append(
            {
                "id": case["id"],
                "passed": not problems,
                "problems": problems,
                "outcome": response.outcome.value,
                "items": [i.text for i in response.answer.items] if response.answer else [],
                "qualifications": response.answer.qualifications if response.answer else [],
                "attempts": [
                    {k: a.get(k) for k in ("stage", "error", "validation", "latency_ms")}
                    for a in diag.attempts
                ],
            }
        )
        details.append(
            {
                "id": case["id"],
                "response": response.model_dump(mode="json"),
                "diagnostics": diag.__dict__,
            }
        )
        mark = "PASS" if not problems else "FAIL"
        print(f"  {mark} {case['id']:<34} {response.outcome.value:<22} {'; '.join(problems)}")

    run_dir = REPO / "evaluation" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "cases.json").write_text(json.dumps(details, indent=1, default=str))
    summary = {
        "run_id": run_id,
        "fixtures": spec["name"],
        "model": llm.model,
        "prompt_version": PROMPT_VERSION,
        "passed": sum(r["passed"] for r in results),
        "cases": len(results),
        "requests_dispatched": llm.dispatched,
        "requests_from_cache": llm.hits,
        "results": results,
    }
    out = REPO / "evaluation" / "results" / f"{run_id}.json"
    out.write_text(json.dumps(summary, indent=2) + "\n")
    print(
        f"== {summary['passed']}/{summary['cases']} passed; {llm.dispatched} requests sent, "
        f"{llm.hits} from cache; ledger {ledger.used()}/{ledger.ceiling}"
    )
    print(f"== wrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
