"""Keyword tokenizer for the BM25 baseline.

Starting rules, to be revisited on development questions only (technical PRD
section 5). Bump TOKENIZER_VERSION on any change: it is part of the collection
version, and a changed tokenizer invalidates earlier BM25 results.

- Lowercase; no stemming. Stemmers mangle identifiers ("BRCA1s", "statins").
- Keep letter-digit identifiers whole: "BRCA1", "p53", "COVID-19", "5-HT2A".
- A hyphen/slash compound also emits its joined form and its parts, so
  "IL-6" matches "IL6" and "TNF-alpha" matches "alpha".
- Greek letters are kept as letters, so "TNF-α" survives tokenization.
- Drop a small English stopword list; never drop anything containing a digit.
"""

import re

TOKENIZER_VERSION = "1"

_TOKEN = re.compile(r"[^\W_]+(?:[-/][^\W_]+)*")
_SEPARATOR = re.compile(r"[-/]")

STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "can", "could",
    "did", "do", "does", "for", "from", "had", "has", "have", "how", "in", "into",
    "is", "it", "its", "may", "might", "of", "on", "or", "than", "that", "the",
    "their", "there", "these", "they", "this", "those", "to", "was", "were", "what",
    "when", "where", "which", "while", "who", "whom", "why", "will", "with", "would",
})  # fmt: skip


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for match in _TOKEN.finditer(text.lower()):
        word = match.group()
        parts = _SEPARATOR.split(word)
        if len(parts) == 1:
            if word not in STOPWORDS:
                tokens.append(word)
            continue
        tokens.append("".join(parts))
        tokens.extend(p for p in parts if p not in STOPWORDS)
    return tokens
