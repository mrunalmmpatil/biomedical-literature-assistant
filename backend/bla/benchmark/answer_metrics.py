"""Answer scoring against BioASQ exact answers (technical PRD 9.2). Evaluation only.

NORMALIZATION_VERSION 1, set before any development answer was scored:
casefold, NFKC, hyphens/slashes/underscores to spaces, other punctuation
removed, leading articles dropped, whitespace collapsed. Greek letters are
spelled out (alpha, beta, ...), so "TNF-alpha" and "TNF-α" normalize alike.
Revisit on development data only, and bump the version when changing it.

- Fact: strict accuracy uses the first answer item only. Lenient accuracy
  accepts a match in any item (reported, never the headline).
- List: one-to-one matching of predicted items to reference items. A
  reference item matches when any of its accepted variants equals the
  prediction after normalization. Precision, recall, and F1 per question.
- A non-answer (any outcome other than answered) scores zero and is counted
  separately, so provider failures cannot improve the result.
"""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

NORMALIZATION_VERSION = "1"

_GREEK = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "epsilon", "κ": "kappa",
    "λ": "lambda", "μ": "mu", "σ": "sigma", "τ": "tau", "ω": "omega",
}  # fmt: skip
_SEPARATORS = re.compile(r"[-_/]+")
_PUNCTUATION = re.compile(r"[^\w\s]")
_ARTICLE = re.compile(r"^(the|a|an) ")
_SPACE = re.compile(r"\s+")


def normalize_answer(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    for letter, name in _GREEK.items():
        text = text.replace(letter, f" {name} ")
    text = _SEPARATORS.sub(" ", text)
    text = _PUNCTUATION.sub(" ", text)
    text = _SPACE.sub(" ", text).strip()
    return _ARTICLE.sub("", text)


def _matches(prediction: str, variants: Sequence[str]) -> bool:
    p = normalize_answer(prediction)
    return bool(p) and any(p == normalize_answer(v) for v in variants)


@dataclass(frozen=True)
class FactScore:
    strict: bool
    lenient: bool


def score_fact(items: Sequence[str], reference: Sequence[Sequence[str]]) -> FactScore:
    variants = [v for item in reference for v in item]
    return FactScore(
        strict=bool(items) and _matches(items[0], variants),
        lenient=any(_matches(i, variants) for i in items),
    )


@dataclass(frozen=True)
class ListScore:
    precision: float
    recall: float
    f1: float
    matched: int


def score_list(items: Sequence[str], reference: Sequence[Sequence[str]]) -> ListScore:
    predictions = list(dict.fromkeys(normalize_answer(i) for i in items if normalize_answer(i)))
    unmatched = list(range(len(reference)))
    matched = 0
    for prediction in predictions:
        for index in unmatched:
            if _matches(prediction, reference[index]):
                unmatched.remove(index)
                matched += 1
                break
    precision = matched / len(predictions) if predictions else 0.0
    recall = matched / len(reference) if reference else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return ListScore(precision, recall, f1, matched)
