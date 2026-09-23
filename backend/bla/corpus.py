"""Text normalization and content identity for corpus records (technical PRD 3.3).

Normalization runs once at ingestion. Everything downstream (BM25, embeddings,
excerpt offsets, quote matching) operates on the normalized text, so an offset
computed at answer time points into exactly the text that was indexed.
"""

import hashlib
import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """NFC-normalize and collapse all whitespace runs to single spaces.

    NFC rather than NFKC: compatibility folding would rewrite characters such as
    superscripts and micro signs that carry meaning in biomedical text.
    """
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFC", text)).strip()


def searchable_text(title: str, abstract: str) -> str:
    """The one searchable unit per paper. BM25 and the embedding index both
    consume exactly this, so the two methods are compared on the same text."""
    return f"{title}\n{abstract}"


def content_hash(title: str, abstract: str) -> str:
    """SHA-256 over normalized title and abstract. Changes whenever the
    searchable text changes, which is what a collection version must track."""
    payload = f"{normalize_text(title)}\n{normalize_text(abstract)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
