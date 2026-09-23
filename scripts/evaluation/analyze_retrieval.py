"""Paired analysis of a development retrieval run (Milestone 3).

    cd backend
    uv run --env-file .env python ../scripts/evaluation/analyze_retrieval.py <run_id>

Adds what the headline means cannot show on 50 questions:

- per-question wins, ties, and losses between the methods;
- a paired bootstrap 95% interval for each metric difference (vector - BM25);
- the Recall@10 ceiling: a question with R relevant papers can reach at most
  min(10, R) / R, so recall is also reported against that ceiling;
- miss depth: re-querying at depth 50 shows whether a missed paper ranked
  11-50 (a depth problem) or not at all (a ranking or vocabulary problem).

Writes evaluation/results/<run_id>.analysis.json (tracked; no PMIDs or text).
"""

from __future__ import annotations

import collections
import json
import os
import pathlib
import random
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from pinecone import Pinecone

from bla.benchmark.bioasq import BenchmarkQuestion
from bla.ingest.snapshot import read_papers
from bla.retrieval import MAX_DEPTH
from bla.retrieval.bm25 import BM25Retriever
from bla.retrieval.vector import PineconeRetriever

METRICS = ("recall_at_5", "recall_at_10", "reciprocal_rank_at_10")
BOOTSTRAP = 10_000
SEED = 20260923


def bootstrap_ci(diffs: list[float]) -> tuple[float, float]:
    rng = random.Random(SEED)
    n = len(diffs)
    means = sorted(sum(rng.choice(diffs) for _ in range(n)) / n for _ in range(BOOTSTRAP))
    return means[int(0.025 * BOOTSTRAP)], means[int(0.975 * BOOTSTRAP) - 1]


def main() -> int:
    run_id = sys.argv[1]
    result = json.loads((REPO / "evaluation" / "results" / f"{run_id}.json").read_text())
    rows = [
        json.loads(line)
        for line in (REPO / "evaluation" / "runs" / run_id / "questions.jsonl")
        .read_text()
        .splitlines()
    ]
    rows = [r for r in rows if r["bm25"]["score"] and r["vector"]["score"]]

    paired = {}
    for metric in METRICS:
        diffs = [r["vector"]["score"][metric] - r["bm25"]["score"][metric] for r in rows]
        wins = collections.Counter(
            "vector" if d > 1e-12 else "bm25" if d < -1e-12 else "tie" for d in diffs
        )
        low, high = bootstrap_ci(diffs)
        paired[metric] = {
            "mean_difference_vector_minus_bm25": sum(diffs) / len(diffs),
            "bootstrap_95ci": [low, high],
            "questions_better": {
                "vector": wins["vector"],
                "bm25": wins["bm25"],
                "tie": wins["tie"],
            },
        }

    ceiling = {}
    for method in ("bm25", "vector"):
        fractions = []
        for r in rows:
            relevant = len(r["relevant_in_collection"])
            cap = min(10, relevant) / relevant
            fractions.append(r[method]["score"]["recall_at_10"] / cap)
        ceiling[method] = sum(fractions) / len(fractions)
    ceiling["mean_ceiling"] = sum(
        min(10, len(r["relevant_in_collection"])) / len(r["relevant_in_collection"]) for r in rows
    ) / len(rows)
    relevant_counts = sorted(len(r["relevant_in_collection"]) for r in rows)

    # Miss depth: rerun at the maximum depth with the same question text.
    questions = {}
    for line in (
        (REPO / "data" / "benchmark" / result["benchmark"]["name"] / "questions.jsonl")
        .read_text()
        .splitlines()
    ):
        record = json.loads(line)
        record.pop("split")
        questions[record["id"]] = BenchmarkQuestion.model_validate(record)
    papers = read_papers(REPO / "data" / "corpus" / result["benchmark"]["name"] / "papers.jsonl")
    index_info = result["collection"]["index"]
    retrievers = {
        "bm25": BM25Retriever(papers),
        "vector": PineconeRetriever(
            Pinecone(api_key=os.environ["PINECONE_API_KEY"]).Index(index_info["index"]),
            index_info["namespace"],
        ),
    }
    depth = {}
    for method, retriever in retrievers.items():
        buckets = collections.Counter()
        for r in rows:
            ranked = [h.pmid for h in retriever.search(questions[r["id"]].body, k=MAX_DEPTH)]
            position = {pmid: i for i, pmid in enumerate(ranked, start=1)}
            for pmid in r[method]["missed"]:
                rank = position.get(pmid)
                buckets[
                    "11-20" if rank and rank <= 20 else "21-50" if rank else "not_in_top_50"
                ] += 1
        depth[method] = {"missed_relevant_papers": sum(buckets.values()), **dict(buckets)}

    both_hits = sum(
        len(set(r["bm25"]["hits"]) | set(r["vector"]["hits"])) / len(r["relevant_in_collection"])
        for r in rows
    ) / len(rows)

    analysis = {
        "run_id": run_id,
        "questions": len(rows),
        "paired": paired,
        "relevant_papers_per_question": {
            "min": relevant_counts[0],
            "median": relevant_counts[len(relevant_counts) // 2],
            "max": relevant_counts[-1],
            "questions_over_10": sum(1 for n in relevant_counts if n > 10),
        },
        "recall_at_10_vs_ceiling": ceiling,
        "miss_depth": depth,
        "recall_at_10_union_of_methods": both_hits,
        "bootstrap": {"resamples": BOOTSTRAP, "seed": SEED},
    }
    out = REPO / "evaluation" / "results" / f"{run_id}.analysis.json"
    out.write_text(json.dumps(analysis, indent=2) + "\n")
    print(json.dumps(analysis, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
