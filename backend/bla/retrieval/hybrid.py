"""Hybrid retrieval by reciprocal rank fusion (technical PRD 5, optional).

Configuration retrieval-hybrid-v2, registered before it was run
(evaluation/configs/retrieval-hybrid-v2.json). Fusion uses ranks only, so a
BM25 score and a cosine similarity are never compared or added (section 4).
The fused score is a ranking device, not a confidence.
"""

from collections.abc import Mapping

from bla.contracts import RetrievalHit, RetrievalMethod
from bla.retrieval import MAX_DEPTH, Retriever, check_depth

RRF_K = 60
"""Cormack, Clarke and Buettcher (SIGIR 2009). Not tuned on project data."""

CANDIDATE_DEPTH = MAX_DEPTH


class HybridRetriever:
    method = RetrievalMethod.HYBRID

    def __init__(
        self,
        retrievers: Mapping[str, Retriever],
        rrf_k: int = RRF_K,
        candidate_depth: int = CANDIDATE_DEPTH,
    ) -> None:
        if len(retrievers) < 2:
            raise ValueError("fusion needs at least two retrievers")
        self._retrievers = dict(retrievers)
        self.rrf_k = rrf_k
        self.candidate_depth = check_depth(candidate_depth)

    def search(self, query: str, k: int = 10) -> list[RetrievalHit]:
        check_depth(k)
        fused: dict[str, float] = {}
        best: dict[str, tuple[int, str | None]] = {}  # pmid -> (best rank, its unit)
        for retriever in self._retrievers.values():
            for hit in retriever.search(query, k=self.candidate_depth):
                fused[hit.pmid] = fused.get(hit.pmid, 0.0) + 1 / (self.rrf_k + hit.rank)
                if hit.pmid not in best or hit.rank < best[hit.pmid][0]:
                    best[hit.pmid] = (hit.rank, hit.unit_id)
        ranked = sorted(fused.items(), key=lambda item: (-item[1], item[0]))[:k]
        return [
            RetrievalHit(
                pmid=pmid,
                rank=rank,
                score=score,
                method=self.method,
                unit_id=best[pmid][1],
            )
            for rank, (pmid, score) in enumerate(ranked, start=1)
        ]
