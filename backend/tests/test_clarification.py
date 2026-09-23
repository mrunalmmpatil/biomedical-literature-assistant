import pytest

from bla import clarification
from bla.clarification import Clarification, ClarificationSigner, InvalidToken

SECRET = "s" * 32
ASKED = Clarification(
    question="Which variants affect it?",
    prompt="Which gene do you mean by 'it'?",
    request_id="req-1",
)


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def signer(clock):
    return ClarificationSigner(SECRET, clock=clock)


def test_round_trip_returns_exactly_what_was_signed(signer):
    assert signer.verify(signer.issue(ASKED)) == ASKED


def test_non_ascii_questions_survive(signer):
    asked = Clarification("Does TNF-α rise?", "In which tissue?", "r")
    assert signer.verify(signer.issue(asked)) == asked


def test_token_expires_after_its_lifetime(signer, clock):
    token = signer.issue(ASKED)
    clock.now += clarification.TOKEN_LIFETIME_SECONDS - 1
    assert signer.verify(token) == ASKED
    clock.now += 1
    with pytest.raises(InvalidToken, match="expired"):
        signer.verify(token)


def test_edited_question_is_rejected(signer):
    _, signature = signer.issue(ASKED).split(".")
    forged = ClarificationSigner(SECRET).issue(
        Clarification("Something else entirely?", ASKED.prompt, ASKED.request_id)
    )
    with pytest.raises(InvalidToken, match="signature"):
        signer.verify(f"{forged.split('.')[0]}.{signature}")


def test_token_from_another_secret_is_rejected(signer):
    other = ClarificationSigner("t" * 32)
    with pytest.raises(InvalidToken, match="signature"):
        signer.verify(other.issue(ASKED))


def test_policy_change_invalidates_outstanding_tokens(signer, monkeypatch):
    token = signer.issue(ASKED)
    monkeypatch.setattr(clarification, "POLICY_VERSION", "2")
    with pytest.raises(InvalidToken, match="policy"):
        signer.verify(token)


@pytest.mark.parametrize("token", ["", "no-dot", "a.b", "!!!.???", "e30.AAAA"])
def test_malformed_tokens_are_rejected_not_crashed_on(signer, token):
    with pytest.raises(InvalidToken):
        signer.verify(token)


def test_short_secrets_are_refused():
    with pytest.raises(ValueError, match="32"):
        ClarificationSigner("too-short")
