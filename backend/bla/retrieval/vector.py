"""Vector retrieval through a Pinecone index with integrated embedding
(llama-text-embed-v2; technical PRD section 5).

Pinecone embeds both records and queries with the index's own model, so
passage and query settings cannot drift apart. The index holds only IDs and
searchable text; titles, abstracts, and metadata shown to users come from the
local frozen snapshot, never from what the vector store returns.

SDK calls mirror scripts/feasibility/check_pinecone.py, verified against a real
account with pinecone 10.0.0 on 2026-09-23. Search hits are `Hit` objects:
read `.score` and `.fields`; `hit["_score"]` raises KeyError in this SDK.
"""

from collections.abc import Callable, Iterable, Sequence
from typing import Any, Protocol

from bla.contracts import Paper, RetrievalHit, RetrievalMethod
from bla.retrieval import MAX_DEPTH, check_depth
from bla.units import MAX_UNIT_CHARS, units

UPSERT_BATCH = 96
"""Pinecone's per-request record limit for integrated-embedding upserts (DOC)."""

MAX_EMBED_CHARS = MAX_UNIT_CHARS
"""Kept as an alias: the unit policy (bla/units.py) guarantees every record
fits, so nothing reaches Pinecone's silent truncation."""


class SearchableIndex(Protocol):
    """The subset of `pinecone.Index` this module uses."""

    def search(self, namespace: str, query: dict[str, Any], fields: list[str]) -> Any: ...

    def upsert_records(self, namespace: str, records: list[dict[str, Any]]) -> Any: ...


class PineconeRetriever:
    method = RetrievalMethod.VECTOR

    def __init__(self, index: SearchableIndex, namespace: str) -> None:
        self._index = index
        self._namespace = namespace

    def search(self, query: str, k: int = 10) -> list[RetrievalHit]:
        check_depth(k)
        # Over-fetch so that, once passages exist, several from one paper
        # cannot crowd out other papers. Fixed ceiling (section 5).
        response = self._index.search(
            namespace=self._namespace,
            query={"inputs": {"text": query}, "top_k": min(k * 3, MAX_DEPTH * 3)},
            fields=["pmid"],
        )
        best: dict[str, tuple[float, str]] = {}
        for hit in response["result"]["hits"]:
            pmid = hit.fields["pmid"]
            score = float(hit.score)
            # A paper scores as its best passage (section 5's initial rule).
            if pmid not in best or score > best[pmid][0]:
                best[pmid] = (score, hit.id)
        ranked = sorted(best.items(), key=lambda item: (-item[1][0], item[0]))[:k]
        return [
            RetrievalHit(pmid=pmid, rank=rank, score=score, method=self.method, unit_id=unit_id)
            for rank, (pmid, (score, unit_id)) in enumerate(ranked, start=1)
        ]


def to_records(paper: Paper) -> list[dict[str, str]]:
    """One record per searchable unit; IDs are unit IDs (bla/units.py)."""
    return [{"_id": u.id, "pmid": u.pmid, "text": u.text} for u in units(paper)]


def upsert_papers(
    index: SearchableIndex,
    namespace: str,
    papers: Iterable[Paper],
    on_batch: Callable[[int], None] | None = None,
) -> int:
    """Upsert every unit in batches. IDs are deterministic, so re-running is
    idempotent. `on_batch` receives the running record count after each batch.
    Returns the number of records upserted."""
    records = [record for paper in papers for record in to_records(paper)]
    oversized = [r["_id"] for r in records if len(r["text"]) > MAX_EMBED_CHARS]
    if oversized:
        raise AssertionError(f"unit policy produced oversized records: {oversized[:5]}")
    done = 0
    for batch in _chunks(records, UPSERT_BATCH):
        index.upsert_records(namespace=namespace, records=list(batch))
        done += len(batch)
        if on_batch:
            on_batch(done)
    return done


def _chunks(items: Sequence, size: int) -> Iterable[Sequence]:
    for start in range(0, len(items), size):
        yield items[start : start + size]
