"""Milestone 3: retrieval-only evaluation on the DEVELOPMENT split.

    cd backend
    uv run --env-file .env python ../scripts/evaluation/run_retrieval.py

Runs BM25 and Pinecone vector retrieval with the benchmark question text as
the only query input: no reference answers, snippets, or labels reach either
retriever. Never calls the generation model (technical PRD 5).

The held-out test split is not accepted here. It is run once, in Milestone 6,
under a configuration frozen beforehand (technical PRD 9.1).

Outputs:
    evaluation/runs/<run>/questions.jsonl   per question: retrieved and missed PMIDs (untracked)
    evaluation/results/<run>.json           aggregate metrics and run metadata (tracked)
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
import time
from datetime import UTC, datetime
from importlib.metadata import version

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from pinecone import Pinecone

from bla.benchmark.bioasq import BenchmarkQuestion
from bla.benchmark.metrics import mean, score
from bla.ingest.snapshot import read_papers, sha256
from bla.retrieval.bm25 import BM25Retriever
from bla.retrieval.tokenize import TOKENIZER_VERSION
from bla.retrieval.vector import PineconeRetriever
from bla.units import UNIT_POLICY_VERSION

DEPTH = 10


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.strip()


def summarize(rows: list[dict], method: str) -> dict:
    scored = [r[method] for r in rows if r[method]["score"] is not None]
    latencies = sorted(r[method]["latency_ms"] for r in rows)
    return {
        "questions_scored": len(scored),
        "recall_at_5": mean([s["score"]["recall_at_5"] for s in scored]),
        "recall_at_10": mean([s["score"]["recall_at_10"] for s in scored]),
        "mrr_at_10": mean([s["score"]["reciprocal_rank_at_10"] for s in scored]),
        "any_relevant_in_top_10": sum(
            1 for s in scored if s["score"]["first_relevant_rank"] is not None
        ),
        "latency_ms": {
            "p50": round(statistics.median(latencies), 1),
            "p95": round(latencies[max(0, round(0.95 * len(latencies)) - 1)], 1),
            "max": round(latencies[-1], 1),
        },
    }


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--benchmark", default="bioasq14b-v1")
    p.add_argument(
        "--split",
        default="development",
        choices=["development"],
        help="only the development split; the test split is Milestone 6",
    )
    args = p.parse_args()

    bench_path = REPO / "data" / "benchmark" / args.benchmark / "questions.jsonl"
    papers_path = REPO / "data" / "corpus" / args.benchmark / "papers.jsonl"
    index_manifest = json.loads(
        (
            REPO
            / "evaluation"
            / "manifests"
            / f"index-{args.benchmark}.u{UNIT_POLICY_VERSION}.json"
        ).read_text()
    )

    questions = []
    for line in bench_path.read_text().splitlines():
        record = json.loads(line)
        if record.pop("split") == args.split:
            questions.append(BenchmarkQuestion.model_validate(record))
    if len(questions) != 50:
        raise SystemExit(f"expected 50 {args.split} questions, found {len(questions)}")

    papers = read_papers(papers_path)
    in_collection = {paper.pmid for paper in papers}
    started = time.monotonic()
    bm25 = BM25Retriever(papers)
    bm25_build_s = time.monotonic() - started
    index = Pinecone(api_key=os.environ["PINECONE_API_KEY"]).Index(index_manifest["index"])
    retrievers = {
        "bm25": bm25,
        "vector": PineconeRetriever(index, index_manifest["namespace"]),
    }

    run_id = f"retrieval-{args.split}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    rows = []
    for q in sorted(questions, key=lambda q: q.id):
        relevant = [p for p in q.pmids if p in in_collection]
        row = {
            "id": q.id,
            "type": q.type.value,
            "relevant_in_collection": relevant,
            "reference_missing_from_collection": [p for p in q.pmids if p not in in_collection],
        }
        for name, retriever in retrievers.items():
            t0 = time.perf_counter()
            hits = retriever.search(q.body, k=DEPTH)  # question text only
            latency = (time.perf_counter() - t0) * 1000
            retrieved = [h.pmid for h in hits]
            s = score(retrieved, relevant)
            row[name] = {
                "retrieved": retrieved,
                "units": [h.unit_id for h in hits],
                "hits": [p for p in retrieved if p in set(relevant)],
                "missed": [p for p in relevant if p not in set(retrieved)],
                "latency_ms": round(latency, 1),
                "score": s.__dict__ if s else None,
            }
        rows.append(row)
        print(
            f"  {q.id} {q.type.value:<4} rel={len(relevant):>2}  "
            + "  ".join(
                f"{m} R@10={row[m]['score']['recall_at_10']:.2f}" if row[m]["score"] else f"{m} -"
                for m in retrievers
            )
        )

    run_dir = REPO / "evaluation" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "questions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    by_type = collections.defaultdict(list)
    for r in rows:
        by_type[r["type"]].append(r)
    result = {
        "run_id": run_id,
        "split": args.split,
        "questions": len(rows),
        "depth": DEPTH,
        "query_input": "benchmark question text only",
        "commit": git("rev-parse", "HEAD"),
        "working_tree_clean": git("status", "--porcelain") == "",
        "benchmark": {"name": args.benchmark, "questions_sha256": sha256(bench_path.read_bytes())},
        "collection": {
            "papers_sha256": sha256(papers_path.read_bytes()),
            "papers": len(papers),
            "index": index_manifest,
        },
        "settings": {
            "bm25": {"k1": bm25.k1, "b": bm25.b, "tokenizer_version": TOKENIZER_VERSION},
            "unit_policy_version": UNIT_POLICY_VERSION,
            "paper_aggregation": "best unit score",
            "vector_top_k_requested": DEPTH * 3,
        },
        "dependencies": {pkg: version(pkg) for pkg in ("pinecone", "pydantic", "httpx")},
        "bm25_build_seconds": round(bm25_build_s, 2),
        "questions_with_missing_references": sum(
            1 for r in rows if r["reference_missing_from_collection"]
        ),
        "methods": {m: summarize(rows, m) for m in retrievers},
        "by_type": {t: {m: summarize(rs, m) for m in retrievers} for t, rs in by_type.items()},
    }
    out = REPO / "evaluation" / "results" / f"{run_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["methods"], indent=1))
    print(json.dumps(result["by_type"], indent=1))
    print(f"== wrote {out.relative_to(REPO)} and {run_dir.relative_to(REPO)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
