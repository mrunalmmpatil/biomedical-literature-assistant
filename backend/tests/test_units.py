"""Searchable-unit policy: whole papers unless overlong, never truncated."""

import pytest

from bla.units import MAX_UNIT_CHARS, units
from tests.conftest import paper


def test_ordinary_paper_is_one_unit_named_by_its_pmid(corpus):
    [unit] = units(corpus[0])
    assert unit.id == unit.pmid == "1001"
    assert unit.text == f"{corpus[0].title}\n{corpus[0].abstract}"
    assert (unit.start, unit.end) == (0, len(corpus[0].abstract))


def test_overlong_paper_splits_on_sentences_and_repeats_the_title():
    sentences = [f"Finding number {i} was observed in the cohort." for i in range(300)]
    p = paper("42", "Long review", " ".join(sentences))
    parts = units(p)
    assert len(parts) > 1
    assert [u.id for u in parts] == [f"42#{n}" for n in range(len(parts))]
    for u in parts:
        assert len(u.text) <= MAX_UNIT_CHARS
        assert u.text == f"{p.title}\n{p.abstract[u.start : u.end]}"
        assert p.abstract[u.start : u.end].endswith(".")  # a sentence boundary


def test_passages_cover_the_whole_abstract_without_loss():
    p = paper("42", "t", " ".join(f"Sentence {i} ends here." for i in range(800)))
    parts = units(p)
    rejoined = " ".join(p.abstract[u.start : u.end] for u in parts)
    assert rejoined == p.abstract


def test_a_sentence_longer_than_the_budget_is_split_not_truncated():
    p = paper("42", "t", "word " * 3000)
    parts = units(p)
    assert all(len(u.text) <= MAX_UNIT_CHARS for u in parts)
    assert sum(len(p.abstract[u.start : u.end].split()) for u in parts) == 3000


def test_a_title_leaving_no_room_for_text_is_refused():
    p = paper("42", "t" * 100, "Some abstract text. " * 20)
    with pytest.raises(ValueError, match="no room"):
        units(p, max_chars=250)
