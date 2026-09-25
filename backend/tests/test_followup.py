"""Follow-up questions: signed tokens, the rewrite step, and the guarantee that
the single-question pipeline evaluated as final-v1 is unchanged."""

import hashlib
import json

import pytest

from bla import followup
from bla.answering import prompts
from bla.answering.service import AnswerService, InputError
from bla.clarification import ClarificationSigner, InvalidToken
from bla.contracts import Outcome
from bla.followup import Exchange, FollowUpSigner
from bla.retrieval.bm25 import BM25Retriever
from tests.test_answering import ANSWERABLE, GOOD, NOT_SUPPORTED, OUT_OF_SCOPE, SECRET, Script


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


def followup_assessment(standalone, decision="answerable", clarification=""):
    return {
        "standalone_question": standalone,
        "decision": decision,
        "clarification_question": clarification,
        "reason": "x",
    }


def service(corpus, llm, followups=True):
    return AnswerService(
        BM25Retriever(corpus),
        {p.pmid: p for p in corpus},
        llm,
        ClarificationSigner(SECRET),
        corpus_version="test-v1",
        followups=FollowUpSigner(SECRET) if followups else None,
    )


# --- tokens -------------------------------------------------------------------


def one(question, items=()):
    return FollowUpSigner(SECRET).issue([Exchange(question, tuple(items))])


def test_token_round_trip():
    signer = FollowUpSigner(SECRET)
    history = (
        Exchange("Which enzyme does allopurinol inhibit?", ("xanthine oxidase",)),
        Exchange("Which disease is allopurinol used for?", ()),
    )
    assert signer.verify(signer.issue(history)) == history


def test_token_expires():
    clock = Clock()
    signer = FollowUpSigner(SECRET, clock=clock)
    token = signer.issue([Exchange("q", ())])
    clock.now += followup.TOKEN_LIFETIME_SECONDS
    with pytest.raises(InvalidToken, match="expired"):
        signer.verify(token)


def test_tampered_token_is_rejected():
    signer = FollowUpSigner(SECRET)
    _, signature = signer.issue([Exchange("q", ("a",))]).split(".")
    forged = FollowUpSigner("t" * 40).issue([Exchange("q", ("planted answer",))]).split(".")[0]
    with pytest.raises(InvalidToken, match="signature"):
        signer.verify(f"{forged}.{signature}")


def test_clarification_and_followup_tokens_are_not_interchangeable():
    from bla.clarification import Clarification

    clarification = ClarificationSigner(SECRET).issue(Clarification("q", "p", "r"))
    with pytest.raises(InvalidToken):
        FollowUpSigner(SECRET).verify(clarification)
    with pytest.raises(InvalidToken):
        ClarificationSigner(SECRET).verify(one("q"))


def test_token_contents_are_bounded():
    signer = FollowUpSigner(SECRET)
    history = [Exchange(f"{n:02}" + "q" * 10_000, ("i" * 500,) * 50) for n in range(13)]
    kept = signer.verify(signer.issue(history))
    # The most recent exchanges are kept, oldest first.
    assert [e.question[:2] for e in kept] == [f"{n:02}" for n in range(3, 13)]
    assert len(kept) == followup.MAX_EXCHANGES
    for exchange in kept:
        assert len(exchange.question) == followup.MAX_QUESTION_CHARS
        assert len(exchange.items) == followup.MAX_ITEMS
        assert all(len(i) == followup.MAX_ITEM_CHARS for i in exchange.items)
    # Even at the bounds the token fits the API's request limit.
    worst = [Exchange("α" * 10_000, ("α" * 500,) * 50)] * 13
    assert len(signer.issue(worst)) < 131072


# --- the frozen single-question pipeline ---------------------------------------


def test_single_question_prompts_are_those_evaluated_as_final_v1():
    frozen = [
        prompts.ASSESS_SYSTEM,
        prompts.ASSESS_SCHEMA,
        prompts.GENERATE_SYSTEM,
        prompts.GENERATE_SCHEMA,
        prompts.RETRY_FEEDBACK,
    ]
    digest = hashlib.sha256(json.dumps(frozen, sort_keys=True).encode()).hexdigest()
    assert prompts.PROMPT_VERSION == "2"
    assert digest == "da9b871504f6990d0e5c58a75296f3c439b1d4984ad2f1f3c4f6bf529d5787ea"


def test_without_a_signer_no_followup_token_is_issued(corpus):
    response, _ = service(corpus, Script(ANSWERABLE, GOOD), followups=False).answer(
        "Which enzyme does allopurinol inhibit?"
    )
    assert response.outcome is Outcome.ANSWERED
    assert response.followup_token is None and response.interpreted_question is None


def test_without_a_signer_followups_are_refused(corpus):
    llm = Script()
    with pytest.raises(InputError, match="not available"):
        service(corpus, llm, followups=False).answer("And in mice?", followup_token="x.y")
    assert llm.calls == []


# --- the follow-up flow --------------------------------------------------------


