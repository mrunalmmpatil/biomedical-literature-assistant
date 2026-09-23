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

from collections.abc import Iterable, Sequence
from typing import Any, Protocol

from bla.contracts import Paper, RetrievalHit, RetrievalMethod
from bla.corpus import searchable_text
from bla.retrieval import MAX_DEPTH, check_depth

UPSERT_BATCH = 96
"""Pinecone's per-request record limit for integrated-embedding upserts (DOC)."""

MAX_EMBED_CHARS = 6000
"""Conservative guard for the model's 2,048-token input limit (DOC), assuming
roughly 3 characters per token in dense biomedical text. Longer records are
refused rather than silently truncated; passage splitting for them is a
Milestone 2 decision made against measured lengths."""


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
        best: dict[str, float] = {}
        for hit in response["result"]["hits"]:
            pmid = hit.fields["pmid"]
            score = float(hit.score)
            # A paper scores as its best passage (section 5's initial rule).
            if pmid not in best or score > best[pmid]:
                best[pmid] = score
        ranked = sorted(best.items(), key=lambda item: (-item[1], item[0]))[:k]
        return [
            RetrievalHit(pmid=pmid, rank=rank, score=score, method=self.method)
            for rank, (pmid, score) in enumerate(ranked, start=1)
        ]


def to_record(paper: Paper) -> dict[str, str]:
    """One record per paper for now; passage IDs would be `<pmid>#<n>`."""
    return {
        "_id": paper.pmid,
        "pmid": paper.pmid,
        "text": searchable_text(paper.title, paper.abstract),
    }


def upsert_papers(
    index: SearchableIndex, namespace: str, papers: Iterable[Paper]
) -> tuple[int, list[str]]:
    """Upsert in batches; IDs are PMIDs, so re-running is idempotent.

    Returns (records upserted, PMIDs refused as too long to embed whole).
    """
    records: list[dict[str, str]] = []
    refused: list[str] = []
    for paper in papers:
        record = to_record(paper)
        if len(record["text"]) > MAX_EMBED_CHARS:
            refused.append(paper.pmid)
        else:
            records.append(record)
    for batch in _chunks(records, UPSERT_BATCH):
        index.upsert_records(namespace=namespace, records=list(batch))
    return len(records), refused


def _chunks(items: Sequence, size: int) -> Iterable[Sequence]:
    for start in range(0, len(items), size):
        yield items[start : start + size]
