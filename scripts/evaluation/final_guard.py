"""Guards for the one-time held-out test run (technical PRD 9.1, 9.3).

The test split may be run only with a frozen configuration that is committed
before the run, only from a clean working tree, only when every setting in
use matches the frozen values, and only once. A later "improved" run is a new,
separately identified evaluation cycle; it never overwrites this result
(implementation plan, Milestone 6).
"""

from __future__ import annotations

import json
import pathlib
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[2]


class GuardError(SystemExit):
    pass


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.strip()


def load_frozen(config_path: pathlib.Path) -> dict:
    """The frozen configuration, which must be committed and unchanged."""
    rel = config_path.resolve().relative_to(REPO)
    if not _git("ls-files", str(rel)):
        raise GuardError(f"{rel} is not committed; commit the frozen config before the test run")
    if _git("status", "--porcelain"):
        raise GuardError("working tree is not clean; the test run must use committed code only")
    return json.loads(config_path.read_text())


def check_matches(frozen: dict, actual: dict) -> None:
    """Every frozen setting must equal the value actually in use."""
    mismatched = {k: (frozen.get(k), v) for k, v in actual.items() if frozen.get(k) != v}
    if mismatched:
        lines = "\n".join(f"  {k}: frozen {f!r}, in use {a!r}" for k, (f, a) in mismatched.items())
        raise GuardError(f"configuration differs from the frozen config:\n{lines}")


def check_first_run(pattern: str) -> None:
    existing = sorted((REPO / "evaluation" / "results").glob(pattern))
    if existing:
        names = ", ".join(p.name for p in existing)
        raise GuardError(
            f"a held-out result already exists ({names}). The test split is run once; "
            "a new evaluation cycle needs a new frozen config and must not overwrite it."
        )


def commit() -> str:
    return _git("rev-parse", "HEAD")
