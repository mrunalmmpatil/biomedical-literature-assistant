"""BioASQ Task B records: loading, normalization, structural eligibility, and
duplicate grouping (technical PRD 3.1).

Everything here is decided from question structure and relevant-paper IDs
before any split exists. Answer *content* is never inspected to decide
eligibility: an answer must exist and be well formed, nothing more.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from bla.contracts import Pmid

RULES_VERSION = "1"
"""Bump whenever an eligibility or grouping rule changes: a manifest built
under one rules version is not comparable with one built under another."""

MAX_QUESTION_CHARS = 2000
"""The application's initial-question limit (technical PRD 8.1). A benchmark
question the application would reject is not a fair test item."""

_PMID_URL = re.compile(
    r"^https?://(?:www\.ncbi\.nlm\.nih\.gov/pubmed|pubmed\.ncbi\.nlm\.nih\.gov)/(\d+)/?$"
)
_TOKEN = re.compile(r"[a-z0-9]+")


class QuestionType(StrEnum):
    """BioASQ says "factoid"; the planning documents say "fact". Same type."""

    FACT = "fact"
    LIST = "list"


_TYPES = {"factoid": QuestionType.FACT, "list": QuestionType.LIST}


class Snippet(BaseModel):
    """A benchmark-provided evidence span. An evaluation reference only: it is
    never indexed or shown to a model (technical PRD 3.2)."""

    model_config = ConfigDict(frozen=True)

    pmid: Pmid
    section: Literal["title", "abstract"]
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    text: str


class BenchmarkQuestion(BaseModel):
    """Evaluation-only record (technical PRD section 4, "Benchmark question").

    `answers` holds one entry per expected answer item; each entry lists the
    accepted surface variants. A fact question has exactly one item.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    type: QuestionType
    body: str
    answers: list[list[str]]
    ideal_answers: list[str]
    pmids: list[Pmid]
    snippets: list[Snippet]


class Reason(StrEnum):
    """Why a question is not structurally eligible. Checked in this order; the
    first failure is the one recorded, so counts partition the input."""

    OUT_OF_SCOPE_TYPE = "out_of_scope_type"
    TOO_LONG = "question_too_long"
    NO_ANSWER = "no_exact_answer"
    MALFORMED_ANSWER = "malformed_exact_answer"
    NO_DOCUMENTS = "no_documents"
    UNPARSEABLE_DOCUMENT = "unparseable_document_url"
    NO_SNIPPETS = "no_snippets"
    FULL_TEXT_SNIPPET = "full_text_snippet"
    SNIPPET_OUTSIDE_DOCUMENTS = "snippet_document_not_listed"
    MALFORMED_SNIPPET = "malformed_snippet"


@dataclass(frozen=True)
class Ineligible:
    id: str
    type: str
    reason: Reason


def pmid_from_url(url: str) -> str | None:
    """BioASQ lists documents as URLs in two historical formats."""
    match = _PMID_URL.match(url.strip())
    return match.group(1) if match else None


def normalize(raw: dict) -> BenchmarkQuestion | Ineligible:
    """One raw BioASQ record to a benchmark question, or the first reason it is
    not structurally eligible.

    Full-text snippets exclude the whole question rather than being dropped:
    this project only has titles and abstracts, and a question whose reference
    evidence partly lies in full text may be unanswerable here.
    """
    qid, raw_type = raw["id"], raw["type"]

    def no(reason: Reason) -> Ineligible:
        return Ineligible(qid, raw_type, reason)

    qtype = _TYPES.get(raw_type)
    if qtype is None:
        return no(Reason.OUT_OF_SCOPE_TYPE)
    body = raw["body"].strip()
    if len(body) > MAX_QUESTION_CHARS:
        return no(Reason.TOO_LONG)

    exact = raw.get("exact_answer")
    if not exact:
        return no(Reason.NO_ANSWER)
    answers = _answers(qtype, exact)
    if answers is None:
        return no(Reason.MALFORMED_ANSWER)

    urls = raw.get("documents") or []
    if not urls:
        return no(Reason.NO_DOCUMENTS)
    pmids = [pmid_from_url(u) for u in urls]
    if any(p is None for p in pmids):
        return no(Reason.UNPARSEABLE_DOCUMENT)
    pmids = list(dict.fromkeys(pmids))

    raw_snippets = raw.get("snippets") or []
    if not raw_snippets:
        return no(Reason.NO_SNIPPETS)
    # Each rule is applied across all snippets before the next, so the recorded
    # reason does not depend on snippet order.
    if any(
        s["beginSection"] != s["endSection"] or s["beginSection"] not in ("title", "abstract")
        for s in raw_snippets
    ):
        return no(Reason.FULL_TEXT_SNIPPET)
    snippet_pmids = [pmid_from_url(s["document"]) for s in raw_snippets]
    if any(p is None or p not in pmids for p in snippet_pmids):
        return no(Reason.SNIPPET_OUTSIDE_DOCUMENTS)
    if any(
        s["offsetInBeginSection"] < 0
        or s["offsetInEndSection"] < s["offsetInBeginSection"]
        or not s["text"].strip()
        for s in raw_snippets
    ):
        return no(Reason.MALFORMED_SNIPPET)
    snippets = [
        Snippet(
            pmid=pmid,
            section=s["beginSection"],
            start=s["offsetInBeginSection"],
            end=s["offsetInEndSection"],
            text=s["text"],
        )
        for s, pmid in zip(raw_snippets, snippet_pmids, strict=True)
    ]

    ideal = raw.get("ideal_answer") or []
    return BenchmarkQuestion(
        id=qid,
        type=qtype,
        body=body,
        answers=answers,
        ideal_answers=[ideal] if isinstance(ideal, str) else list(ideal),
        pmids=pmids,
        snippets=snippets,
    )


