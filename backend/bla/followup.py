"""Signed follow-up tokens.

An answered (or not-enough-evidence) response carries a token binding the
recent exchanges of the conversation: each question as the service answered it
and the answer items shown. A follow-up request presents the token with the new
question; the server rewrites the follow-up into a standalone question using
only what the signature covers, so a browser cannot plant an earlier "answer"
the service never gave.

The token holds the last MAX_EXCHANGES exchanges. Each follow-up answer issues a
new token with its own exchange appended and the oldest dropped, so a
conversation of any length works without the token growing and without any
server-side conversation store.

Like clarification tokens, these are signed, not encrypted: they hold the
user's own questions and the answers already shown to that user. The signing
key is derived separately, so a clarification token never verifies as a
follow-up token or the other way round.
"""

import hashlib
import hmac
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from bla.clarification import InvalidToken, _b64, _unb64

POLICY_VERSION = "2"
"""2: several exchanges per token. Bump when the follow-up rules change:
outstanding tokens then stop verifying."""

TOKEN_LIFETIME_SECONDS = 3600
MAX_EXCHANGES = 10
MAX_QUESTION_CHARS = 1000
"""Context for the rewrite, not the question itself: a longer one is cut."""
MAX_ITEMS = 10
MAX_ITEM_CHARS = 150


@dataclass(frozen=True)
class Exchange:
    """A question as the service answered it, and the items shown. No items
    means the collection did not support an answer."""

    question: str
    items: tuple[str, ...]


class FollowUpSigner:
    def __init__(
        self,
        secret: str,
        lifetime: int = TOKEN_LIFETIME_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if len(secret) < 32:
            raise ValueError("follow-up secret must be at least 32 characters")
        self._key = hmac.new(secret.encode(), b"bla-followup", hashlib.sha256).digest()
        self._lifetime = lifetime
        self._clock = clock

    def issue(self, history: Sequence[Exchange]) -> str:
        """`history` is oldest first; only the last MAX_EXCHANGES are kept."""
        payload = {
            "v": POLICY_VERSION,
            "h": [
                {
                    "q": e.question[:MAX_QUESTION_CHARS],
                    "i": [item[:MAX_ITEM_CHARS] for item in e.items[:MAX_ITEMS]],
                }
                for e in history[-MAX_EXCHANGES:]
            ],
            "exp": int(self._clock()) + self._lifetime,
        }
        body = _b64(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode())
        return f"{body}.{_b64(self._sign(body))}"

    def verify(self, token: str) -> tuple[Exchange, ...]:
        body, dot, signature = token.partition(".")
        if not dot:
            raise InvalidToken("malformed token")
        try:
            given = _unb64(signature)
            payload = json.loads(_unb64(body))
        except ValueError as exc:
            raise InvalidToken("malformed token") from exc
        # Signature before anything else: unsigned content is not read.
        if not hmac.compare_digest(given, self._sign(body)):
            raise InvalidToken("bad signature")
        if payload.get("v") != POLICY_VERSION:
            raise InvalidToken("issued under a different policy")
        if not isinstance(payload.get("exp"), int) or self._clock() >= payload["exp"]:
            raise InvalidToken("expired")
        return tuple(Exchange(question=e["q"], items=tuple(e["i"])) for e in payload["h"])

    def _sign(self, body: str) -> bytes:
        return hmac.new(self._key, body.encode(), hashlib.sha256).digest()
