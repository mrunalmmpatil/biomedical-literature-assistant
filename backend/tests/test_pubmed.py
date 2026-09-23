"""PubMed parsing and fetching. The XML mirrors the structure of real efetch
responses (inspected 2026-09-23) but its text is invented for these tests."""

from datetime import date

import httpx
import pytest

from bla.contracts import SourceStatus
from bla.ingest.pubmed import (
    BATCH_SIZE,
    FetchError,
    PubMedClient,
    batches,
    parse_neighbors,
    parse_pubmed_xml,
)

TODAY = date(2026, 9, 23)


def article(pmid, body="", title="A study title.", journal_date="<Year>2021</Year>", extra=""):
    return f"""
<PubmedArticle><MedlineCitation Status="MEDLINE" Owner="NLM">
  <PMID Version="1">{pmid}</PMID>
  <Article PubModel="Print">
    <Journal><JournalIssue><PubDate>{journal_date}</PubDate></JournalIssue>
      <Title>Journal of Examples</Title></Journal>
    <ArticleTitle>{title}</ArticleTitle>
    {body}
    <PublicationTypeList><PublicationType UI="D016428">Journal Article</PublicationType>
    </PublicationTypeList>
  </Article>
  {extra}
</MedlineCitation></PubmedArticle>"""


def abstract(*sections):
    return (
        "<Abstract>"
        + "".join(sections)
        + "<CopyrightInformation>© Publisher</CopyrightInformation></Abstract>"
    )


def document(*records):
    return (
        '<?xml version="1.0" ?>\n<!DOCTYPE PubmedArticleSet PUBLIC "-//NLM//DTD PubMedArticle, '
        '1st January 2025//EN" "https://dtd.nlm.nih.gov/ncbi/pubmed/out/pubmed_250101.dtd">\n'
        "<PubmedArticleSet>" + "".join(records) + "</PubmedArticleSet>"
    ).encode()


def parse(xml, requested):
    return parse_pubmed_xml(xml, requested, TODAY)


def test_structured_abstract_keeps_labels_and_drops_copyright():
    xml = document(
        article(
            "111",
            abstract(
                '<AbstractText Label="BACKGROUND">Why we looked.</AbstractText>',
                '<AbstractText Label="RESULTS">What\n   we found.</AbstractText>',
            ),
        )
    )
    papers, exclusions = parse(xml, ["111"])
    assert exclusions == []
    (p,) = papers
    assert p.abstract == "BACKGROUND: Why we looked. RESULTS: What we found."
    assert p.title == "A study title."
    assert p.journal == "Journal of Examples"
    assert p.year == 2021
    assert p.source_status is SourceStatus.NONE_REPORTED
    assert p.retrieved_on == TODAY


def test_inline_markup_is_kept_as_text():
    xml = document(
        article(
            "112",
            abstract(
                "<AbstractText><i>BRCA1</i> carriers had CO<sub>2</sub> levels.</AbstractText>"
            ),
            title="Effects of <i>TNF</i>-α",
        )
    )
    (p,), _ = parse(xml, ["112"])
    assert p.title == "Effects of TNF-α"
    assert p.abstract == "BRCA1 carriers had CO2 levels."


def test_own_pmid_is_used_not_a_nested_comment_pmid():
    comments = (
        '<CommentsCorrectionsList><CommentsCorrections RefType="CommentIn">'
        '<RefSource>Other</RefSource><PMID Version="1">999</PMID>'
        "</CommentsCorrections></CommentsCorrectionsList>"
    )
    xml = document(article("113", abstract("<AbstractText>Text.</AbstractText>"), extra=comments))
    (p,), _ = parse(xml, ["113"])
    assert p.pmid == "113"


def test_medline_date_year_is_extracted():
    xml = document(
        article(
            "114",
            abstract("<AbstractText>Text.</AbstractText>"),
            journal_date="<MedlineDate>1998 Dec-1999 Jan</MedlineDate>",
        )
    )
    (p,), _ = parse(xml, ["114"])
    assert p.year == 1998


def notice(ref_type):
    return (
        f'<CommentsCorrectionsList><CommentsCorrections RefType="{ref_type}">'
        "<RefSource>Notice</RefSource></CommentsCorrections></CommentsCorrectionsList>"
    )


@pytest.mark.parametrize(
    "ref_type, status",
    [
        ("ErratumIn", SourceStatus.CORRECTED),
        ("ExpressionOfConcernIn", SourceStatus.EXPRESSION_OF_CONCERN),
        ("CommentIn", SourceStatus.NONE_REPORTED),
    ],
)
def test_publication_notices_are_recorded(ref_type, status):
    xml = document(
        article("115", abstract("<AbstractText>Text.</AbstractText>"), extra=notice(ref_type))
    )
    (p,), _ = parse(xml, ["115"])
    assert p.source_status is status


def test_retracted_records_are_excluded_by_either_marker():
    retracted_type = article("116", abstract("<AbstractText>Text.</AbstractText>")).replace(
        "Journal Article</PublicationType>",
        'Journal Article</PublicationType><PublicationType UI="D016441">Retracted Publication</PublicationType>',
    )
    retraction_link = article(
        "117", abstract("<AbstractText>Text.</AbstractText>"), extra=notice("RetractionIn")
    )
    papers, exclusions = parse(document(retracted_type, retraction_link), ["116", "117"])
    assert papers == []
    assert {(e.pmid, e.reason) for e in exclusions} == {("116", "retracted"), ("117", "retracted")}


