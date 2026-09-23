"""Searchable units: what BM25 and the vector index actually search
(technical PRD sections 3.3 and 5).

Policy (UNIT_POLICY_VERSION 1, chosen on measured lengths; see
docs/data-protocol.md): one unit per paper, "title\\nabstract", unless that
exceeds MAX_UNIT_CHARS. Only then is the abstract split into passages on
sentence boundaries, and every passage repeats the title. Nothing is ever
truncated: a single sentence longer than the budget is split at whitespace.

Offsets point into the normalized abstract, so any unit maps back to the
exact stored source text.
"""

import re
from dataclasses import dataclass

from bla.contracts import Paper
from bla.corpus import searchable_text

UNIT_POLICY_VERSION = "1"

MAX_UNIT_CHARS = 6000
"""Guard for llama-text-embed-v2's 2,048-token input, assuming about 3
characters per token in dense biomedical text. Pinecone truncates longer
input silently (truncate: END), which this policy exists to prevent."""

# A sentence ends at . ? or ! followed by whitespace and an uppercase letter,
# digit, or opening bracket. Deliberately simple: split points only need to be
# plausible, never lossy, because units are rejoined by offsets.
_SENTENCE_END = re.compile(r"(?<=[.?!])\s+(?=[A-Z0-9(\[])")


@dataclass(frozen=True)
class Unit:
    id: str
    """The PMID for a whole-paper unit, "<pmid>#<n>" for passage n."""
    pmid: str
    index: int
    text: str
    start: int
    """Offsets of the unit's abstract portion within `paper.abstract`."""
    end: int


def units(paper: Paper, max_chars: int = MAX_UNIT_CHARS) -> list[Unit]:
    whole = searchable_text(paper.title, paper.abstract)
    if len(whole) <= max_chars:
        return [Unit(paper.pmid, paper.pmid, 0, whole, 0, len(paper.abstract))]
    budget = max_chars - len(paper.title) - 1
    if budget < 200:
        raise ValueError(f"title of {paper.pmid} leaves no room for abstract text")
    spans = _pack(paper.abstract, _sentences(paper.abstract, budget), budget)
    return [
        Unit(
            f"{paper.pmid}#{n}",
            paper.pmid,
            n,
            searchable_text(paper.title, paper.abstract[start:end]),
            start,
            end,
        )
        for n, (start, end) in enumerate(spans)
    ]


def _sentences(text: str, budget: int) -> list[tuple[int, int]]:
    """Sentence spans; any sentence over budget is cut at whitespace."""
    spans, start = [], 0
    for match in _SENTENCE_END.finditer(text):
        spans.append((start, match.start()))
        start = match.end()
    spans.append((start, len(text)))
    result = []
    for s, e in spans:
        while e - s > budget:
            cut = text.rfind(" ", s, s + budget)
            cut = cut if cut > s else s + budget
            result.append((s, cut))
            s = cut + 1 if text[cut : cut + 1] == " " else cut
        if e > s:
            result.append((s, e))
    return result


def _pack(text: str, sentences: list[tuple[int, int]], budget: int) -> list[tuple[int, int]]:
    """Greedily join consecutive sentences while the passage fits."""
    packed: list[tuple[int, int]] = []
    for s, e in sentences:
        if packed and e - packed[-1][0] <= budget:
            packed[-1] = (packed[-1][0], e)
        else:
            packed.append((s, e))
    return packed
