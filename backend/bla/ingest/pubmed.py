"""PubMed title/abstract collection through NCBI E-utilities (technical PRD 3.2-3.3).

Two halves, kept separate so the parser is testable without the network:

- `parse_pubmed_xml` turns an efetch response into normalized `Paper` records
  plus an explicit exclusion for every requested PMID that did not become one.
- `PubMedClient` fetches raw XML politely: NCBI's documented request rate,
  bounded retries, and no retry on errors that will not change.

The raw XML is the preserved original; callers store it before parsing.
"""

import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date

import httpx

from bla.contracts import Paper, SourceStatus
from bla.corpus import content_hash, normalize_text

EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
TOOL_NAME = "biomedical-literature-assistant"
BATCH_SIZE = 200
"""NCBI's recommended ceiling for IDs per efetch request."""


@dataclass(frozen=True)
class Exclusion:
    """A requested PMID that is not in the corpus, and why. Every one appears
    in the data report; missing reference papers are coverage failures."""

    pmid: str
    reason: str  # not_returned | no_title | no_abstract | retracted | duplicate


# --- Parsing ----------------------------------------------------------------

_YEAR = re.compile(r"\b(1[89]\d\d|20\d\d)\b")

# Notices, strongest first: the first match decides the status.
_NOTICES = [
    (SourceStatus.RETRACTED, {"RetractionIn"}, {"Retracted Publication"}),
    (SourceStatus.EXPRESSION_OF_CONCERN, {"ExpressionOfConcernIn"}, set()),
    (SourceStatus.CORRECTED, {"ErratumIn", "CorrectedandRepublishedIn"}, set()),
]


def parse_pubmed_xml(
    xml: bytes, requested: Iterable[str], retrieved_on: date
) -> tuple[list[Paper], list[Exclusion]]:
    """Parse one efetch response. Retracted records are excluded by policy.

    Raises ValueError when the body is not a PubMed article set: NCBI can
    answer HTTP 200 with an error document, which must not read as "no papers".
    """
    root = ET.fromstring(xml)
    if root.tag != "PubmedArticleSet":
        raise ValueError(f"unexpected efetch document <{root.tag}>")

    wanted = list(dict.fromkeys(requested))
    papers: dict[str, Paper] = {}
    exclusions: list[Exclusion] = []

    for record in root:
        if record.tag == "PubmedArticle":
            core = record.find("MedlineCitation")
            article = core.find("Article") if core is not None else None
            journal = _text(article.find("Journal/Title")) if article is not None else None
            year = _year(
                article.find("Journal/JournalIssue/PubDate") if article is not None else None
            )
        elif record.tag == "PubmedBookArticle":
            core = record.find("BookDocument")
            article = core
            journal = None
            year = _year(core.find("Book/PubDate") if core is not None else None)
        else:
            continue
        if core is None or article is None:
            continue

        # Only the record's own PMID: comment and correction links nest PMIDs too.
        pmid = _text(core.find("PMID"))
        if pmid is None:
            continue
        if pmid in papers:
            exclusions.append(Exclusion(pmid, "duplicate"))
            continue

        title = _text(article.find("ArticleTitle"))
        if title is None and record.tag == "PubmedBookArticle":
            title = _text(core.find("Book/BookTitle"))
        abstract = _abstract(article.find("Abstract"))
        status = _status(record)

        if title is None:
            exclusions.append(Exclusion(pmid, "no_title"))
        elif abstract is None:
            exclusions.append(Exclusion(pmid, "no_abstract"))
        elif status is SourceStatus.RETRACTED:
            exclusions.append(Exclusion(pmid, "retracted"))
        else:
            papers[pmid] = Paper(
                pmid=pmid,
                title=title,
                abstract=abstract,
                journal=journal,
                year=year,
                source_status=status,
                retrieved_on=retrieved_on,
                content_hash=content_hash(title, abstract),
            )

    accounted = set(papers) | {e.pmid for e in exclusions}
    exclusions.extend(Exclusion(p, "not_returned") for p in wanted if p not in accounted)
    return [papers[p] for p in wanted if p in papers], exclusions


