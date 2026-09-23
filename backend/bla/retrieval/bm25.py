"""Okapi BM25 keyword baseline (technical PRD section 5).

Implemented directly rather than through a library so the scoring formula, the
tokenizer, and tie-breaking are all visible and versioned with the project. It
indexes the same searchable units as the vector index (bla/units.py), and a
paper scores as its best unit.
"""

import heapq
import math
from collections import Counter, defaultdict
from collections.abc import Iterable

from bla.contracts import Paper, RetrievalHit, RetrievalMethod
from bla.retrieval import check_depth
from bla.retrieval.tokenize import tokenize
from bla.units import units


class BM25Retriever:
    method = RetrievalMethod.BM25

    def __init__(self, papers: Iterable[Paper], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._pmids: list[str] = []  # per unit
        self._unit_ids: list[str] = []
        self._lengths: list[int] = []
        # term -> [(document index, term frequency)]
        self._postings: dict[str, list[tuple[int, int]]] = defaultdict(list)

        seen: set[str] = set()
        for paper in papers:
            if paper.pmid in seen:
                raise ValueError(f"duplicate PMID in corpus: {paper.pmid}")
            seen.add(paper.pmid)
            for unit in units(paper):
                doc = len(self._pmids)
                terms = tokenize(unit.text)
                self._pmids.append(paper.pmid)
                self._unit_ids.append(unit.id)
                self._lengths.append(len(terms))
                for term, tf in Counter(terms).items():
                    self._postings[term].append((doc, tf))
        self._papers = len(seen)

        n = len(self._pmids)
        self._avg_length = sum(self._lengths) / n if n else 0.0
        # Lucene's non-negative IDF: a term in most documents still scores >= 0.
        self._idf = {
            term: math.log(1 + (n - len(posts) + 0.5) / (len(posts) + 0.5))
            for term, posts in self._postings.items()
        }

    def __len__(self) -> int:
        """Papers indexed (not units)."""
        return self._papers

    def search(self, query: str, k: int = 10) -> list[RetrievalHit]:
        check_depth(k)
        scores: dict[int, float] = defaultdict(float)
        # Repeated query terms count once: a question restating a word is not
        # stronger evidence for that word.
        for term in set(tokenize(query)):
            idf = self._idf.get(term)
            if idf is None:
                continue
            for doc, tf in self._postings[term]:
                norm = 1 - self.b + self.b * self._lengths[doc] / self._avg_length
                scores[doc] += idf * tf * (self.k1 + 1) / (tf + self.k1 * norm)

        # A paper scores as its best unit (section 5's initial rule).
        best_unit: dict[str, tuple[float, int]] = {}
        for doc, score in scores.items():
            pmid = self._pmids[doc]
            current = best_unit.get(pmid)
            if current is None or (score, -doc) > (current[0], -current[1]):
                best_unit[pmid] = (score, doc)

        # Ties break on PMID so identical inputs always produce identical rankings.
        best = heapq.nsmallest(k, best_unit.items(), key=lambda item: (-item[1][0], item[0]))
        return [
            RetrievalHit(
                pmid=pmid,
                rank=rank,
                score=score,
                method=self.method,
                unit_id=self._unit_ids[doc],
            )
            for rank, (pmid, (score, doc)) in enumerate(best, start=1)
        ]