def test_answered_and_insufficient_responses_can_be_followed_up(corpus):
    answered, _ = service(corpus, Script(ANSWERABLE, GOOD)).answer(
        "Which enzyme does allopurinol inhibit?"
    )
    (exchange,) = FollowUpSigner(SECRET).verify(answered.followup_token)
    assert exchange.items == ("xanthine oxidase",)
    insufficient, _ = service(corpus, Script(ANSWERABLE, NOT_SUPPORTED)).answer(
        "allopurinol dose in cats?"
    )
    (exchange,) = FollowUpSigner(SECRET).verify(insufficient.followup_token)
    assert exchange.items == ()


def test_unsupported_responses_cannot_be_followed_up(corpus):
    response, _ = service(corpus, Script(OUT_OF_SCOPE)).answer("Should I stop my medication?")
    assert response.followup_token is None


def test_followup_is_rewritten_then_answered_as_a_standalone_question(corpus):
    first, _ = service(corpus, Script(ANSWERABLE, GOOD)).answer(
        "Which enzyme does allopurinol inhibit?"
    )
    standalone = "Which disease is allopurinol used to manage?"
    llm = Script(followup_assessment(standalone), GOOD)
    second, diag = service(corpus, llm).answer(
        "What disease is it used for?", followup_token=first.followup_token
    )
    assert second.outcome is Outcome.ANSWERED
    assert second.interpreted_question == standalone
    assert llm.calls == ["followup_assessment", "answer"]
    # The rewrite sees the earlier exchange ...
    assert "Which enzyme does allopurinol inhibit?" in llm.users[0]
    assert "- xanthine oxidase" in llm.users[0]
    assert "What disease is it used for?" in llm.users[0]
    # ... generation sees only the standalone question, as for any question.
    assert llm.users[1].startswith(f"<question>\n{standalone}\n</question>")
    assert "xanthine oxidase\n" not in llm.users[1].split("<source")[0]
    assert diag.followup_prompt_version == prompts.FOLLOWUP_PROMPT_VERSION
    # The conversation continues from the rewritten question, not the raw follow-up.
    history = FollowUpSigner(SECRET).verify(second.followup_token)
    assert [e.question for e in history] == ["Which enzyme does allopurinol inhibit?", standalone]


def test_every_recent_exchange_is_context_for_the_rewrite(corpus):
    history = [
        Exchange("Which enzyme does allopurinol inhibit?", ("xanthine oxidase",)),
        Exchange("Which drug is first-line for type 2 diabetes?", ("metformin",)),
    ]
    token = FollowUpSigner(SECRET).issue(history)
    llm = Script(followup_assessment("Which disease is allopurinol used to manage?"), GOOD)
    response, _ = service(corpus, llm).answer(
        "Back to the first drug: what disease is it for?", followup_token=token
    )
    assert response.outcome is Outcome.ANSWERED
    prompt = llm.users[0]
    assert prompt.index("allopurinol inhibit") < prompt.index("type 2 diabetes")
    assert '<exchange n="1">' in prompt and '<exchange n="2">' in prompt
    assert "- metformin" in prompt
    assert len(FollowUpSigner(SECRET).verify(response.followup_token)) == 3


def test_out_of_scope_followup_is_unsupported(corpus):
    token = one("Which enzyme does allopurinol inhibit?", ["x"])
    llm = Script(followup_assessment("", decision="out_of_scope"))
    response, _ = service(corpus, llm).answer("Should I take it?", followup_token=token)
    assert response.outcome is Outcome.UNSUPPORTED_REQUEST
    assert response.followup_token is None


def test_followup_may_ask_one_clarification_about_the_rewritten_question(corpus):
    token = one("Which enzyme does allopurinol inhibit?", ["x"])
    svc = service(
        corpus,
        Script(followup_assessment("What is the dose?", "needs_clarification", "Which drug?")),
    )
    first, _ = svc.answer("And the dose?", followup_token=token)
    assert first.outcome is Outcome.NEEDS_CLARIFICATION
    assert first.interpreted_question == "What is the dose?"
    assert ClarificationSigner(SECRET).verify(first.clarification.token).question == (
        "What is the dose?"
    )


def test_a_rewrite_that_returns_no_question_is_service_unavailable(corpus):
    token = one("q")
    response, diag = service(corpus, Script(followup_assessment("  "))).answer(
        "and?", followup_token=token
    )
    assert response.outcome is Outcome.SERVICE_UNAVAILABLE
    assert "standalone" in diag.internal_reason


def test_expired_or_tampered_followup_token_is_an_input_error(corpus):
    llm = Script()
    with pytest.raises(InputError, match="expired"):
        service(corpus, llm).answer("And in mice?", followup_token="bogus.token")
    assert llm.calls == []


def test_clarification_and_followup_together_are_refused(corpus):
    with pytest.raises(InputError, match="both"):
        service(corpus, Script()).answer(
            "q", clarification_token="a.b", clarification_answer="x", followup_token="c.d"
        )