def _text(element: ET.Element | None) -> str | None:
    """All text inside an element, inline markup (<i>, <sup>) included."""
    if element is None:
        return None
    return normalize_text("".join(element.itertext())) or None


def _abstract(element: ET.Element | None) -> str | None:
    """Join sections, keeping structured-abstract labels ("METHODS: ...").
    Copyright statements and OtherAbstract translations are not abstract text."""
    if element is None:
        return None
    sections = []
    for part in element.findall("AbstractText"):
        body = _text(part)
        if body is None:
            continue
        label = part.get("Label")
        sections.append(f"{label}: {body}" if label and label != "UNLABELLED" else body)
    return normalize_text(" ".join(sections)) or None


def _year(pub_date: ET.Element | None) -> int | None:
    if pub_date is None:
        return None
    raw = _text(pub_date.find("Year")) or _text(pub_date.find("MedlineDate"))
    match = _YEAR.search(raw or "")
    return int(match.group()) if match else None


def _status(record: ET.Element) -> SourceStatus:
    ref_types = {c.get("RefType") for c in record.iter("CommentsCorrections")}
    pub_types = {_text(p) for p in record.iter("PublicationType")}
    for status, refs, types in _NOTICES:
        if ref_types & refs or pub_types & types:
            return status
    return SourceStatus.NONE_REPORTED


# --- Fetching ---------------------------------------------------------------


class FetchError(RuntimeError):
    pass


class PubMedClient:
    """Rate-limited efetch. Retries only transient failures, a bounded number
    of times; a 4xx other than 429 is a request problem and is raised at once."""

    def __init__(
        self,
        api_key: str | None = None,
        email: str | None = None,
        http: httpx.Client | None = None,
        max_attempts: int = 4,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._params = {"db": "pubmed", "retmode": "xml", "tool": TOOL_NAME}
        if api_key:
            self._params["api_key"] = api_key
        if email:
            self._params["email"] = email
        # NCBI: 3 requests/second without a key, 10 with one.
        self._interval = 1 / 10 if api_key else 1 / 3
        self._http = http or httpx.Client(timeout=60)
        self._max_attempts = max_attempts
        self._sleep = sleep
        self._clock = clock
        self._last_request: float | None = None

    def efetch(self, pmids: Sequence[str]) -> bytes:
        if not 1 <= len(pmids) <= BATCH_SIZE:
            raise ValueError(f"efetch takes 1-{BATCH_SIZE} PMIDs, got {len(pmids)}")
        data = {**self._params, "id": ",".join(pmids)}

        for attempt in range(1, self._max_attempts + 1):
            self._wait_turn()
            try:
                response = self._http.post(EFETCH_URL, data=data)
            except httpx.TransportError as exc:
                problem, delay = f"transport error: {exc.__class__.__name__}", None
            else:
                if response.status_code == 200:
                    return response.content
                if response.status_code != 429 and response.status_code < 500:
                    raise FetchError(f"efetch rejected the request: HTTP {response.status_code}")
                problem = f"HTTP {response.status_code}"
                delay = _retry_after(response)
            if attempt == self._max_attempts:
                raise FetchError(f"efetch failed after {attempt} attempts ({problem})")
            self._sleep(delay if delay is not None else 2 ** (attempt - 1))
        raise AssertionError("unreachable")

    def _wait_turn(self) -> None:
        now = self._clock()
        if self._last_request is not None:
            gap = self._interval - (now - self._last_request)
            if gap > 0:
                self._sleep(gap)
                now = self._clock()
        self._last_request = now


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return min(float(response.headers["Retry-After"]), 60.0)
    except (KeyError, ValueError):
        return None


def batches(pmids: Iterable[str], size: int = BATCH_SIZE) -> list[list[str]]:
    """Deterministic batches over de-duplicated PMIDs in first-seen order, so a
    resumed run requests exactly the batches an interrupted run did."""
    unique = list(dict.fromkeys(pmids))
    return [unique[i : i + size] for i in range(0, len(unique), size)]
