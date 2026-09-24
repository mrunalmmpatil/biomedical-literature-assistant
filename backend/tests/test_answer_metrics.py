"""Answer scoring on hand-built references (not BioASQ items)."""

import pytest

from bla.benchmark.answer_metrics import normalize_answer, score_fact, score_list


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("TNF-α", "tnf alpha"),
        ("The Xanthine Oxidase", "xanthine oxidase"),
        ("IL-6", "IL6".replace("6", " 6")),
        ("5-HT2A receptor.", "5 ht2a receptor"),
    ],
)
def test_normalization_equates_surface_variants(a, b):
    assert normalize_answer(a) == normalize_answer(b)


def test_normalization_keeps_distinct_identifiers_distinct():
    assert normalize_answer("IL-6") != normalize_answer("IL-8")


def test_fact_strict_uses_the_first_item_lenient_any():
    reference = [["xanthine oxidase", "XO"]]
    assert score_fact(["XO"], reference).strict
    s = score_fact(["urate", "xanthine oxidase"], reference)
    assert not s.strict and s.lenient
    assert not score_fact([], reference).lenient


def test_list_matching_is_one_to_one():
    reference = [["IL-6"], ["TNF-alpha", "TNF"], ["IL-8"]]
    s = score_list(["IL-6", "IL 6", "TNF", "IL-10"], reference)
    assert s.matched == 2
    assert s.precision == pytest.approx(2 / 3)  # "IL-6" and "IL 6" are one prediction
    assert s.recall == pytest.approx(2 / 3)
    assert s.f1 == pytest.approx(2 / 3)


def test_empty_list_answer_scores_zero():
    s = score_list([], [["a"]])
    assert (s.precision, s.recall, s.f1) == (0.0, 0.0, 0.0)
