"""Versioned data contracts (technical PRD sections 4 and 6.4).

These types are shared by the API, the retrieval layer, and the offline
evaluation runner, so the pipeline that is evaluated is the pipeline served.
Benchmark records (reference answers, relevant-paper labels, splits) are
deliberately absent: they live in evaluation-only code and never reach a type
that the API can return.
"""

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

SCHEMA_VERSION = "1"

Pmid = Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]{0,9}$")]


class Outcome(StrEnum):
    """Every request ends in exactly one of these (technical PRD 6.4)."""

    ANSWERED = "answered"
    NEEDS_CLARIFICATION = "needs_clarification"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    UNSUPPORTED_REQUEST = "unsupported_request"
    SERVICE_UNAVAILABLE = "service_unavailable"


class RetrievalMethod(StrEnum):
    BM25 = "bm25"
    VECTOR = "vector"
    HYBRID = "hybrid"


class SourceStatus(StrEnum):
    """Publication notices carried by the source record at retrieval time.
    Retracted records are excluded from the corpus (technical PRD 3.3).
    `none_reported` means PubMed listed no notice; it is not a claim that the
    paper is sound."""

    NONE_REPORTED = "none_reported"
    CORRECTED = "corrected"
    EXPRESSION_OF_CONCERN = "expression_of_concern"
    RETRACTED = "retracted"


class Paper(BaseModel):
    """One normalized PubMed record. Missing metadata is null, never generated."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pmid: Pmid
    title: str = Field(min_length=1)
    abstract: str = Field(min_length=1)
    journal: str | None = None
    year: int | None = None
    source_status: SourceStatus = SourceStatus.NONE_REPORTED
    retrieved_on: date
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def url(self) -> str:
        """Built from the stored identifier, never from model output (6.3)."""
        return f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/"


class RetrievalHit(BaseModel):
    """One ranked paper. Scores are method-specific: a BM25 score and a cosine
    similarity are not comparable, and neither is a confidence (section 4)."""

    model_config = ConfigDict(frozen=True)

    pmid: Pmid
    rank: int = Field(ge=1)
    score: float
    method: RetrievalMethod
    unit_id: str | None = None
    """The best-scoring searchable unit: the PMID itself, or "<pmid>#<n>" for a
    passage of an overlong paper (bla/units.py)."""


class Excerpt(BaseModel):
    """A span of stored source text. `text == paper.<field>[start:end]` is an
    invariant enforced by the validator, not trusted from the model."""

    model_config = ConfigDict(frozen=True)

    field: Literal["title", "abstract"]
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str


# --- Answer API response (technical PRD 7.1) ---------------------------------


class AnswerItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    source_ids: list[str]


class ExplanationClaim(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    source_ids: list[str]


class Answer(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[AnswerItem]
    explanation_claims: list[ExplanationClaim]
    qualifications: list[str]


class SourceExcerpt(BaseModel):
    model_config = ConfigDict(frozen=True)

    field: Literal["title", "abstract"]
    start: int
    end: int
    text: str


class Source(BaseModel):
    """A paper shown to the model for this response. `source_id` is local to
    the response (S1, S2, ...); URLs are built from stored PMIDs (6.3)."""

    model_config = ConfigDict(frozen=True)

    source_id: str
    pmid: Pmid
    title: str
    url: str
    abstract: str
    journal: str | None
    year: int | None
    source_status: SourceStatus
    retrieval_rank: int
    retrieval_method: RetrievalMethod
    excerpts: list[SourceExcerpt]


class ClarificationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    question: str
    token: str


class AnswerResponse(BaseModel):
    """Everything the public API returns. No reference answers, split labels,
    provider errors, prompts, or credentials (technical PRD section 4)."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = SCHEMA_VERSION
    request_id: str
    outcome: Outcome
    message: str
    answer: Answer | None = None
    sources: list[Source] = []
    clarification: ClarificationRequest | None = None
    corpus_version: str | None = None
