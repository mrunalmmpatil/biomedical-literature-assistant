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
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from bla.config import settings
from bla.ingest.pubmed import PubMedClient
from bla.ingest.snapshot import fetch_papers, sha256, write_snapshot


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


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("pmid_file", type=pathlib.Path)
    p.add_argument("--name", required=True, help="snapshot directory name under data/corpus/")
    args = p.parse_args()

    pmids = read_pmids(args.pmid_file)
    if not pmids:
        raise SystemExit("no PMIDs in input")
    out = REPO / "data" / "corpus" / args.name
    print(f"== {len(pmids)} PMIDs ({len(set(pmids))} unique) -> {out.relative_to(REPO)}")

    client = PubMedClient(api_key=settings.ncbi_api_key, email=settings.ncbi_email)
    papers, exclusions = fetch_papers(pmids, out / "raw", client)
    manifest = write_snapshot(
        out,
        args.name,
        pmids,
        papers,
        exclusions,
        extra={"input_sha256": sha256(args.pmid_file.read_bytes())},
    )

    print(f"== {len(papers)} papers, {len(exclusions)} exclusions")
    for reason, count in manifest["exclusions"].items():
        print(f"  excluded {reason}: {count}")
    print(f"  searchable text length (chars): {manifest['searchable_chars']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
