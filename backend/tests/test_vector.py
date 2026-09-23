"""Vector retrieval against a stand-in index. Hits are the SDK's own `Hit`
type, so a change to its access pattern fails here rather than in production."""

import pytest
from pinecone.models.vectors.search import Hit

from bla.contracts import RetrievalMethod
from bla.retrieval.vector import (
    MAX_EMBED_CHARS,
    UPSERT_BATCH,
    PineconeRetriever,
    to_records,
    upsert_papers,
)
from tests.conftest import paper


class FakeIndex:
    def __init__(self, hits=()):
        self.hits = list(hits)
        self.searches = []
        self.upserts = []

    def search(self, namespace, query, fields):
        self.searches.append((namespace, query, fields))
        return {"result": {"hits": self.hits}}

    def upsert_records(self, namespace, records):
        self.upserts.append((namespace, records))


def hit(record_id, pmid, score):
    return Hit(id_=record_id, score_=score, fields={"pmid": pmid})


def test_hits_become_ranked_papers():
    index = FakeIndex([hit("1001", "1001", 0.9), hit("1002", "1002", 0.7)])
    hits = PineconeRetriever(index, "v1").search("xanthine oxidase", k=5)
    assert [(h.pmid, h.rank, h.method) for h in hits] == [
        ("1001", 1, RetrievalMethod.VECTOR),
        ("1002", 2, RetrievalMethod.VECTOR),
    ]
    namespace, query, fields = index.searches[0]
    assert namespace == "v1"
    assert query["inputs"] == {"text": "xanthine oxidase"}
    assert query["top_k"] == 15  # over-fetch for paper-level uniqueness
    assert fields == ["pmid"]  # display text comes from the local snapshot


def test_passages_collapse_to_their_best_scoring_paper():
    index = FakeIndex(
        [hit("7#0", "7", 0.80), hit("8", "8", 0.85), hit("7#1", "7", 0.95), hit("9", "9", 0.5)]
    )
    hits = PineconeRetriever(index, "v1").search("q", k=2)
    assert [(h.pmid, h.score) for h in hits] == [("7", 0.95), ("8", 0.85)]


def test_no_hits_is_an_empty_result():
    assert PineconeRetriever(FakeIndex(), "v1").search("q") == []


def test_depth_is_bounded():
    with pytest.raises(ValueError, match="depth"):
        PineconeRetriever(FakeIndex(), "v1").search("q", k=0)


def test_record_text_matches_what_bm25_indexes(corpus):
    [record] = to_records(corpus[0])
    assert record["_id"] == record["pmid"] == "1001"
    assert record["text"] == f"{corpus[0].title}\n{corpus[0].abstract}"


def test_upsert_batches_and_splits_overlong_papers_instead_of_truncating():
    papers = [paper(str(i + 1), "t", "abstract") for i in range(UPSERT_BATCH + 5)]
    long = paper("5000", "t", "A sentence of evidence. " * 400)
    index = FakeIndex()
    progress = []
    upserted = upsert_papers(index, "v1", [*papers, long], on_batch=progress.append)
    long_records = [r for _, batch in index.upserts for r in batch if r["pmid"] == "5000"]
    assert len(long_records) > 1
    assert all(len(r["text"]) <= MAX_EMBED_CHARS for r in long_records)
    assert [r["_id"] for r in long_records][:2] == ["5000#0", "5000#1"]
    assert upserted == UPSERT_BATCH + 5 + len(long_records) == progress[-1]
    assert all(ns == "v1" for ns, _ in index.upserts)


def test_search_reports_the_best_unit_of_each_paper():
    index = FakeIndex([hit("7#1", "7", 0.9), hit("7#0", "7", 0.4)])
    [only] = PineconeRetriever(index, "v1").search("q", k=5)
    assert only.unit_id == "7#1"