def _answers(qtype: QuestionType, exact: object) -> list[list[str]] | None:
    """Fact: a flat list of synonyms for one item. List: a list of items, each
    a list of synonyms. Anything else, or any blank variant, is malformed."""
    if not isinstance(exact, list):
        return None
    if qtype is QuestionType.FACT:
        items = [exact] if all(isinstance(v, str) for v in exact) else None
    else:
        items = exact if all(isinstance(i, list) for i in exact) else None
    if not items:
        return None
    cleaned = []
    for item in items:
        variants = [v.strip() for v in item if isinstance(v, str) and v.strip()]
        if len(variants) != len(item) or not variants:
            return None
        cleaned.append(variants)
    return cleaned


# --- Duplicate and paraphrase grouping ---------------------------------------

TEXT_SIMILAR = 0.5
DOCS_SIMILAR = 0.3
DOCS_SAME_SOURCE = 0.6
"""Grouping thresholds, set 2026-09-23 by reading sampled pairs of question
text (no answers). BioASQ has many templated questions that differ only in the
named entity ("Which molecule is targeted by X?"), so word overlap alone groups
unrelated questions. A pair is grouped when:

- the question token sets are identical; or
- wording overlaps (Jaccard >= 0.5) and relevant papers overlap (>= 0.3),
  which catches paraphrases ("methods" / "tools" for the same topic); or
- relevant papers largely coincide (>= 0.6), which also groups distinct
  questions built on the same source paper.

The last clause is deliberately conservative: it keeps question families that
share evidence from straddling the development/test split."""


def tokens(text: str) -> frozenset[str]:
    return frozenset(_TOKEN.findall(text.lower()))


def _jaccard(a: frozenset, b: frozenset) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def related(a: BenchmarkQuestion, b: BenchmarkQuestion) -> bool:
    ta, tb = tokens(a.body), tokens(b.body)
    if ta == tb:
        return True
    docs = _jaccard(frozenset(a.pmids), frozenset(b.pmids))
    return docs >= DOCS_SAME_SOURCE or (_jaccard(ta, tb) >= TEXT_SIMILAR and docs >= DOCS_SIMILAR)


def group(questions: Sequence[BenchmarkQuestion]) -> dict[str, str]:
    """Question ID -> group ID, where the group ID is the smallest member ID.
    Grouping is transitive (union-find), so chains of near-duplicates share one
    group. Quadratic, which is fine at a few thousand questions."""
    parent = list(range(len(questions)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(questions)):
        for j in range(i + 1, len(questions)):
            if related(questions[i], questions[j]):
                parent[find(i)] = find(j)

    members: dict[int, list[str]] = {}
    for i, q in enumerate(questions):
        members.setdefault(find(i), []).append(q.id)
    return {qid: min(ids) for ids in members.values() for qid in ids}


def load(records: Iterable[dict]) -> tuple[list[BenchmarkQuestion], list[Ineligible]]:
    eligible, ineligible = [], []
    for raw in records:
        result = normalize(raw)
        (ineligible if isinstance(result, Ineligible) else eligible).append(result)
    return eligible, ineligible
