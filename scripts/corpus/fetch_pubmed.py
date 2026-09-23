"""Fetch titles/abstracts for a PMID list into a corpus snapshot directory.

    cd backend
    uv run python ../scripts/corpus/fetch_pubmed.py pmids.txt --name dev-probe

Input: one PMID per line; blank lines and `#` comments are ignored.
Output, under data/corpus/<name>/ (gitignored):

    raw/batch-NNNN.xml        efetch response exactly as received (the original)
    raw/batch-NNNN.json       the batch's PMIDs, retrieval date, and XML hash
    papers.jsonl              normalized Paper records, input order
    exclusions.jsonl          every requested PMID that is not a paper, with reason
    manifest.json             counts, hashes, and abstract-length statistics

Resumable: a batch whose raw XML is already saved for the same PMIDs is not
fetched again. Re-running therefore reproduces a snapshot rather than silently
refreshing it (technical PRD 3.3); delete raw/ to refetch deliberately.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import pathlib
import statistics
import sys
from datetime import UTC, date, datetime

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from bla.config import settings
from bla.ingest.pubmed import PubMedClient, batches, parse_pubmed_xml


def read_pmids(path: pathlib.Path) -> list[str]:
    pmids = []
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        value = line.split("#", 1)[0].strip()
        if not value:
            continue
        if not value.isdigit():
            raise SystemExit(f"{path}:{number}: {value!r} — PMIDs are digits only")
        pmids.append(value)
    return pmids


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_batches(pmids: list[str], raw: pathlib.Path) -> list[tuple[list[str], bytes, date]]:
    raw.mkdir(parents=True, exist_ok=True)
    client = PubMedClient(api_key=settings.ncbi_api_key, email=settings.ncbi_email)
    results = []
    todo = batches(pmids)
    for number, batch in enumerate(todo, start=1):
        xml_path = raw / f"batch-{number:04d}.xml"
        meta_path = raw / f"batch-{number:04d}.json"
        if xml_path.exists() and meta_path.exists():
            meta = json.loads(meta_path.read_text())
            xml = xml_path.read_bytes()
            if meta["pmids"] == batch and meta["sha256"] == sha256(xml):
                print(f"  batch {number}/{len(todo)}: cached")
                results.append((batch, xml, date.fromisoformat(meta["retrieved_on"])))
                continue
            raise SystemExit(
                f"{xml_path} was saved for a different PMID list or has changed. "
                "The input no longer matches this snapshot; use a new --name."
            )
        xml = client.efetch(batch)
        today = datetime.now(UTC).date()  # UTC: independent of the machine's zone
        xml_path.write_bytes(xml)
        meta_path.write_text(
            json.dumps(
                {"pmids": batch, "retrieved_on": today.isoformat(), "sha256": sha256(xml)},
                indent=1,
            )
        )
        print(f"  batch {number}/{len(todo)}: fetched {len(batch)} PMIDs")
        results.append((batch, xml, today))
    return results


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("pmid_file", type=pathlib.Path)
    p.add_argument("--name", required=True, help="snapshot directory name under data/corpus/")
    args = p.parse_args()

    pmids = read_pmids(args.pmid_file)
    if not pmids:
        raise SystemExit("no PMIDs in input")
    out = REPO / "data" / "corpus" / args.name
    print(f"== {len(pmids)} PMIDs ({len(set(pmids))} unique) -> {out.relative_to(REPO)}")

    papers, exclusions = [], []
    for batch, xml, retrieved_on in fetch_batches(pmids, out / "raw"):
        got, excluded = parse_pubmed_xml(xml, batch, retrieved_on)
        papers.extend(got)
        exclusions.extend(excluded)

    papers_blob = "".join(p.model_dump_json() + "\n" for p in papers).encode()
    (out / "papers.jsonl").write_bytes(papers_blob)
    (out / "exclusions.jsonl").write_text(
        "".join(json.dumps({"pmid": e.pmid, "reason": e.reason}) + "\n" for e in exclusions)
    )

    lengths = sorted(len(p.title) + 1 + len(p.abstract) for p in papers)
    manifest = {
        "name": args.name,
        "input_sha256": sha256(args.pmid_file.read_bytes()),
        "requested_unique": len(set(pmids)),
        "papers": len(papers),
        "papers_sha256": sha256(papers_blob),
        "exclusions": dict(collections.Counter(e.reason for e in exclusions)),
        "source_status": dict(collections.Counter(p.source_status.value for p in papers)),
        "retrieved_on": sorted({p.retrieved_on.isoformat() for p in papers}),
        "searchable_chars": _describe(lengths),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    print(f"== {len(papers)} papers, {len(exclusions)} exclusions")
    for reason, count in manifest["exclusions"].items():
        print(f"  excluded {reason}: {count}")
    print(f"  searchable text length (chars): {manifest['searchable_chars']}")
    return 0


def _describe(values: list[int]) -> dict[str, int] | None:
    if not values:
        return None
    q = statistics.quantiles(values, n=100, method="inclusive") if len(values) > 1 else values * 99
    return {"min": values[0], "p50": round(q[49]), "p95": round(q[94]), "max": values[-1]}


if __name__ == "__main__":
    sys.exit(main())
