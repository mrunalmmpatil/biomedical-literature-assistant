"""The answer workflow against a scripted model. Every outcome, budget rule,
and failure mapping is exercised without a provider call."""

import pytest

from bla.answering.service import AnswerService, InputError
from bla.clarification import ClarificationSigner
from bla.contracts import Outcome
from bla.llm import (
    Completion,
    MalformedOutput,
    ProviderTimeout,
    ProviderUnavailable,
    QuotaExhausted,
)
from bla.retrieval.bm25 import BM25Retriever

SECRET = "s" * 40
QUOTE = "Allopurinol is a xanthine oxidase inhibitor"

ANSWERABLE = {"decision": "answerable", "clarification_question": "", "reason": "focused"}
OUT_OF_SCOPE = {"decision": "out_of_scope", "clarification_question": "", "reason": "advice"}
CLARIFY = {
    "decision": "needs_clarification",
    "clarification_question": "Which drug?",
    "reason": "x",
}
GOOD = {
    "outcome": "answered",
    "items": [{"text": "xanthine oxidase", "source_ids": ["S1"]}],
    "claims": [
        {
            "text": "Allopurinol inhibits xanthine oxidase.",
            "source_ids": ["S1"],
            "quotes": [{"source_id": "S1", "text": QUOTE}],
        }
    ],
    "qualifications": [],
}
BAD_QUOTE = {
    **GOOD,
    "claims": [
        {**GOOD["claims"][0], "quotes": [{"source_id": "S1", "text": "not in the abstract at all"}]}
    ],
}
NOT_SUPPORTED = {
    "outcome": "insufficient_evidence",
    "items": [],
    "claims": [],
    "qualifications": ["No source names the enzyme."],
}


class Script:
    """Returns (or raises) scripted results in order and records each call."""

    model = "test/model"

    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls = []

    def complete(self, system, user, schema_name, schema, timeout=None):
        self.calls.append(schema_name)
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return Completion(step, self.model, self.model, "test", {"total_tokens": 1}, 1.0)


def service(corpus, llm):
    return AnswerService(
        BM25Retriever(corpus),
        {p.pmid: p for p in corpus},
        llm,
        ClarificationSigner(SECRET),
        corpus_version="test-v1",
    )


def test_answered_with_server_located_excerpts(corpus):
    llm = Script(ANSWERABLE, GOOD)
    response, diag = service(corpus, llm).answer("Which enzyme does allopurinol inhibit?")
    assert response.outcome is Outcome.ANSWERED
    assert response.answer.items[0].text == "xanthine oxidase"
    s1 = response.sources[0]
    assert s1.source_id == "S1" and s1.pmid == "1001"
    assert s1.url == "https://pubmed.ncbi.nlm.nih.gov/1001/"
    assert s1.excerpts[0].text == QUOTE
    assert s1.abstract[s1.excerpts[0].start : s1.excerpts[0].end] == QUOTE
    assert llm.calls == ["assessment", "answer"]
    assert diag.http_status == 200 and len(diag.attempts) == 2


def test_out_of_scope_is_unsupported_without_retrieval_or_generation(corpus):
    llm = Script(OUT_OF_SCOPE)
    response, diag = service(corpus, llm).answer("Should I stop taking my medication?")
    assert response.outcome is Outcome.UNSUPPORTED_REQUEST
    assert llm.calls == ["assessment"]
    assert diag.retrieval == []


def test_clarification_round_trip_preserves_the_original_question(corpus):
    svc = service(corpus, Script(CLARIFY))
    first, _ = svc.answer("What enzyme does it inhibit?")
    assert first.outcome is Outcome.NEEDS_CLARIFICATION
    assert first.clarification.question == "Which drug?"

    llm = Script(ANSWERABLE, GOOD)
    svc._llm = llm
    second, _ = svc.answer(
        "ignored: the token carries the original",
        clarification_token=first.clarification.token,
        clarification_answer="allopurinol",
    )
    assert second.outcome is Outcome.ANSWERED


def test_a_second_clarification_is_not_offered(corpus):
    svc = service(corpus, Script(CLARIFY))
    first, _ = svc.answer("What enzyme does it inhibit?")
    svc._llm = Script(CLARIFY)
    second, _ = svc.answer(
        "q", clarification_token=first.clarification.token, clarification_answer="it"
    )
    assert second.outcome is Outcome.UNSUPPORTED_REQUEST
    assert second.clarification is None


