"""Signed clarification tokens (technical PRD 6.1).

When a question needs one more detail, the server returns a token binding the
original question, the clarification it asked, the request ID, and the policy
version. The follow-up request presents the token with the user's answer; the
server trusts only what the signature covers, never a browser flag claiming
assessment already happened.

The token is signed, not encrypted: it carries the user's own question and our
prompt, both already visible to that user. It grants no free provider calls
(section 8.1) and holds no conversation beyond this one step.

A token can be replayed until it expires. Duplicate suppression belongs to the
shared request-key store (section 8.2), not to the token.
"""

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Callable
from dataclasses import dataclass

POLICY_VERSION = "1"
"""Bump when assessment rules change: outstanding tokens then stop verifying."""

TOKEN_LIFETIME_SECONDS = 600  # section 8.1: 10 minutes


@dataclass(frozen=True)
class Clarification:
    question: str
    prompt: str
    request_id: str


class InvalidToken(ValueError):
    """Tampered, malformed, expired, or issued under another policy. Callers
    answer all of these the same way: ask the question again."""


class ClarificationSigner:
    def __init__(
        self,
        secret: str,
        lifetime: int = TOKEN_LIFETIME_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if len(secret) < 32:
            raise ValueError("clarification secret must be at least 32 characters")
        self._key = secret.encode()
        self._lifetime = lifetime
        self._clock = clock

    def issue(self, clarification: Clarification) -> str:
        payload = {
            "v": POLICY_VERSION,
            "q": clarification.question,
            "p": clarification.prompt,
            "r": clarification.request_id,
            "exp": int(self._clock()) + self._lifetime,
        }
        body = _b64(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode())
        return f"{body}.{_b64(self._sign(body))}"

    def verify(self, token: str) -> Clarification:
        body, dot, signature = token.partition(".")
        if not dot:
            raise InvalidToken("malformed token")
        try:
            given = _unb64(signature)
            payload = json.loads(_unb64(body))
        except ValueError as exc:  # binascii.Error and JSONDecodeError are ValueErrors
            raise InvalidToken("malformed token") from exc
        # Signature before anything else: unsigned content is not read.
        if not hmac.compare_digest(given, self._sign(body)):
            raise InvalidToken("bad signature")
        if payload.get("v") != POLICY_VERSION:
            raise InvalidToken("issued under a different policy")
        if not isinstance(payload.get("exp"), int) or self._clock() >= payload["exp"]:
            raise InvalidToken("expired")
        return Clarification(question=payload["q"], prompt=payload["p"], request_id=payload["r"])

    def _sign(self, body: str) -> bytes:
        return hmac.new(self._key, body.encode(), hashlib.sha256).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
