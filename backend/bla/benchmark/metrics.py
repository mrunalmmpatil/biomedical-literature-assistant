"""Paper-level retrieval metrics (technical PRD 9.2). Evaluation only.

Relevant papers are the question's reference PMIDs *that are in the
collection*. A reference paper missing from the collection is a data-coverage
failure, reported separately, not a retrieval miss (technical PRD 3.3).
Retrieved PMIDs are de-duplicated, keeping first rank, before scoring.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class QuestionScore:
    relevant: int
    recall_at_5: float
    recall_at_10: float
    reciprocal_rank_at_10: float
    first_relevant_rank: int | None


def dedupe(pmids: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(pmids))


def score(retrieved: Sequence[str], relevant: Collection[str]) -> QuestionScore | None:
    """None when no relevant paper is in the collection: such a question
    cannot measure retrieval and is counted separately, not as zero."""
    relevant = set(relevant)
    if not relevant:
        return None
    ranked = dedupe(retrieved)
    first = next((i for i, p in enumerate(ranked[:10], start=1) if p in relevant), None)
    return QuestionScore(
        relevant=len(relevant),
        recall_at_5=len(relevant & set(ranked[:5])) / len(relevant),
        recall_at_10=len(relevant & set(ranked[:10])) / len(relevant),
        reciprocal_rank_at_10=1 / first if first else 0.0,
        first_relevant_rank=first,
    )


def mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None