def test_tampered_clarification_token_is_an_input_error(corpus):
    svc = service(corpus, Script(CLARIFY))
    first, _ = svc.answer("What enzyme does it inhibit?")
    with pytest.raises(InputError, match="ask the question again"):
        svc.answer(
            "q", clarification_token=first.clarification.token + "x", clarification_answer="a"
        )


def test_no_retrieved_evidence_is_insufficient_without_generation(corpus):
    llm = Script(ANSWERABLE)
    response, diag = service(corpus, llm).answer("zzqx wibble frobnicate")
    assert response.outcome is Outcome.INSUFFICIENT_EVIDENCE
    assert llm.calls == ["assessment"]
    assert diag.internal_reason == "no retrieved evidence"


def test_model_reported_insufficient_evidence_carries_its_explanation(corpus):
    response, _ = service(corpus, Script(ANSWERABLE, NOT_SUPPORTED)).answer(
        "allopurinol dose in cats?"
    )
    assert response.outcome is Outcome.INSUFFICIENT_EVIDENCE
    assert "No source names the enzyme." in response.message
    assert response.answer is None


def test_invalid_citation_gets_one_retry_then_answers(corpus):
    llm = Script(ANSWERABLE, BAD_QUOTE, GOOD)
    response, diag = service(corpus, llm).answer("Which enzyme does allopurinol inhibit?")
    assert response.outcome is Outcome.ANSWERED
    assert llm.calls == ["assessment", "answer", "answer"]
    assert "quote not found" in diag.attempts[1]["validation"]


def test_invalid_citation_twice_is_service_unavailable_never_a_partial_answer(corpus):
    llm = Script(ANSWERABLE, BAD_QUOTE, BAD_QUOTE)
    response, diag = service(corpus, llm).answer("Which enzyme does allopurinol inhibit?")
    assert response.outcome is Outcome.SERVICE_UNAVAILABLE
    assert response.answer is None and response.sources == []
    assert diag.http_status == 503
    assert "validation" in diag.internal_reason


def test_daily_quota_is_never_retried(corpus):
    llm = Script(QuotaExhausted("daily"))
    response, diag = service(corpus, llm).answer("Which enzyme does allopurinol inhibit?")
    assert response.outcome is Outcome.SERVICE_UNAVAILABLE
    assert llm.calls == ["assessment"]
    assert diag.http_status == 503


def test_one_transient_failure_is_retried(corpus):
    llm = Script(ProviderUnavailable("busy"), ANSWERABLE, GOOD)
    response, diag = service(corpus, llm).answer("Which enzyme does allopurinol inhibit?")
    assert response.outcome is Outcome.ANSWERED
    assert [a.get("error") for a in diag.attempts] == ["ProviderUnavailable", None, None]


def test_only_one_retry_per_request(corpus):
    llm = Script(ProviderUnavailable("busy"), ANSWERABLE, MalformedOutput("junk"))
    response, _ = service(corpus, llm).answer("Which enzyme does allopurinol inhibit?")
    assert response.outcome is Outcome.SERVICE_UNAVAILABLE
    assert len(llm.calls) == 3


def test_timeout_maps_to_504(corpus):
    response, diag = service(
        corpus, Script(ProviderTimeout("slow"), ProviderTimeout("slow"))
    ).answer("Which enzyme does allopurinol inhibit?")
    assert response.outcome is Outcome.SERVICE_UNAVAILABLE
    assert diag.http_status == 504


def test_provider_errors_do_not_reach_the_response(corpus):
    response, _ = service(corpus, Script(QuotaExhausted("secret detail"))).answer(
        "q about allopurinol"
    )
    assert "secret detail" not in response.model_dump_json()


@pytest.mark.parametrize(("question", "match"), [("   ", "empty"), ("x" * 2001, "longer than")])
def test_input_is_validated_before_any_provider_call(corpus, question, match):
    llm = Script()
    with pytest.raises(InputError, match=match):
        service(corpus, llm).answer(question)
    assert llm.calls == []