def test_every_requested_pmid_is_accounted_for():
    xml = document(
        article("201", abstract("<AbstractText>Kept.</AbstractText>")),
        article("202"),  # no abstract
        article("203", abstract("<AbstractText>   </AbstractText>")),  # empty abstract
    )
    papers, exclusions = parse(xml, ["201", "202", "203", "204"])
    assert [p.pmid for p in papers] == ["201"]
    assert {(e.pmid, e.reason) for e in exclusions} == {
        ("202", "no_abstract"),
        ("203", "no_abstract"),
        ("204", "not_returned"),
    }


def test_papers_come_back_in_requested_order():
    xml = document(
        *(article(p, abstract("<AbstractText>Text.</AbstractText>")) for p in ("3", "1", "2"))
    )
    papers, _ = parse(xml, ["1", "2", "3"])
    assert [p.pmid for p in papers] == ["1", "2", "3"]


def test_book_articles_are_parsed():
    book = """
<PubmedBookArticle><BookDocument>
  <PMID Version="1">301</PMID>
  <Book><BookTitle>Reviews of Examples</BookTitle><PubDate><Year>2010</Year></PubDate></Book>
  <ArticleTitle>An example condition</ArticleTitle>
  <Abstract><AbstractText><i>Clinical characteristics.</i> Onset is variable.</AbstractText></Abstract>
</BookDocument></PubmedBookArticle>"""
    (p,), _ = parse(document(book), ["301"])
    assert (p.title, p.journal, p.year) == ("An example condition", None, 2010)
    assert p.abstract == "Clinical characteristics. Onset is variable."


def test_error_document_is_not_mistaken_for_an_empty_result():
    with pytest.raises(ValueError, match="eFetchResult"):
        parse(b"<eFetchResult><ERROR>Empty id list</ERROR></eFetchResult>", ["1"])


def test_batches_deduplicate_in_first_seen_order():
    assert batches(["3", "1", "3", "2", "1"], size=2) == [["3", "1"], ["2"]]


# --- Client -----------------------------------------------------------------


class FakeTime:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def client_with(responses, **kwargs):
    """A client whose HTTP layer replays `responses` in order and records requests."""
    seen = []
    queue = list(responses)

    def handler(request):
        seen.append(request)
        result = queue.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    clock = FakeTime()
    client = PubMedClient(
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=clock.sleep,
        clock=clock.clock,
        **kwargs,
    )
    return client, seen, clock


def test_request_identifies_the_tool_and_uses_post():
    client, seen, _ = client_with(
        [httpx.Response(200, content=b"<xml/>")], api_key="k", email="e@x"
    )
    assert client.efetch(["1", "2"]) == b"<xml/>"
    (request,) = seen
    assert request.method == "POST"
    body = request.content.decode()
    for part in ("db=pubmed", "id=1%2C2", "tool=biomedical-literature-assistant", "api_key=k"):
        assert part in body


def test_requests_are_spaced_to_the_ncbi_rate():
    ok = httpx.Response(200, content=b"<xml/>")
    client, _, clock = client_with([ok, ok])
    client.efetch(["1"])
    client.efetch(["2"])
    assert clock.sleeps == [pytest.approx(1 / 3)]


def test_transient_failures_are_retried_within_bounds():
    client, seen, clock = client_with(
        [
            httpx.ConnectError("down"),
            httpx.Response(503),
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, content=b"<xml/>"),
        ]
    )
    assert client.efetch(["1"]) == b"<xml/>"
    assert len(seen) == 4
    assert 7 in clock.sleeps  # Retry-After honoured


def test_retries_give_up_after_the_attempt_budget():
    client, seen, _ = client_with([httpx.Response(502)] * 3, max_attempts=3)
    with pytest.raises(FetchError, match="3 attempts"):
        client.efetch(["1"])
    assert len(seen) == 3


def test_client_errors_are_not_retried():
    client, seen, _ = client_with([httpx.Response(400)])
    with pytest.raises(FetchError, match="HTTP 400"):
        client.efetch(["1"])
    assert len(seen) == 1


@pytest.mark.parametrize("count", [0, BATCH_SIZE + 1])
def test_batch_size_is_bounded(count):
    client, _, _ = client_with([])
    with pytest.raises(ValueError):
        client.efetch([str(i + 1) for i in range(count)])


# --- Similar articles (elink) ------------------------------------------------


def elink(*linksets):
    return ("<eLinkResult>" + "".join(linksets) + "</eLinkResult>").encode()


def linkset(source, *links, name="pubmed_pubmed"):
    body = "".join(f"<Link><Id>{p}</Id><Score>{s}</Score></Link>" for p, s in links)
    return (
        f"<LinkSet><DbFrom>pubmed</DbFrom><IdList><Id>{source}</Id></IdList>"
        f"<LinkSetDb><DbTo>pubmed</DbTo><LinkName>{name}</LinkName>{body}</LinkSetDb></LinkSet>"
    )


def test_neighbors_are_ranked_by_score_and_exclude_the_source():
    xml = elink(linkset("1", ("5", 10), ("1", 99), ("4", 30)), linkset("2", ("7", 1)))
    assert parse_neighbors(xml) == {"1": [("4", 30), ("5", 10)], "2": [("7", 1)]}


def test_other_link_names_are_ignored():
    xml = elink(linkset("1", ("5", 10), name="pubmed_pubmed_citedin"))
    assert parse_neighbors(xml) == {"1": []}


def test_elink_error_document_is_not_an_empty_result():
    with pytest.raises(ValueError):
        parse_neighbors(b"<eLinkResult><ERROR>bad</ERROR></eLinkResult>")


def test_neighbors_sends_one_id_parameter_per_pmid():
    seen = {}

    def handler(request):
        seen["body"] = request.content.decode()
        return httpx.Response(200, content=elink())

    client = PubMedClient(http=httpx.Client(transport=httpx.MockTransport(handler)))
    client.neighbors(["1", "2"])
    assert "id=1&id=2" in seen["body"]
    assert "cmd=neighbor_score" in seen["body"]
