"""Reciprocal rank fusion over stand-in retrievers."""

import pytest

from bla.contracts import RetrievalHit, RetrievalMethod
from bla.retrieval.hybrid import HybridRetriever


class Fixed:
    def __init__(self, method, pmids, units=None):
        self.method = method
        self.pmids = pmids
        self.units = units or {}
        self.depths = []

    def search(self, query, k=10):
        self.depths.append(k)
        return [
            RetrievalHit(
                pmid=p, rank=i, score=100.0 - i, method=self.method, unit_id=self.units.get(p, p)
            )
            for i, p in enumerate(self.pmids[:k], start=1)
        ]


def test_papers_ranked_well_by_both_methods_rise_to_the_top():
    bm25 = Fixed(RetrievalMethod.BM25, ["1", "2", "3"])
    vector = Fixed(RetrievalMethod.VECTOR, ["3", "2", "4"])
    hits = HybridRetriever({"bm25": bm25, "vector": vector}).search("q", k=4)
    # 3 (ranks 3 and 1) edges out 2 (ranks 2 and 2): 1/63 + 1/61 > 2/62.
    assert [h.pmid for h in hits] == ["3", "2", "1", "4"]
    assert hits[0].score == pytest.approx(1 / 63 + 1 / 61)
    assert hits[1].score == pytest.approx(2 / 62)
    assert all(h.method is RetrievalMethod.HYBRID for h in hits)


def test_fusion_uses_ranks_not_raw_scores():
    bm25 = Fixed(RetrievalMethod.BM25, ["1", "2"])
    vector = Fixed(RetrievalMethod.VECTOR, ["2", "1"])
    hits = HybridRetriever({"bm25": bm25, "vector": vector}).search("q", k=2)
    assert hits[0].score == hits[1].score
    assert [h.pmid for h in hits] == ["1", "2"]  # exact tie broken by PMID


def test_candidates_come_from_the_full_depth_of_each_method():
    bm25 = Fixed(RetrievalMethod.BM25, [str(i) for i in range(1, 61)])
    vector = Fixed(RetrievalMethod.VECTOR, ["99"])
    HybridRetriever({"bm25": bm25, "vector": vector}).search("q", k=10)
    assert bm25.depths == vector.depths == [50]


def test_reported_unit_comes_from_the_better_ranking_method():
    bm25 = Fixed(RetrievalMethod.BM25, ["8", "7"], units={"7": "7#0"})
    vector = Fixed(RetrievalMethod.VECTOR, ["7"], units={"7": "7#3"})
    hits = HybridRetriever({"bm25": bm25, "vector": vector}).search("q", k=2)
    assert next(h for h in hits if h.pmid == "7").unit_id == "7#3"


def test_a_single_retriever_is_refused():
    with pytest.raises(ValueError):
        HybridRetriever({"bm25": Fixed(RetrievalMethod.BM25, [])})
