"""Milestone 4: end-to-end answers on the DEVELOPMENT split.

    cd backend
    uv run --env-file .env python ../scripts/evaluation/run_answers.py

Runs each development question through the same AnswerService as the API
(BM25 retrieval, the pinned free model, prompt version, validation) and scores
the outcome against the reference answers. Reference answers never reach the
service; they are read only after the response exists.

Free-tier aware: questions run in a fixed order (by ID). When the daily
ledger ceiling is reached the run stops and writes a partial result. Running
again later continues: completed questions come from the completion cache and
spend nothing. A cached completion keeps its original latency.

Outputs:
    evaluation/results/answers-development-<ts>.json   aggregate metrics (tracked)
    evaluation/runs/answers-development-<ts>/           per-question detail (untracked)
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import statistics
import subprocess
import sys
from datetime import UTC, datetime

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from bla.answering.prompts import PROMPT_VERSION
from bla.answering.service import AnswerService
from bla.benchmark.answer_metrics import NORMALIZATION_VERSION, score_fact, score_list
from bla.benchmark.bioasq import BenchmarkQuestion, QuestionType
from bla.benchmark.llm_budget import CachingLLM, DailyBudgetReached, DailyLedger
from bla.clarification import ClarificationSigner
from bla.contracts import Outcome
from bla.ingest.snapshot import read_papers, sha256
from bla.llm import OpenRouter
from bla.retrieval.bm25 import BM25Retriever

LEDGER = REPO / "data" / "openrouter" / "ledger"
CACHE = REPO / "data" / "openrouter" / "cache"


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--benchmark", default="bioasq14b-v1")
    p.add_argument("--split", default="development", choices=["development"])
    p.add_argument("--limit", type=int, default=None, help="first N questions by ID")
    args = p.parse_args()

    bench_path = REPO / "data" / "benchmark" / args.benchmark / "questions.jsonl"
    papers_path = REPO / "data" / "corpus" / args.benchmark / "papers.jsonl"
    questions = []
    for line in bench_path.read_text().splitlines():
        record = json.loads(line)
        if record.pop("split") == args.split:
            questions.append(BenchmarkQuestion.model_validate(record))
    questions.sort(key=lambda q: q.id)
    if len(questions) != 50:
        raise SystemExit(f"expected 50 {args.split} questions, found {len(questions)}")
    questions = questions[: args.limit] if args.limit else questions

    papers = read_papers(papers_path)
    ledger = DailyLedger(LEDGER)
    llm = CachingLLM(OpenRouter(os.environ["OPENROUTER_API_KEY"]), CACHE, ledger)
    service = AnswerService(
        BM25Retriever(papers),
        {paper.pmid: paper for paper in papers},
        llm,
        ClarificationSigner(os.environ["CLARIFICATION_SECRET"]),
        corpus_version=args.benchmark,
    )
    print(f"== {len(questions)} questions; ledger {ledger.used()}/{ledger.ceiling} used today")

    rows, stopped = [], None
    for q in questions:
        try:
            response, diag = service.answer(q.body, request_id=q.id)  # question text only
        except DailyBudgetReached as exc:
            stopped = str(exc)
            break
        items = [i.text for i in response.answer.items] if response.answer else []
        row = {
            "id": q.id,
            "type": q.type.value,
            "outcome": response.outcome.value,
            "items": items,
            "cited_pmids": sorted({s.pmid for s in response.sources if s.excerpts}),
            "shown_pmids": [s.pmid for s in response.sources],
            "reference_pmids_shown": sorted({s.pmid for s in response.sources} & set(q.pmids)),
            "retrieved": diag.retrieval,
            "attempts": diag.attempts,
            "assessment": diag.assessment,
            "internal_reason": diag.internal_reason,
            "total_ms": diag.total_ms,
        }
        if response.outcome is Outcome.ANSWERED:
            if q.type is QuestionType.FACT:
                s = score_fact(items, q.answers)
                row["score"] = {"strict": s.strict, "lenient": s.lenient}
            else:
                s = score_list(items, q.answers)
                row["score"] = {"precision": s.precision, "recall": s.recall, "f1": s.f1}
        rows.append(row)
        print(f"  {q.id} {q.type.value:<4} {response.outcome.value:<22} {row.get('score', '')}")

    run_id = f"answers-{args.split}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    run_dir = REPO / "evaluation" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "questions.json").write_text(json.dumps(rows, indent=1, default=str))

    def summarize(subset: list[dict], qtype: str) -> dict:
        n = len(subset)
        outcomes = collections.Counter(r["outcome"] for r in subset)
        answered = [r for r in subset if "score" in r]
        if qtype == "fact":
            metrics = {
                # Denominator is every attempted question: non-answers score zero.
                "strict_accuracy": sum(r["score"]["strict"] for r in answered) / n if n else None,
                "lenient_accuracy": sum(r["score"]["lenient"] for r in answered) / n if n else None,
                "strict_accuracy_when_answered": (
                    sum(r["score"]["strict"] for r in answered) / len(answered)
                    if answered
                    else None
                ),
            }
        else:
            metrics = {
                key: sum(r["score"][key] for r in answered) / n if n else None
                for key in ("precision", "recall", "f1")
            }
            metrics["f1_when_answered"] = (
                sum(r["score"]["f1"] for r in answered) / len(answered) if answered else None
            )
        return {"attempted": n, "answered": len(answered), "outcomes": dict(outcomes), **metrics}

    latencies = sorted(r["total_ms"] for r in rows)
    attempts = [a for r in rows for a in r["attempts"]]
    result = {
        "run_id": run_id,
        "split": args.split,
        "complete": stopped is None and len(rows) == len(questions),
        "stopped": stopped,
        "questions_attempted": len(rows),
        "questions_planned": len(questions),
        "commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip(),
        "configuration": {
            "retrieval": "bm25 (retrieval-baseline-v1)",
            "model": llm.model,
            "prompt_version": PROMPT_VERSION,
            "normalization_version": NORMALIZATION_VERSION,
            "corpus_papers_sha256": sha256(papers_path.read_bytes()),
            "benchmark_sha256": sha256(bench_path.read_bytes()),
        },
        "fact": summarize([r for r in rows if r["type"] == "fact"], "fact"),
        "list": summarize([r for r in rows if r["type"] == "list"], "list"),
        "operations": {
            "provider_attempts": len(attempts),
            "provider_errors": dict(
                collections.Counter(a["error"] for a in attempts if a.get("error"))
            ),
            "validation_failures": sum(1 for a in attempts if a.get("validation")),
            "requests_dispatched_this_run": llm.dispatched,
            "requests_from_cache_this_run": llm.hits,
            "latency_ms_p50": statistics.median(latencies) if latencies else None,
            "latency_ms_max": latencies[-1] if latencies else None,
            "latency_note": "cached completions report their original latency",
        },
    }
    out = REPO / "evaluation" / "results" / f"{run_id}.json"
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("complete", "fact", "list", "operations")}, indent=1))
    print(f"== wrote {out.relative_to(REPO)}; ledger {ledger.used()}/{ledger.ceiling}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
