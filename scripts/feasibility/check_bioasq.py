"""Milestone 1 probe: inspect a downloaded BioASQ Task B dataset.

Runs entirely offline against a file you download after registering at
participants-area.bioasq.org. It answers the milestone 1 question "is there
enough eligible material?" without selecting or tuning anything: it counts
questions by type and reports how many carry the fields the project needs.

Eligibility here is deliberately structural only. Choosing the 100 questions,
the seed, and the split belongs to milestone 2.

    uv run python ../scripts/feasibility/check_bioasq.py path/to/training14b.json
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

# The project answers "fact and list" questions. BioASQ's own vocabulary calls
# the first of these "factoid" — same thing, and the manifest should say so.
WANTED_TYPES = {"factoid", "list"}


def snippet_has_offsets(s: dict) -> bool:
    return all(
        k in s for k in ("offsetInBeginSection", "offsetInEndSection", "beginSection", "document")
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dataset", type=pathlib.Path, help="BioASQ Task B JSON file")
    args = p.parse_args()

    if not args.dataset.exists():
        print(f"Not found: {args.dataset}")
        print("Register at https://participants-area.bioasq.org/ and download Task B data.")
        return 2

    raw = json.loads(args.dataset.read_text())
    questions = raw.get("questions", raw if isinstance(raw, list) else [])
    print(f"== {args.dataset.name}: {len(questions)} questions ==\n")

    by_type = collections.Counter(q.get("type", "?") for q in questions)
    print("== questions by type ==")
    for t, n in by_type.most_common():
        mark = "  <- in scope" if t in WANTED_TYPES else ""
        print(f"  {t:<10} {n:>6}{mark}")
    print()

    candidates = [q for q in questions if q.get("type") in WANTED_TYPES]
    print(f"== structural eligibility across {len(candidates)} factoid/list questions ==")

    counts = collections.Counter()
    pmids: set[str] = set()
    per_question_docs = []
    for q in candidates:
        has_exact = bool(q.get("exact_answer"))
        docs = q.get("documents") or []
        snips = q.get("snippets") or []
        counts["has_exact_answer"] += has_exact
        counts["has_documents"] += bool(docs)
        counts["has_snippets"] += bool(snips)
        counts["snippets_with_offsets"] += bool(snips) and all(
            snippet_has_offsets(s) for s in snips
        )
        if has_exact and docs and snips:
            counts["fully_eligible"] += 1
            per_question_docs.append(len(docs))
        for d in docs:
            pmids.add(str(d).rstrip("/").split("/")[-1])

    for label in (
        "has_exact_answer",
        "has_documents",
        "has_snippets",
        "snippets_with_offsets",
        "fully_eligible",
    ):
        print(f"  {label:<24} {counts[label]:>6}")
    print()

    print("== corpus implication ==")
    print(f"  distinct referenced PMIDs across candidates: {len(pmids)}")
    if per_question_docs:
        avg = sum(per_question_docs) / len(per_question_docs)
        print(f"  mean gold documents per eligible question: {avg:.1f}")
        print(f"  gold documents for a 100-question set:     ~{avg * 100:.0f} abstracts")
        print("  plus related-topic papers, which milestone 2 sizes against the")
        print("  Pinecone 5M tokens/month embedding allowance.")
    print()

    gate = counts["fully_eligible"] >= 100
    print(f"  need >= 100 fully eligible; found {counts['fully_eligible']}  ->  "
          f"{'PASS' if gate else 'FAIL (report the data limitation, do not invent labels)'}")
    return 0 if gate else 1


if __name__ == "__main__":
    sys.exit(main())
