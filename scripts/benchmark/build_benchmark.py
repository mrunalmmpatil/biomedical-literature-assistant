"""Milestone 2: build the 100-question benchmark and its controlled collection.

    cd backend
    uv run python ../scripts/benchmark/build_benchmark.py ../data/bioasq/training14b.json

Steps, all fixed before any system result exists (technical PRD 3.1-3.3):

1. Structural eligibility over every BioASQ record (bla/benchmark/bioasq.py).
2. Duplicate/paraphrase grouping over the eligible questions.
3. Seeded walk over groups; fetch reference papers for a prefix of the walk;
   select 50 fact + 50 list questions whose snippets are found in the fetched
   source text; split each type 25/25 (bla/benchmark/select.py).
4. Collection = every reference paper of the 100 questions, plus the top-K
   PubMed "similar articles" of each resolved reference paper. The neighbour
   rule uses paper IDs only, never question text or answers, and applies
   identically to development and test questions.

Outputs:

    data/benchmark/<name>/questions.jsonl   evaluation-only: answers, labels, split
    data/benchmark/<name>/raw/              reference-paper efetch responses
    data/corpus/<name>/                     collection snapshot (raw, papers, manifest)
    evaluation/manifests/<name>.json        tracked: IDs, counts, hashes; no answers

Re-running reuses saved responses, so it reproduces the same snapshot.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from bla.benchmark import bioasq
from bla.benchmark.select import QuotaNotMet, Split, candidate_order, select, shared_pmids
from bla.config import settings
from bla.ingest.pubmed import PubMedClient
from bla.ingest.snapshot import fetch_neighbors, fetch_papers, sha256, write_snapshot
from bla.retrieval.vector import MAX_EMBED_CHARS

SEED = 20260923
"""Chosen once, on the day the procedure was fixed, before any selection ran."""

EMBED_TOKEN_ALLOWANCE = 5_000_000
"""Pinecone Starter: llama-text-embed-v2 tokens per month (feasibility report 3)."""


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("dataset", type=pathlib.Path)
    p.add_argument("--name", default="bioasq14b-v1")
    p.add_argument("--seed", type=int, default=SEED)
    p.add_argument("--per-type", type=int, default=50)
    p.add_argument(
        "--prefix-groups",
        type=int,
        default=300,
        help="groups whose reference papers are fetched before selecting; "
        "a longer prefix cannot change the selection, only whether it completes",
    )
    p.add_argument("--neighbors", type=int, default=3, help="similar articles per reference paper")
    args = p.parse_args()

    raw_bytes = args.dataset.read_bytes()
    records = json.loads(raw_bytes)["questions"]
    client = PubMedClient(api_key=settings.ncbi_api_key, email=settings.ncbi_email)
    bench_dir = REPO / "data" / "benchmark" / args.name
    corpus_dir = REPO / "data" / "corpus" / args.name

    # 1-2. Eligibility and grouping.
    eligible, ineligible = bioasq.load(records)
    groups = bioasq.group(eligible)
    group_sizes = collections.Counter(groups.values())
    print(f"== {len(records)} records; {len(eligible)} structurally eligible")
    for reason, n in collections.Counter(i.reason.value for i in ineligible).most_common():
        print(f"  ineligible {reason}: {n}")
    print(
        f"  {len(group_sizes)} groups ({sum(1 for n in group_sizes.values() if n > 1)} multi-member)"
    )

    # 3. Seeded walk and selection.
    ordered = candidate_order(eligible, groups, args.seed)
    prefix = ordered[: args.prefix_groups]
    prefix_pmids = [pmid for members in prefix for q in members for pmid in q.pmids]
    print(f"== fetching reference papers for the first {len(prefix)} groups")
    gold_papers, _ = fetch_papers(prefix_pmids, bench_dir / "raw", client)
    papers_by_pmid = {paper.pmid: paper for paper in gold_papers}
    try:
        selection = select(prefix, papers_by_pmid, args.seed, args.per_type)
    except QuotaNotMet as exc:
        raise SystemExit(f"{exc}. Re-run with a larger --prefix-groups.") from exc
    by_id = {q.id: q for q in eligible}
    chosen = {qid: by_id[qid] for qid in selection.selected}
    print(
        f"== selected {len(chosen)} after examining {selection.examined_groups} groups; "
        f"{len(selection.rejected)} rejected for evidence"
    )

    bench_dir.mkdir(parents=True, exist_ok=True)
    (bench_dir / "questions.jsonl").write_text(
        "".join(
            json.dumps({**chosen[qid].model_dump(mode="json"), "split": split.value}) + "\n"
            for qid, split in sorted(selection.selected.items())
        )
    )

    # 4. Collection: reference papers plus similar articles.
    reference = list(dict.fromkeys(pmid for q in chosen.values() for pmid in q.pmids))
    resolved_reference = [pmid for pmid in reference if pmid in papers_by_pmid]
    neighbor_map = fetch_neighbors(resolved_reference, corpus_dir / "raw", client)
    requested = list(reference)
    seen = set(requested)
    for pmid in resolved_reference:
        # The top-K links per paper, counting links already in the set, so the
        # rule does not reach further down one paper's list to compensate.
        for neighbor, _score in neighbor_map.get(pmid, [])[: args.neighbors]:
            if neighbor not in seen:
                seen.add(neighbor)
                requested.append(neighbor)
    print(f"== collection: {len(reference)} reference + {len(requested) - len(reference)} related")
    papers, exclusions = fetch_papers(requested, corpus_dir / "raw", client)
    in_corpus = {paper.pmid for paper in papers}
    excluded_reason = {e.pmid: e.reason for e in exclusions}

    coverage = {}
    for qid, q in chosen.items():
        missing = [pmid for pmid in q.pmids if pmid not in in_corpus]
        coverage[qid] = {
            "reference": len(q.pmids),
            "in_collection": len(q.pmids) - len(missing),
            "missing": {pmid: excluded_reason.get(pmid, "not_requested") for pmid in missing},
        }

    chars = [len(p.title) + 1 + len(p.abstract) for p in papers]
    total_chars = sum(chars)
    corpus_manifest = write_snapshot(
        corpus_dir,
        args.name,
        requested,
        papers,
        exclusions,
        extra={
            "benchmark": args.name,
            "reference_pmids": len(reference),
            "related_pmids": len(requested) - len(reference),
            "neighbors_per_reference": args.neighbors,
        },
    )

    # Tracked manifest: identifiers, counts, and hashes only.
    split_types = collections.Counter(
        (split.value, chosen[qid].type.value) for qid, split in selection.selected.items()
    )
    manifest = {
        "name": args.name,
        "rules_version": bioasq.RULES_VERSION,
        "dataset": {
            "source": "BioASQ Task B training 14b (participants-area.bioasq.org)",
            "file": args.dataset.name,
            "sha256": sha256(raw_bytes),
            "records": len(records),
            "terms": "Registration required; NLM terms apply. Not redistributed.",
            "type_mapping": {"factoid": "fact", "list": "list"},
        },
        "procedure": {
            "seed": args.seed,
            "per_type": args.per_type,
            "grouping": {
                "text_similar": bioasq.TEXT_SIMILAR,
                "docs_similar": bioasq.DOCS_SIMILAR,
                "docs_same_source": bioasq.DOCS_SAME_SOURCE,
            },
            "prefix_groups_fetched": len(prefix),
            "neighbors_per_reference": args.neighbors,
        },
        "eligibility": {
            "structurally_eligible": len(eligible),
            "ineligible": dict(
                collections.Counter(i.reason.value for i in ineligible).most_common()
            ),
            "groups": len(group_sizes),
            "multi_member_groups": sum(1 for n in group_sizes.values() if n > 1),
            "groups_examined": selection.examined_groups,
            "rejected_for_evidence": dict(
                collections.Counter(r.value for r in selection.rejected.values())
            ),
        },
        "selection": {
            "distribution": {f"{s}/{t}": n for (s, t), n in sorted(split_types.items())},
            "questions": {
                split.value: sorted(qid for qid, s in selection.selected.items() if s is split)
                for split in Split
            },
            "reference_pmids_shared_across_splits": len(shared_pmids(chosen, selection.selected)),
        },
        "collection": {
            "papers": len(papers),
            "papers_sha256": corpus_manifest["papers_sha256"],
            "reference_pmids": len(reference),
            "related_pmids_requested": len(requested) - len(reference),
            "exclusions": corpus_manifest["exclusions"],
            "source_status": corpus_manifest["source_status"],
            "retrieved_on": corpus_manifest["retrieved_on"],
            "searchable_chars": corpus_manifest["searchable_chars"],
            "over_embed_limit": sum(1 for n in chars if n > MAX_EMBED_CHARS),
            "reference_coverage": {
                "questions_fully_covered": sum(
                    1 for c in coverage.values() if c["in_collection"] == c["reference"]
                ),
                "reference_pmids_missing": sum(len(c["missing"]) for c in coverage.values()),
                "missing_by_reason": dict(
                    collections.Counter(
                        reason for c in coverage.values() for reason in c["missing"].values()
                    )
                ),
            },
            "estimated_embedding_tokens": {
                "at_4_chars_per_token": round(total_chars / 4),
                "at_3_chars_per_token": round(total_chars / 3),
                "monthly_allowance": EMBED_TOKEN_ALLOWANCE,
            },
        },
    }
    manifest_path = REPO / "evaluation" / "manifests" / f"{args.name}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    (bench_dir / "coverage.json").write_text(json.dumps(coverage, indent=1) + "\n")

    print(json.dumps({k: manifest[k] for k in ("eligibility", "selection")}, indent=1)[:3000])
    print(json.dumps(manifest["collection"], indent=1))
    print(f"== wrote {manifest_path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
