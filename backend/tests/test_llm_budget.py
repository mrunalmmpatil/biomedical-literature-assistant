"""Evaluation request accounting: ledger ceiling and completion cache."""

import pytest

from bla.benchmark.llm_budget import CachingLLM, DailyBudgetReached, DailyLedger
from bla.llm import Completion, ProviderUnavailable


class Counting:
    model = "m"

    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def complete(self, system, user, schema_name, schema, timeout=None):
        self.calls += 1
        if self.fail:
            raise ProviderUnavailable("busy")
        return Completion({"n": self.calls}, "m", "m", "p", None, 12.5)


def test_identical_prompts_are_served_from_cache(tmp_path):
    inner = Counting()
    llm = CachingLLM(inner, tmp_path / "c", DailyLedger(tmp_path / "l"))
    first = llm.complete("s", "u", "n", {})
    again = llm.complete("s", "u", "n", {})
    assert inner.calls == 1
    assert again.content == first.content and again.cached and not first.cached
    assert again.latency_ms == 12.5


def test_a_changed_prompt_is_a_cache_miss(tmp_path):
    inner = Counting()
    llm = CachingLLM(inner, tmp_path / "c", DailyLedger(tmp_path / "l"))
    llm.complete("s", "u", "n", {})
    llm.complete("s", "u2", "n", {})
    assert inner.calls == 2


def test_the_ceiling_stops_dispatch(tmp_path):
    inner = Counting()
    llm = CachingLLM(inner, tmp_path / "c", DailyLedger(tmp_path / "l", ceiling=2))
    llm.complete("s", "1", "n", {})
    llm.complete("s", "2", "n", {})
    with pytest.raises(DailyBudgetReached):
        llm.complete("s", "3", "n", {})
    assert inner.calls == 2


def test_failures_count_but_are_not_cached(tmp_path):
    ledger = DailyLedger(tmp_path / "l")
    llm = CachingLLM(Counting(fail=True), tmp_path / "c", ledger)
    with pytest.raises(ProviderUnavailable):
        llm.complete("s", "u", "n", {})
    assert ledger.used() == 1
    assert list((tmp_path / "c").iterdir()) == []
