import pytest

from bla.contracts import RetrievalMethod
from bla.retrieval.bm25 import BM25Retriever
from bla.retrieval.tokenize import tokenize
from tests.conftest import paper


def top_pmids(retriever, query, k=10):
    return [hit.pmid for hit in retriever.search(query, k)]


def test_tokenizer_keeps_biomedical_identifiers_whole():
    tokens = tokenize("BRCA1, p53 and COVID-19 in the 5-HT2A receptor")
    assert {"brca1", "p53", "covid19", "5ht2a"} <= set(tokens)
    assert "the" not in tokens


def test_tokenizer_keeps_greek_letters():
    assert "tnfα" in tokenize("TNF-α")


def test_relevant_paper_ranks_first(corpus):
    bm25 = BM25Retriever(corpus)
    hits = bm25.search("Which drug inhibits xanthine oxidase?")
    assert hits[0].pmid == "1001"
    assert hits[0].rank == 1
    assert hits[0].method is RetrievalMethod.BM25


def test_hyphenated_and_joined_identifiers_match_each_other(corpus):
    bm25 = BM25Retriever(corpus)
    assert top_pmids(bm25, "IL6 levels in sepsis")[0] == "1003"


def test_no_matching_terms_returns_nothing_rather_than_padding(corpus):
    assert BM25Retriever(corpus).search("photosynthesis in C4 grasses") == []


def test_results_are_unique_ranked_and_bounded(corpus):
    hits = BM25Retriever(corpus).search("cancer diabetes gout sepsis", k=3)
    assert len(hits) == 3
    assert len({h.pmid for h in hits}) == 3
    assert [h.rank for h in hits] == [1, 2, 3]
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)


def test_equal_scores_rank_deterministically_by_pmid():
    twins = [paper("2002", "Same", "identical text"), paper("2001", "Same", "identical text")]
    assert top_pmids(BM25Retriever(twins), "identical") == ["2001", "2002"]


def test_duplicate_pmids_are_rejected(corpus):
    with pytest.raises(ValueError, match="duplicate PMID"):
        BM25Retriever([*corpus, corpus[0]])


@pytest.mark.parametrize("k", [0, 51])
def test_depth_is_bounded(corpus, k):
    with pytest.raises(ValueError, match="depth"):
        BM25Retriever(corpus).search("gout", k)


def test_empty_corpus_returns_nothing():
    assert BM25Retriever([]).search("gout") == []
