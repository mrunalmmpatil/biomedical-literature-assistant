"""Okapi BM25 keyword baseline (technical PRD section 5).

Implemented directly rather than through a library so the scoring formula, the
tokenizer, and tie-breaking are all visible and versioned with the project. The
searchable unit is the paper's title plus its complete abstract.
"""

import heapq
import math
from collections import Counter, defaultdict
from collections.abc import Iterable

from bla.contracts import Paper, RetrievalHit, RetrievalMethod
from bla.corpus import searchable_text
from bla.retrieval import check_depth
from bla.retrieval.tokenize import tokenize


class BM25Retriever:
    method = RetrievalMethod.BM25

    def __init__(self, papers: Iterable[Paper], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._pmids: list[str] = []
        self._lengths: list[int] = []
        # term -> [(document index, term frequency)]
        self._postings: dict[str, list[tuple[int, int]]] = defaultdict(list)

        seen: set[str] = set()
        for paper in papers:
            if paper.pmid in seen:
                raise ValueError(f"duplicate PMID in corpus: {paper.pmid}")
            seen.add(paper.pmid)
            doc = len(self._pmids)
            terms = tokenize(searchable_text(paper.title, paper.abstract))
            self._pmids.append(paper.pmid)
            self._lengths.append(len(terms))
            for term, tf in Counter(terms).items():
                self._postings[term].append((doc, tf))

        n = len(self._pmids)
        self._avg_length = sum(self._lengths) / n if n else 0.0
        # Lucene's non-negative IDF: a term in most documents still scores >= 0.
        self._idf = {
            term: math.log(1 + (n - len(posts) + 0.5) / (len(posts) + 0.5))
            for term, posts in self._postings.items()
        }

    def __len__(self) -> int:
        return len(self._pmids)

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

        # Ties break on PMID so identical inputs always produce identical rankings.
        best = heapq.nsmallest(k, scores.items(), key=lambda s: (-s[1], self._pmids[s[0]]))
        return [
            RetrievalHit(pmid=self._pmids[doc], rank=rank, score=score, method=self.method)
            for rank, (doc, score) in enumerate(best, start=1)
        ]
