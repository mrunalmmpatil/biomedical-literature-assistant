"""Shared admission control and request state (technical PRD 8.1-8.2).

Backed by Upstash Redis over its REST API, so every serverless instance sees
the same counters; process memory is never used as a global count. Three
controls, all atomic on the Redis side:

- Per-visitor admission: at most CLIENT_LIMIT answer requests per hour per
  pseudonymous client key (a salted hash of the network address that expires
  with its window). This is an abuse limit, not an identity: IP addresses do
  not reliably identify people.
- Site-wide provider ceiling: every provider attempt is counted before it is
  dispatched, against a daily ceiling set below the account's verified free
  allowance, leaving room for development.
- Request keys: a client-generated key binds one question. The same key with
  different content is refused; a duplicate while the first is running does
  not start a second generation; a finished result is returned again for a
  short time.

If the store cannot be reached, generation fails closed (8.2).
"""

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

CLIENT_LIMIT = 5
CLIENT_WINDOW_SECONDS = 3600
DAILY_ATTEMPT_CEILING = 300
"""Public share of the 1,000/day free allowance (feasibility report 4a)."""
REQUEST_KEY_SECONDS = 600
"""In-flight lease and completed-result lifetime for a request key."""


class StoreUnavailable(RuntimeError):
    """The shared store did not answer: fail closed."""


class AdmissionDenied(RuntimeError):
    """This visitor is over the hourly limit (HTTP 429)."""


class DailyCeilingReached(RuntimeError):
    """The site-wide provider ceiling for today is spent (HTTP 429)."""


class KeyConflict(RuntimeError):
    """The request key was used for different content, or is still running (HTTP 409)."""


class Store:
    """The Redis commands this module uses."""

    def pipeline(self, commands: list[list[str]]) -> list: ...


class UpstashStore(Store):
    def __init__(self, url: str, token: str, http: httpx.Client | None = None) -> None:
        self._url = url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}
        self._http = http or httpx.Client(timeout=5)

    def pipeline(self, commands: list[list[str]]) -> list:
        try:
            response = self._http.post(
                f"{self._url}/pipeline", json=commands, headers=self._headers
            )
            response.raise_for_status()
            results = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise StoreUnavailable(f"quota store: {exc.__class__.__name__}") from exc
        if any("error" in r for r in results):
            raise StoreUnavailable("quota store returned an error")
        return [r["result"] for r in results]


@dataclass(frozen=True)
class Stored:
    fingerprint: str
    status: str  # "running" | "done"
    body: dict | None
    http_status: int | None


class Quota:
    def __init__(
        self,
        store: Store,
        salt: str,
        client_limit: int = CLIENT_LIMIT,
        daily_ceiling: int = DAILY_ATTEMPT_CEILING,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._salt = salt
        self.client_limit = client_limit
        self.daily_ceiling = daily_ceiling
        self._clock = clock

    # --- per-visitor admission ----------------------------------------------

    def client_key(self, address: str) -> str:
        """Pseudonymous and expiring: the salt rotates the hash daily."""
        day = datetime.fromtimestamp(self._clock(), UTC).strftime("%Y-%m-%d")
        digest = hashlib.sha256(f"{self._salt}|{day}|{address}".encode()).hexdigest()
        return digest[:24]

    def admit(self, client: str) -> int:
        """Counts this request; raises AdmissionDenied past the limit.
        Returns the number of requests this window, including this one."""
        window = int(self._clock() // CLIENT_WINDOW_SECONDS)
        key = f"bla:client:{client}:{window}"
        _, count = self._store.pipeline(
            [["SET", key, "0", "EX", str(CLIENT_WINDOW_SECONDS), "NX"], ["INCR", key]]
        )
        if int(count) > self.client_limit:
            raise AdmissionDenied(f"over {self.client_limit} requests this hour")
        return int(count)

    # --- site-wide provider ceiling -----------------------------------------

    def charge_attempt(self) -> int:
        """Called before every provider dispatch (8.1)."""
        day = datetime.fromtimestamp(self._clock(), UTC).strftime("%Y-%m-%d")
        key = f"bla:attempts:{day}"
        _, count = self._store.pipeline(
            [["SET", key, "0", "EX", str(2 * 86400), "NX"], ["INCR", key]]
        )
        if int(count) > self.daily_ceiling:
            raise DailyCeilingReached("site-wide daily provider ceiling reached")
        return int(count)

    # --- request keys ---------------------------------------------------------

    @staticmethod
    def fingerprint(payload: dict) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def begin(self, request_key: str, fingerprint: str) -> Stored | None:
        """Claim the key. None means the caller should run the request; a
        Stored result means return that; KeyConflict means refuse."""
        key = f"bla:request:{request_key}"
        lease = json.dumps({"fingerprint": fingerprint, "status": "running"})
        claimed, existing = self._store.pipeline(
            [["SET", key, lease, "EX", str(REQUEST_KEY_SECONDS), "NX"], ["GET", key]]
        )
        if claimed == "OK":
            return None
        record = json.loads(existing) if existing else None
        if record is None:
            return None
        if record["fingerprint"] != fingerprint:
            raise KeyConflict("this request key was already used for a different question")
        if record["status"] == "running":
            raise KeyConflict("this question is already being answered")
        return Stored(fingerprint, "done", record.get("body"), record.get("http_status"))

    def finish(self, request_key: str, fingerprint: str, body: dict, http_status: int) -> None:
        record = json.dumps(
            {"fingerprint": fingerprint, "status": "done", "body": body, "http_status": http_status}
        )
        self._store.pipeline(
            [["SET", f"bla:request:{request_key}", record, "EX", str(REQUEST_KEY_SECONDS)]]
        )

    def release(self, request_key: str) -> None:
        """Drop an in-flight lease after an unexpected failure, so a retry can run."""
        self._store.pipeline([["DEL", f"bla:request:{request_key}"]])


class MeteredLLM:
    """Charges the site-wide ceiling before each provider attempt."""

    def __init__(self, inner, quota: Quota) -> None:
        self._inner = inner
        self._quota = quota
        self.model = inner.model

    def complete(self, system, user, schema_name, schema, timeout=None):
        self._quota.charge_attempt()
        return self._inner.complete(system, user, schema_name, schema, timeout=timeout)
