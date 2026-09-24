"""POST /api/answer admission, duplicates, and failure mapping, with a fake
store and a stub service (no provider calls)."""

import pytest
from fastapi.testclient import TestClient

import app as app_module
from bla.answering.service import Diagnostics, InputError
from bla.contracts import AnswerResponse, Outcome
from bla.quota import DailyCeilingReached, Quota, StoreUnavailable
from tests.test_quota import Clock, FakeRedis


class StubService:
    def __init__(self):
        self.calls = 0
        self.raise_next = None

    def answer(self, question, clarification_token=None, clarification_answer=None):
        self.calls += 1
        if self.raise_next:
            exc, self.raise_next = self.raise_next, None
            raise exc
        response = AnswerResponse(
            request_id="r", outcome=Outcome.INSUFFICIENT_EVIDENCE, message="m"
        )
        return response, Diagnostics()


@pytest.fixture
def api(monkeypatch):
    clock = Clock()
    quota = Quota(FakeRedis(clock), salt="s", client_limit=2, daily_ceiling=100, clock=clock)
    stub = StubService()
    monkeypatch.setattr(app_module, "_generation_blocker", lambda: None)
    monkeypatch.setattr(app_module, "_quota", lambda: quota)
    monkeypatch.setattr(app_module, "_service", lambda: stub)
    return TestClient(app_module.app), stub


def ask(client, key=None, question="Which enzyme does X inhibit?"):
    body = {"question": question}
    if key:
        body["request_key"] = key
    return client.post("/api/answer", json=body)


def test_visitor_is_limited_per_hour(api):
    client, stub = api
    assert ask(client).status_code == 200
    assert ask(client).status_code == 200
    third = ask(client)
    assert third.status_code == 429
    assert "questions per hour" in third.json()["message"]
    assert stub.calls == 2


def test_duplicate_submission_is_answered_once(api):
    client, stub = api
    first = ask(client, key="k-1")
    again = ask(client, key="k-1")
    assert first.status_code == again.status_code == 200
    assert first.json() == again.json()
    assert stub.calls == 1  # the second click replayed the stored result


def test_request_key_reused_for_another_question_is_refused(api):
    client, _ = api
    ask(client, key="k-1")
    assert ask(client, key="k-1", question="A different question?").status_code == 409


def test_daily_site_ceiling_maps_to_429(api):
    client, stub = api
    stub.raise_next = DailyCeilingReached("spent")
    response = ask(client, key="k-2")
    assert response.status_code == 429
    assert "daily question limit" in response.json()["message"]
    stub.raise_next = None
    assert ask(client, key="k-2").status_code == 200  # the key was released


def test_input_errors_are_400_and_release_the_key(api):
    client, stub = api
    stub.raise_next = InputError("The question is empty.")
    assert ask(client, key="k-3").status_code == 400
    assert ask(client, key="k-3").status_code == 200


def test_unreachable_store_fails_closed(api, monkeypatch):
    client, stub = api

    class Down:
        client_limit = 5

        def client_key(self, address):
            return "c"

        def admit(self, client):
            raise StoreUnavailable("down")

    monkeypatch.setattr(app_module, "_quota", lambda: Down())
    response = ask(client)
    assert response.status_code == 503
    assert stub.calls == 0
