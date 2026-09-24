"""The question-to-outcome workflow (technical PRD 6 and 8.1).

    validate input -> [verify clarification token] -> assess (provider call 1)
      -> retrieve -> [no evidence: insufficient_evidence, no generation]
      -> generate (provider call 2) -> validate -> outcome

One service drives both the API and evaluation, so the pipeline evaluated is
the pipeline served. It returns the public response and, separately, internal
diagnostics that are never sent to clients.

Budgets per request: at most 3 provider attempts in total, at most one of them
a transient retry, a 45s ceiling per attempt, and a 90s overall deadline.
Daily quota exhaustion and authentication errors are never retried.
"""

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from bla.answering.prompts import (
    ASSESS_SCHEMA,
    ASSESS_SYSTEM,
    GENERATE_SCHEMA,
    GENERATE_SYSTEM,
    PROMPT_VERSION,
    assess_user,
    generate_user,
    retry_user,
)
from bla.clarification import Clarification, ClarificationSigner, InvalidToken
from bla.contracts import (
    Answer,
    AnswerItem,
    AnswerResponse,
    ClarificationRequest,
    ExplanationClaim,
    Outcome,
    Paper,
    RetrievalHit,
    Source,
    SourceExcerpt,
)
from bla.llm import MalformedOutput, ProviderError, ProviderTimeout
from bla.retrieval import Retriever
from bla.units import units
from bla.validation import InvalidAnswer, validate_answer

MAX_QUESTION_CHARS = 2000
MAX_CLARIFICATION_CHARS = 1000
MAX_ATTEMPTS = 3
MAX_RETRIES = 1
DEADLINE_SECONDS = 90.0
RETRIEVAL_DEPTH = 10
MAX_SOURCES = 5
EVIDENCE_CHAR_BUDGET = 16_000
"""About 4-5k tokens of source text: up to 5 typical abstracts in full."""

MESSAGES = {
    Outcome.ANSWERED: "Answer drawn from the cited abstracts. Check the quoted text before relying on it.",
    Outcome.NEEDS_CLARIFICATION: "One more detail is needed to answer this question.",
    Outcome.INSUFFICIENT_EVIDENCE: "The abstracts in this collection do not adequately support an answer.",
    Outcome.UNSUPPORTED_REQUEST: "This assistant answers focused biomedical fact or list questions from published abstracts.",
    Outcome.SERVICE_UNAVAILABLE: "The answer service is unavailable right now. Please try again later.",
}


class InputError(ValueError):
    """Maps to HTTP 400 with this message; safe to show."""


class LLM:
    """The subset of bla.llm.OpenRouter this module uses."""

    model: str

    def complete(self, system, user, schema_name, schema, timeout=None): ...


@dataclass
class Diagnostics:
    """Internal only: may contain model output. Never returned to clients."""

    prompt_version: str = PROMPT_VERSION
    attempts: list[dict[str, Any]] = field(default_factory=list)
    assessment: dict[str, Any] | None = None
    retrieval: list[dict[str, Any]] = field(default_factory=list)
    internal_reason: str | None = None
    http_status: int = 200
    total_ms: float = 0.0


class _Budget:
    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._start = clock()
        self.attempts = 0
        self.retries = 0

    def remaining(self) -> float:
        return DEADLINE_SECONDS - (self._clock() - self._start)


