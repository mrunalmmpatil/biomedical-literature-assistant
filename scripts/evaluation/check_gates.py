"""Check the technical PRD 9.3 hard gates on an answer run.

    cd backend
    uv run python ../scripts/evaluation/check_gates.py <run_id>

Reads evaluation/runs/<run_id>/questions.json and the frozen collection, and
checks every response independently of the code that produced it:

- complete accounting: every question in the split has exactly one row;
- distinct outcomes: each row carries one of the five defined outcomes;
- no unknown-source citations: every cited source ID belongs to a shown source;
- excerpts match source: each excerpt equals the stored text at its offsets.

Prints a pass/fail line per gate and exits non-zero on any failure.
"""

from __future__ import annotations

import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
OUTCOMES = {
    "answered",
    "needs_clarification",
    "insufficient_evidence",
    "unsupported_request",
    "service_unavailable",
}


def main() -> int:
    run_id = sys.argv[1]
    rows = json.loads((REPO / "evaluation" / "runs" / run_id / "questions.json").read_text())
    split = "test" if "-test-" in run_id else "development"
    expected = {
        json.loads(line)["id"]
        for line in (REPO / "data" / "benchmark" / "bioasq14b-v1" / "questions.jsonl")
        .read_text()
        .splitlines()
        if json.loads(line)["split"] == split
    }
    papers = {
        json.loads(line)["pmid"]: json.loads(line)
        for line in (REPO / "data" / "corpus" / "bioasq14b-v1" / "papers.jsonl")
        .read_text()
        .splitlines()
    }

    problems: dict[str, list[str]] = {
        "complete_accounting": [],
        "distinct_outcomes": [],
        "no_unknown_source_citations": [],
        "excerpts_match_source": [],
    }
    ids = [r["id"] for r in rows]
    if set(ids) != expected or len(ids) != len(set(ids)):
        problems["complete_accounting"].append(
            f"{len(set(ids))} unique of {len(expected)} expected; duplicates {len(ids) - len(set(ids))}"
        )
    excerpts_checked = citations_checked = 0
    for r in rows:
        if r["outcome"] not in OUTCOMES:
            problems["distinct_outcomes"].append(f"{r['id']}: {r['outcome']}")
        response = r.get("response")
        if not response:
            continue
        shown = {s["source_id"]: s for s in response["sources"]}
        answer = response.get("answer") or {}
        for part in answer.get("items", []) + answer.get("explanation_claims", []):
            for sid in part["source_ids"]:
                citations_checked += 1
                if sid not in shown:
                    problems["no_unknown_source_citations"].append(f"{r['id']}: {sid}")
        for s in response["sources"]:
            paper = papers.get(s["pmid"])
            for e in s["excerpts"]:
                excerpts_checked += 1
                text = paper[e["field"]] if paper else ""
                if paper is None or text[e["start"] : e["end"]] != e["text"]:
                    problems["excerpts_match_source"].append(f"{r['id']}: {s['pmid']} {e['start']}")

    failed = False
    print(
        f"== {run_id}: {len(rows)} rows; {citations_checked} citations; {excerpts_checked} excerpts"
    )
    for gate, found in problems.items():
        status = "PASS" if not found else f"FAIL ({len(found)}): {found[:3]}"
        failed |= bool(found)
        print(f"  {gate:<30} {status}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
