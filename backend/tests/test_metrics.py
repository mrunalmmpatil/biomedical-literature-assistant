"""Paper-level retrieval metrics on hand-computed cases."""

import pytest

from bla.benchmark.metrics import dedupe, score


def test_recall_and_reciprocal_rank():
    s = score(["9", "1", "8", "2", "7", "3"], {"1", "2", "3", "4"})
    assert s.recall_at_5 == pytest.approx(2 / 4)
    assert s.recall_at_10 == pytest.approx(3 / 4)
    assert s.reciprocal_rank_at_10 == pytest.approx(1 / 2)
    assert s.first_relevant_rank == 2


def test_no_relevant_paper_in_the_first_ten_scores_zero_mrr():
    s = score([str(i) for i in range(100, 110)] + ["1"], {"1"})
    assert s.reciprocal_rank_at_10 == 0.0
    assert s.first_relevant_rank is None
    assert s.recall_at_10 == 0.0


def test_duplicates_are_removed_before_ranking():
    assert dedupe(["1", "1", "2", "1"]) == ["1", "2"]
    s = score(["9", "9", "9", "9", "9", "1"], {"1"})
    assert s.first_relevant_rank == 2
    assert s.recall_at_5 == 1.0


def test_no_relevant_paper_in_the_collection_is_not_scored():
    assert score(["1", "2"], set()) is None
