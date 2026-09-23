"""Deterministic checks on generated answers (technical PRD section 6.3).

The model cites sources by the local IDs it was shown (S1, S2, ...) and supports
each claim with verbatim quotes. It never supplies offsets or URLs: the server
locates each quote in the stored text and derives the excerpt itself.

Validation is all-or-nothing. A single bad citation rejects the whole response;
removing the citation and showing its claim anyway would display an unsupported
statement. Passing these checks establishes that references are consistent,
not that the cited text scientifically supports the claim.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from bla.contracts import Excerpt, Paper
from bla.corpus import normalize_text

MIN_QUOTE_CHARS = 15
"""Starting default. Shorter quotes ("in mice") match almost anywhere and so
verify nothing; tune on development data only."""


# --- What the model is asked to return -------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelQuote(_Strict):
    source_id: str
    text: str


class ModelItem(_Strict):
    text: str = Field(min_length=1)
    source_ids: list[str]


class ModelClaim(_Strict):
    text: str = Field(min_length=1)
    source_ids: list[str]
    quotes: list[ModelQuote]


class ModelAnswer(_Strict):
    outcome: Literal["answered", "insufficient_evidence"]
    items: list[ModelItem]
    claims: list[ModelClaim]
    qualifications: list[str] = []


# --- What validation produces ----------------------------------------------


@dataclass(frozen=True)
class CitedItem:
    text: str
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class CitedClaim:
    text: str
    source_ids: tuple[str, ...]
    excerpts: tuple[tuple[str, Excerpt], ...]  # (source_id, excerpt)


@dataclass(frozen=True)
class ValidAnswer:
    outcome: Literal["answered", "insufficient_evidence"]
    items: tuple[CitedItem, ...]
    claims: tuple[CitedClaim, ...]
    qualifications: tuple[str, ...]


@dataclass(frozen=True)
class InvalidAnswer:
    """Maps to service_unavailable. `reason` is internal diagnostics: it may
    quote model output, so it is logged in bounded form, never returned."""

    reason: str


def validate_answer(
    raw: str | Mapping, sources: Mapping[str, Paper]
) -> ValidAnswer | InvalidAnswer:
    """Check a model response against the sources it was actually given."""
    try:
        parsed = (
            ModelAnswer.model_validate_json(raw)
            if isinstance(raw, str)
            else ModelAnswer.model_validate(raw)
        )
    except ValidationError as exc:  # also raised for unparseable JSON
        return InvalidAnswer(f"malformed output: {exc.error_count()} schema error(s)")

    if parsed.outcome == "insufficient_evidence":
        if parsed.items:
            return InvalidAnswer("insufficient_evidence outcome carries answer items")
        # Any explanatory claims must still cite honestly.
    elif not parsed.items:
        return InvalidAnswer("answered outcome has no answer items")

    items: list[CitedItem] = []
    for item in parsed.items:
        problem = _check_ids(item.source_ids, sources)
        if problem:
            return InvalidAnswer(f"answer item {item.text!r}: {problem}")
        items.append(CitedItem(item.text, tuple(item.source_ids)))

    claims: list[CitedClaim] = []
    for claim in parsed.claims:
        problem = _check_ids(claim.source_ids, sources)
        if problem:
            return InvalidAnswer(f"claim {claim.text!r}: {problem}")
        if not claim.quotes:
            return InvalidAnswer(f"claim {claim.text!r}: no supporting quote")
        excerpts = []
        for quote in claim.quotes:
            if quote.source_id not in claim.source_ids:
                return InvalidAnswer(f"claim {claim.text!r}: quote from uncited {quote.source_id}")
            excerpt = locate_quote(quote.text, sources[quote.source_id])
            if excerpt is None:
                return InvalidAnswer(f"claim {claim.text!r}: quote not found in {quote.source_id}")
            excerpts.append((quote.source_id, excerpt))
        claims.append(CitedClaim(claim.text, tuple(claim.source_ids), tuple(excerpts)))

    return ValidAnswer(
        outcome=parsed.outcome,
        items=tuple(items),
        claims=tuple(claims),
        qualifications=tuple(q for q in parsed.qualifications if q.strip()),
    )


def locate_quote(quote: str, paper: Paper) -> Excerpt | None:
    """Find a verbatim quote in the paper's stored (already normalized) text.

    Only whitespace is normalized on the quote side; case, punctuation, and
    wording must match exactly. A paraphrase is not a quotation.
    """
    needle = normalize_text(quote)
    if len(needle) < MIN_QUOTE_CHARS:
        return None
    for field in ("abstract", "title"):
        text = getattr(paper, field)
        start = text.find(needle)
        if start != -1:
            return Excerpt(field=field, start=start, end=start + len(needle), text=needle)
    return None


def _check_ids(ids: list[str], sources: Mapping[str, Paper]) -> str | None:
    if not ids:
        return "no source cited"
    unknown = [i for i in ids if i not in sources]
    if unknown:
        return f"unknown source {', '.join(unknown)}"
    return None
