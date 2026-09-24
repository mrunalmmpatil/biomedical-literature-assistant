"""Provider-request accounting for evaluation runs. Evaluation only.

The free tier allows about 50 requests per day (feasibility report 4), shared
with every other use of the key. Evaluation therefore:

- counts every dispatched request in a per-UTC-day ledger and stops before a
  configured ceiling, leaving headroom for manual checks;
- caches successful completions by (model, prompt text, schema), so a re-run
  or re-scoring spends nothing. A cached completion is marked, and its latency
  is the original measurement. Failures are never cached.

The cache key contains the full prompts, which contain the prompt version and
the evidence, so a changed prompt, corpus, or model is a cache miss.
"""

import hashlib
import json
import pathlib
from dataclasses import asdict
from datetime import UTC, datetime

from bla.llm import Completion

DEFAULT_DAILY_CEILING = 45


class DailyBudgetReached(RuntimeError):
    pass


class DailyLedger:
    def __init__(self, directory: pathlib.Path, ceiling: int = DEFAULT_DAILY_CEILING) -> None:
        self.directory = directory
        self.ceiling = ceiling
        directory.mkdir(parents=True, exist_ok=True)

    def _path(self) -> pathlib.Path:
        return self.directory / f"{datetime.now(UTC):%Y-%m-%d}.json"

    def used(self) -> int:
        path = self._path()
        return json.loads(path.read_text())["requests"] if path.exists() else 0

    def charge(self) -> None:
        used = self.used()
        if used >= self.ceiling:
            raise DailyBudgetReached(f"{used} requests today; ceiling {self.ceiling}")
        self._path().write_text(json.dumps({"requests": used + 1}))


class CachingLLM:
    def __init__(self, inner, cache_dir: pathlib.Path, ledger: DailyLedger) -> None:
        self._inner = inner
        self.model = inner.model
        self._cache_dir = cache_dir
        self._ledger = ledger
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.hits = 0
        self.dispatched = 0

    def complete(self, system, user, schema_name, schema, timeout=None) -> Completion:
        key = hashlib.sha256(
            json.dumps([self.model, system, user, schema_name, schema], sort_keys=True).encode()
        ).hexdigest()
        path = self._cache_dir / f"{key}.json"
        if path.exists():
            self.hits += 1
            return Completion(**{**json.loads(path.read_text()), "cached": True})
        self._ledger.charge()  # before dispatch: a failed request still counts
        self.dispatched += 1
        completion = self._inner.complete(system, user, schema_name, schema, timeout=timeout)
        path.write_text(json.dumps(asdict(completion)))
        return completion
