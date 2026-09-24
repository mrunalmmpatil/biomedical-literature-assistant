"""Shared admission control against an in-memory Redis stand-in."""

import httpx
import pytest

from bla.quota import (
    AdmissionDenied,
    DailyCeilingReached,
    KeyConflict,
    MeteredLLM,
    Quota,
    StoreUnavailable,
    UpstashStore,
)


class FakeRedis:
    """SET (EX, NX), INCR, GET, DEL with expiry on a controllable clock."""

    def __init__(self, clock):
        self.data = {}
        self.clock = clock

    def _live(self, key):
        value = self.data.get(key)
        if value and value[1] is not None and value[1] <= self.clock():
            del self.data[key]
            return None
        return value

    def pipeline(self, commands):
        out = []
        for cmd in commands:
            op, key = cmd[0], cmd[1]
            if op == "SET":
                ttl = int(cmd[cmd.index("EX") + 1]) if "EX" in cmd else None
                if "NX" in cmd and self._live(key):
                    out.append(None)
                    continue
                self.data[key] = [cmd[2], self.clock() + ttl if ttl else None]
                out.append("OK")
            elif op == "INCR":
                current = self._live(key) or ["0", None]
                current[0] = str(int(current[0]) + 1)
                self.data[key] = current
                out.append(int(current[0]))
            elif op == "GET":
                value = self._live(key)
                out.append(value[0] if value else None)
            elif op == "DEL":
                out.append(1 if self.data.pop(key, None) else 0)
        return out


class Clock:
    def __init__(self, t=1_790_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def quota(clock):
    return Quota(FakeRedis(clock), salt="s", client_limit=2, daily_ceiling=3, clock=clock)


def test_visitor_limit_resets_with_the_window(quota, clock):
    client = quota.client_key("203.0.113.9")
    assert quota.admit(client) == 1
    assert quota.admit(client) == 2
    with pytest.raises(AdmissionDenied):
        quota.admit(client)
    clock.t += 3600
    assert quota.admit(client) == 1


def test_client_keys_are_pseudonymous_and_rotate_daily(quota, clock):
    first = quota.client_key("203.0.113.9")
    assert "203" not in first and len(first) == 24
    assert quota.client_key("203.0.113.10") != first
    clock.t += 86400
    assert quota.client_key("203.0.113.9") != first


def test_site_ceiling_stops_provider_dispatch(quota):
    class Inner:
        model = "m"
        calls = 0

        def complete(self, *args, **kwargs):
            Inner.calls += 1
            return "ok"

    llm = MeteredLLM(Inner(), quota)
    for _ in range(3):
        llm.complete("s", "u", "n", {})
    with pytest.raises(DailyCeilingReached):
        llm.complete("s", "u", "n", {})
    assert Inner.calls == 3  # counted before dispatch, so the 4th never went out


def test_request_key_runs_once_and_replays_the_result(quota):
    fp = quota.fingerprint({"question": "q"})
    assert quota.begin("k1", fp) is None
    with pytest.raises(KeyConflict, match="already being answered"):
        quota.begin("k1", fp)
    quota.finish("k1", fp, {"outcome": "answered"}, 200)
    stored = quota.begin("k1", fp)
    assert stored.body == {"outcome": "answered"} and stored.http_status == 200


def test_request_key_reused_for_different_content_is_refused(quota):
    quota.begin("k1", quota.fingerprint({"question": "a"}))
    with pytest.raises(KeyConflict, match="different question"):
        quota.begin("k1", quota.fingerprint({"question": "b"}))


def test_released_lease_can_run_again(quota):
    fp = quota.fingerprint({"question": "q"})
    quota.begin("k1", fp)
    quota.release("k1")
    assert quota.begin("k1", fp) is None


def test_unreachable_store_fails_closed():
    def down(request):
        raise httpx.ConnectError("no route")

    store = UpstashStore(
        "https://kv.test", "t", http=httpx.Client(transport=httpx.MockTransport(down))
    )
    with pytest.raises(StoreUnavailable):
        store.pipeline([["INCR", "x"]])


def test_upstash_pipeline_wire_format():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = request.content
        return httpx.Response(200, json=[{"result": "OK"}, {"result": 1}])

    store = UpstashStore(
        "https://kv.test/", "tok", http=httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert store.pipeline([["SET", "k", "0", "EX", "60", "NX"], ["INCR", "k"]]) == ["OK", 1]
    assert seen["url"] == "https://kv.test/pipeline"
    assert seen["auth"] == "Bearer tok"
