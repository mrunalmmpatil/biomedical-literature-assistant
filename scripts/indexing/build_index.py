"""Milestone 3: load a frozen collection into Pinecone (technical PRD 3.3, 5).

    cd backend
    uv run --env-file .env python ../scripts/indexing/build_index.py bioasq14b-v1

- One index, `bla-collection`, with integrated llama-text-embed-v2
  (1024 dimensions, cosine), as verified in Milestone 1.
- One namespace per collection version: `<corpus>.u<unit policy>`. A changed
  corpus or unit policy is a new namespace, never an in-place edit.
- Resumable and cheap to resume: IDs already stored are listed (read units)
  and skipped, so an interrupted run never re-embeds (embedding tokens).
- Paced under the Starter limit of 250,000 embedding tokens per minute
  (measured 2026-09-23), estimating 3 characters per token. A 429 that still
  gets through waits for the server's Retry-After; other errors stop the run.
- The version is published only after the stored count matches the unit count
  and title sanity queries pass.

Writes evaluation/manifests/index-<namespace>.json (tracked).
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import random
import sys
import time
from collections import deque

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from pinecone import Pinecone
from pinecone.errors.exceptions import RateLimitError, ServiceError

from bla.ingest.snapshot import read_papers, sha256
from bla.retrieval.vector import UPSERT_BATCH, PineconeRetriever, to_records
from bla.units import UNIT_POLICY_VERSION

INDEX_NAME = "bla-collection"
MODEL = "llama-text-embed-v2"
DIMENSION = 1024
METRIC = "cosine"
SANITY_QUERIES = 5
SANITY_SEED = 3
TOKENS_PER_MINUTE = 200_000
"""Headroom under the measured 250,000/minute Starter limit."""


def namespace_for(corpus: str) -> str:
    return f"{corpus}.u{UNIT_POLICY_VERSION}"


def with_backoff(call, what: str, attempts: int = 6):
    """The SDK already retries 429s briefly; this waits out a spent minute."""
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except (RateLimitError, ServiceError) as exc:
            if attempt == attempts:
                raise
            delay = getattr(exc, "retry_after", None) or min(90, 15 * attempt)
            print(f"  {what}: {exc.__class__.__name__}; retrying in {delay:.0f}s")
            time.sleep(delay)
    raise AssertionError("unreachable")


class TokenPacer:
    """Rolling one-minute budget of estimated embedding tokens."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self.sent: deque[tuple[float, int]] = deque()

    def wait_for(self, tokens: int) -> None:
        while True:
            now = time.monotonic()
            while self.sent and now - self.sent[0][0] >= 60:
                self.sent.popleft()
            if sum(t for _, t in self.sent) + tokens <= self.per_minute:
                self.sent.append((now, tokens))
                return
            time.sleep(max(0.5, 60 - (now - self.sent[0][0])))


def stored_ids(index, namespace: str) -> set[str]:
    ids: set[str] = set()
    for page in index.list(namespace=namespace):
        ids.update(page if isinstance(page, list) else [v.id for v in page.vectors])
    return ids


def namespace_count(index, namespace: str) -> int:
    stats = index.describe_index_stats().to_dict()
    return stats.get("namespaces", {}).get(namespace, {}).get("vector_count", 0)


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("corpus", help="snapshot name under data/corpus/")
    args = p.parse_args()

    corpus_dir = REPO / "data" / "corpus" / args.corpus
    papers_path = corpus_dir / "papers.jsonl"
    papers = read_papers(papers_path)
    records = [record for paper in papers for record in to_records(paper)]
    namespace = namespace_for(args.corpus)
    print(f"== {len(papers)} papers -> {len(records)} records in namespace {namespace!r}")

    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    if not pc.has_index(INDEX_NAME):
        print(f"== creating index {INDEX_NAME!r}")
        pc.create_index_for_model(
            name=INDEX_NAME,
            cloud="aws",
            region="us-east-1",
            embed={
                "model": MODEL,
                "field_map": {"text": "text"},
                "metric": METRIC,
                "dimension": DIMENSION,
            },
        )
    index = pc.Index(INDEX_NAME)

    have = stored_ids(index, namespace)
    todo = [r for r in records if r["_id"] not in have]
    print(f"== {len(have)} already stored; {len(todo)} to embed")
    started = time.monotonic()
    pacer = TokenPacer(TOKENS_PER_MINUTE)
    for start in range(0, len(todo), UPSERT_BATCH):
        batch = todo[start : start + UPSERT_BATCH]
        pacer.wait_for(sum(len(r["text"]) for r in batch) // 3 + 1)
        with_backoff(
            lambda b=batch: index.upsert_records(namespace=namespace, records=b),
            f"upsert {start // UPSERT_BATCH + 1}",
        )
        done = start + len(batch)
        if done % (UPSERT_BATCH * 5) < UPSERT_BATCH or done == len(todo):
            print(f"  upserted {done}/{len(todo)} ({time.monotonic() - started:.0f}s)")

    print("== waiting for the stored count to match")
    for _ in range(60):
        count = namespace_count(index, namespace)
        if count == len(records):
            break
        time.sleep(5)
    else:
        raise SystemExit(f"count mismatch: stored {count}, expected {len(records)}; not published")
    print(f"  stored {count} records")

    # Sanity: a paper's own title should retrieve that paper. Titles are
    # collection text, not benchmark questions or answers.
    rng = random.Random(SANITY_SEED)
    sample = rng.sample(papers, SANITY_QUERIES)
    retriever = PineconeRetriever(index, namespace)
    sanity = []
    for paper in sample:
        hits = with_backoff(lambda t=paper.title: retriever.search(t, k=3), "sanity query")
        rank = next((h.rank for h in hits if h.pmid == paper.pmid), None)
        sanity.append({"pmid": paper.pmid, "rank_in_top3": rank})
        print(f"  title of {paper.pmid} -> rank {rank}")
    if any(s["rank_in_top3"] is None for s in sanity):
        raise SystemExit("sanity queries failed; collection version not published")

    manifest = {
        "index": INDEX_NAME,
        "namespace": namespace,
        "model": MODEL,
        "dimension": DIMENSION,
        "metric": METRIC,
        "unit_policy_version": UNIT_POLICY_VERSION,
        "corpus": args.corpus,
        "papers_sha256": sha256(papers_path.read_bytes()),
        "papers": len(papers),
        "records": len(records),
        "record_ids_sha256": sha256("\n".join(sorted(r["_id"] for r in records)).encode()),
        "embedded_this_run": len(todo),
        "sanity_queries": sanity,
        "published_on": time.strftime("%Y-%m-%d"),
    }
    out = REPO / "evaluation" / "manifests" / f"index-{namespace}.json"
    out.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"== published {namespace}; wrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
