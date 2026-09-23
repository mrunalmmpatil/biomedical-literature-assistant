"""Seeded selection of the 100-question set and its development/test split
(technical PRD 3.1).

The procedure is fixed before any system result exists, and every step is a
pure function of (eligible questions, groups, fetched papers, seed):

1. Shuffle duplicate groups with the seed. Within a group, shuffle members.
2. Walk the groups in order. Take the first member that has resolvable
   title/abstract evidence and whose type quota is not yet full. At most one
   question per group, so duplicates and paraphrases never appear twice.
3. Within each type, shuffle the selected questions with a derived seed and
   assign the first half to development and the rest to test.

Because each candidate is judged only on its own data, fetching papers for a
longer prefix of the walk cannot change which questions are selected.
"""

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from bla.benchmark.bioasq import BenchmarkQuestion, QuestionType
from bla.contracts import Paper
from bla.corpus import normalize_text


class Split(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"


class EvidenceReason(StrEnum):
    NO_PAPER_RESOLVED = "no_reference_paper_resolved"
    NO_SNIPPET_IN_SOURCE = "no_snippet_found_in_source_text"


@dataclass(frozen=True)
class Evidence:
    resolved_pmids: tuple[str, ...]
    matched_snippets: int
    reason: EvidenceReason | None

    @property
    def ok(self) -> bool:
        return self.reason is None


def check_evidence(question: BenchmarkQuestion, papers: Mapping[str, Paper]) -> Evidence:
    """Resolvable evidence: at least one benchmark snippet appears verbatim
    (after the corpus's own normalization) in the independently fetched title
    or abstract it cites. This proves the answer's support is inside the
    collection's searchable text, not only in BioASQ's copy of it."""
    resolved = tuple(p for p in question.pmids if p in papers)
    if not resolved:
        return Evidence(resolved, 0, EvidenceReason.NO_PAPER_RESOLVED)
    matched = 0
    for s in question.snippets:
        paper = papers.get(s.pmid)
        if paper is None:
            continue
        source = paper.title if s.section == "title" else paper.abstract
        needle = normalize_text(s.text)
        if needle and needle in source:
            matched += 1
    reason = None if matched else EvidenceReason.NO_SNIPPET_IN_SOURCE
    return Evidence(resolved, matched, reason)


def candidate_order(
    questions: Sequence[BenchmarkQuestion], groups: Mapping[str, str], seed: int
) -> list[list[BenchmarkQuestion]]:
    """Groups in seeded order, each a seeded ordering of its members. Inputs
    are sorted first so the result does not depend on file order."""
    rng = random.Random(seed)
    by_group: dict[str, list[BenchmarkQuestion]] = {}
    for q in sorted(questions, key=lambda q: q.id):
        by_group.setdefault(groups[q.id], []).append(q)
    order = sorted(by_group)
    rng.shuffle(order)
    result = []
    for gid in order:
        members = by_group[gid]
        rng.shuffle(members)
        result.append(members)
    return result


@dataclass(frozen=True)
class Selection:
    selected: dict[str, Split]
    examined_groups: int
    rejected: dict[str, EvidenceReason]
    """Questions judged and rejected for evidence before the quotas filled."""


class QuotaNotMet(RuntimeError):
    """Fewer eligible questions than required in the examined prefix. Report
    the limitation or examine more groups; never shrink the set silently."""


def select(
    ordered_groups: Sequence[Sequence[BenchmarkQuestion]],
    papers: Mapping[str, Paper],
    seed: int,
    per_type: int = 50,
) -> Selection:
    if per_type % 2:
        raise ValueError("per_type must be even to split each type in half")
    chosen: dict[QuestionType, list[str]] = {t: [] for t in QuestionType}
    rejected: dict[str, EvidenceReason] = {}
    examined = 0
    for members in ordered_groups:
        if all(len(ids) == per_type for ids in chosen.values()):
            break
        examined += 1
        for q in members:
            if len(chosen[q.type]) == per_type:
                continue
            evidence = check_evidence(q, papers)
            if evidence.ok:
                chosen[q.type].append(q.id)
                break
            rejected[q.id] = evidence.reason
    short = {t.value: per_type - len(ids) for t, ids in chosen.items() if len(ids) < per_type}
    if short:
        raise QuotaNotMet(f"examined {examined} groups; still short {short}")

    split_rng = random.Random(f"{seed}/split")
    selected: dict[str, Split] = {}
    for qtype in QuestionType:
        ids = sorted(chosen[qtype])
        split_rng.shuffle(ids)
        half = per_type // 2
        selected.update({i: Split.DEVELOPMENT for i in ids[:half]})
        selected.update({i: Split.TEST for i in ids[half:]})
    return Selection(selected, examined, rejected)


def shared_pmids(
    questions: Mapping[str, BenchmarkQuestion], selected: Mapping[str, Split]
) -> set[str]:
    """Relevant papers cited by both a development and a test question. Allowed
    in a controlled collection, but disclosed (technical PRD 3.1)."""
    by_split: dict[Split, set[str]] = {Split.DEVELOPMENT: set(), Split.TEST: set()}
    for qid, split in selected.items():
        by_split[split].update(questions[qid].pmids)
    return by_split[Split.DEVELOPMENT] & by_split[Split.TEST]
