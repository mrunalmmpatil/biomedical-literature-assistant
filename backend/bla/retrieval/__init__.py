"""Retrieval behind one interface (technical PRD section 5).

BM25 and vector search implement the same protocol over the same normalized
papers, so the evaluation runner and the API can switch methods without
touching anything else. Retrieval never calls the generation model.
"""

from typing import Protocol

from bla.contracts import RetrievalHit, RetrievalMethod

MAX_DEPTH = 50
"""Fixed ceiling on requested depth; the starting default is 10 (section 8.1)."""


class Retriever(Protocol):
    method: RetrievalMethod

    def search(self, query: str, k: int = 10) -> list[RetrievalHit]:
        """Return up to `k` unique papers, best first. Fewer, or none, is a
        valid result: an empty list is evidence of absence in this collection
        only, and is handled as insufficient evidence upstream."""
        ...


def check_depth(k: int) -> int:
    if not 1 <= k <= MAX_DEPTH:
        raise ValueError(f"retrieval depth must be between 1 and {MAX_DEPTH}, got {k}")
    return k