class AnswerService:
    def __init__(
        self,
        retriever: Retriever,
        papers: dict[str, Paper],
        llm: LLM,
        signer: ClarificationSigner,
        corpus_version: str | None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._retriever = retriever
        self._papers = papers
        self._llm = llm
        self._signer = signer
        self._corpus_version = corpus_version
        self._clock = clock

    # --- public -------------------------------------------------------------

    def answer(
        self,
        question: str,
        clarification_token: str | None = None,
        clarification_answer: str | None = None,
        request_id: str | None = None,
    ) -> tuple[AnswerResponse, Diagnostics]:
        question = _check_text(question, "question", MAX_QUESTION_CHARS)
        request_id = request_id or uuid.uuid4().hex
        diag = Diagnostics()
        budget = _Budget(self._clock)

        clarified = clarification_token is not None
        if clarified:
            answer = _check_text(
                clarification_answer, "clarification answer", MAX_CLARIFICATION_CHARS
            )
            try:
                earlier = self._signer.verify(clarification_token)
            except InvalidToken as exc:
                raise InputError(
                    "The clarification has expired. Please ask the question again."
                ) from exc
            question = f"{earlier.question}\n(Clarification: {earlier.prompt} {answer})"

        try:
            response = self._run(question, clarified, request_id, diag, budget)
        except ProviderError as exc:
            response = self._unavailable(request_id, diag, exc)
        diag.total_ms = round((DEADLINE_SECONDS - budget.remaining()) * 1000, 1)
        return response, diag

    # --- workflow -----------------------------------------------------------

    def _run(self, question, clarified, request_id, diag, budget) -> AnswerResponse:
        assessment = self._call(
            "assess",
            ASSESS_SYSTEM,
            assess_user(question),
            "assessment",
            ASSESS_SCHEMA,
            diag,
            budget,
        )
        decision = assessment.get("decision")
        diag.assessment = {"decision": decision, "reason": str(assessment.get("reason", ""))[:300]}
        if decision == "out_of_scope":
            return self._respond(request_id, Outcome.UNSUPPORTED_REQUEST)
        if decision == "needs_clarification":
            prompt = str(assessment.get("clarification_question", "")).strip()[:300]
            if clarified or not prompt:
                # One clarification only (6.1): no second loop.
                return self._respond(
                    request_id,
                    Outcome.UNSUPPORTED_REQUEST,
                    "This question still needs more detail. Please ask a new, more specific question.",
                )
            token = self._signer.issue(Clarification(question, prompt, request_id))
            return self._respond(
                request_id,
                Outcome.NEEDS_CLARIFICATION,
                clarification=ClarificationRequest(question=prompt, token=token),
            )
        if decision != "answerable":
            raise MalformedOutput(f"unknown assessment decision {decision!r}")

        hits = self._retriever.search(question, k=RETRIEVAL_DEPTH)
        diag.retrieval = [
            {"pmid": h.pmid, "rank": h.rank, "score": h.score, "unit": h.unit_id} for h in hits
        ]
        shown = self._select_evidence(hits)
        if not shown:
            diag.internal_reason = "no retrieved evidence"
            return self._respond(request_id, Outcome.INSUFFICIENT_EVIDENCE)

        sources = {sid: paper for sid, paper, _, _ in shown}
        first = generate_user(question, [(sid, paper, text) for sid, paper, text, _ in shown])
        user = first
        while True:
            raw = self._call(
                "generate", GENERATE_SYSTEM, user, "answer", GENERATE_SCHEMA, diag, budget
            )
            result = validate_answer(raw, sources)
            if not isinstance(result, InvalidAnswer):
                break
            diag.attempts[-1]["validation"] = result.reason[:300]
            # Kept for development review of validation failures (internal only).
            diag.attempts[-1]["rejected_output"] = raw
            if not self._may_retry(budget):
                raise MalformedOutput(f"answer failed validation: {result.reason}")
            budget.retries += 1
            # At temperature 0 an identical prompt tends to reproduce the same
            # mistake, so the retry says what was rejected.
            user = retry_user(first, result.reason[:200])

        if result.outcome == "insufficient_evidence":
            return self._respond(
                request_id,
                Outcome.INSUFFICIENT_EVIDENCE,
                qualifications=list(result.qualifications),
                sources=self._sources(shown, result),
            )
        answer = Answer(
            items=[AnswerItem(text=i.text, source_ids=list(i.source_ids)) for i in result.items],
            explanation_claims=[
                ExplanationClaim(text=c.text, source_ids=list(c.source_ids)) for c in result.claims
            ],
            qualifications=list(result.qualifications),
        )
        return self._respond(
            request_id, Outcome.ANSWERED, answer=answer, sources=self._sources(shown, result)
        )

    def _call(self, stage, system, user, name, schema, diag, budget) -> dict:
        """One provider call, with at most one transient retry per request."""
        while True:
            if budget.attempts >= MAX_ATTEMPTS:
                raise ProviderTimeout("attempt budget spent")
            remaining = budget.remaining()
            if remaining <= 1:
                raise ProviderTimeout("request deadline reached")
            budget.attempts += 1
            record: dict[str, Any] = {"stage": stage, "model": self._llm.model}
            diag.attempts.append(record)
            try:
                completion = self._llm.complete(system, user, name, schema, timeout=remaining)
            except ProviderError as exc:
                record["error"] = exc.__class__.__name__
                if exc.retryable and self._may_retry(budget):
                    budget.retries += 1
                    continue
                raise
            record.update(
                returned_model=completion.returned_model,
                provider=completion.provider,
                usage=completion.usage,
                latency_ms=completion.latency_ms,
            )
            return completion.content

    @staticmethod
    def _may_retry(budget: _Budget) -> bool:
        return (
            budget.retries < MAX_RETRIES
            and budget.attempts < MAX_ATTEMPTS
            and budget.remaining() > 5
        )

    def _select_evidence(
        self, hits: list[RetrievalHit]
    ) -> list[tuple[str, Paper, str, RetrievalHit]]:
        """Up to MAX_SOURCES papers in rank order within the character budget.
        An overlong paper contributes its best-matching passage, not all of it."""
        shown, used = [], 0
        for hit in hits:
            paper = self._papers.get(hit.pmid)
            if paper is None:
                continue
            text = paper.abstract
            if hit.unit_id and "#" in hit.unit_id:
                unit = next((u for u in units(paper) if u.id == hit.unit_id), None)
                text = paper.abstract[unit.start : unit.end] if unit else text
            if shown and used + len(text) > EVIDENCE_CHAR_BUDGET:
                break
            shown.append((f"S{len(shown) + 1}", paper, text, hit))
            used += len(text)
            if len(shown) == MAX_SOURCES:
                break
        return shown

    def _sources(self, shown, result) -> list[Source]:
        excerpts: dict[str, list[SourceExcerpt]] = {}
        for claim in result.claims:
            for sid, e in claim.excerpts:
                excerpts.setdefault(sid, []).append(
                    SourceExcerpt(field=e.field, start=e.start, end=e.end, text=e.text)
                )
        return [
            Source(
                source_id=sid,
                pmid=paper.pmid,
                title=paper.title,
                url=paper.url,
                abstract=paper.abstract,
                journal=paper.journal,
                year=paper.year,
                source_status=paper.source_status,
                retrieval_rank=hit.rank,
                retrieval_method=hit.method,
                excerpts=excerpts.get(sid, []),
            )
            for sid, paper, _, hit in shown
        ]

    def _respond(self, request_id, outcome, message=None, qualifications=None, **fields):
        text = message or MESSAGES[outcome]
        if qualifications and outcome is Outcome.INSUFFICIENT_EVIDENCE:
            text = f"{text} {' '.join(qualifications)}"
        return AnswerResponse(
            request_id=request_id,
            outcome=outcome,
            message=text,
            corpus_version=self._corpus_version,
            **fields,
        )

    def _unavailable(self, request_id, diag, exc: ProviderError) -> AnswerResponse:
        diag.internal_reason = f"{exc.__class__.__name__}: {exc}"[:300]
        # 504 for timeouts; everything else, including daily quota and a
        # misconfigured key, is the provider being unavailable to us (7.1).
        diag.http_status = 504 if isinstance(exc, ProviderTimeout) else 503
        return self._respond(request_id, Outcome.SERVICE_UNAVAILABLE)


def _check_text(value: str | None, name: str, limit: int) -> str:
    text = (value or "").strip()
    if not text:
        raise InputError(f"The {name} is empty.")
    if len(text) > limit:
        raise InputError(f"The {name} is longer than {limit} characters.")
    return text
