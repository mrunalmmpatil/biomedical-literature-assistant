"""Resumable, frozen snapshots of PubMed responses (technical PRD 3.3).

Every response is saved exactly as received, next to a small JSON record of
what was asked for, when, and the response hash. A later run with the same
request reads the saved bytes instead of calling NCBI, so re-running
reproduces a snapshot rather than silently refreshing it. Delete the raw
directory to refetch deliberately.
"""

import collections
import hashlib
import json
import pathlib
import statistics
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime

from bla.contracts import Paper
from bla.ingest.pubmed import (
    NEIGHBOR_BATCH_SIZE,
    Exclusion,
    PubMedClient,
    batches,
    parse_neighbors,
    parse_pubmed_xml,
)


class SnapshotMismatch(RuntimeError):
    """A saved batch was made for a different request, or its bytes changed."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def cached_batches(
    kind: str,
    todo: Sequence[list[str]],
    raw: pathlib.Path,
    fetch: Callable[[list[str]], bytes],
    log: Callable[[str], None] = print,
) -> list[tuple[list[str], bytes, date]]:
    """Fetch each batch once. Files are `<kind>-NNNN.xml` plus `.json`."""
    raw.mkdir(parents=True, exist_ok=True)
    results = []
    for number, batch in enumerate(todo, start=1):
        xml_path = raw / f"{kind}-{number:04d}.xml"
        meta_path = raw / f"{kind}-{number:04d}.json"
        if xml_path.exists() and meta_path.exists():
            meta = json.loads(meta_path.read_text())
            xml = xml_path.read_bytes()
            if meta["pmids"] != batch or meta["sha256"] != sha256(xml):
                raise SnapshotMismatch(
                    f"{xml_path} was saved for a different request or has changed; "
                    "use a new snapshot name."
                )
            results.append((batch, xml, date.fromisoformat(meta["retrieved_on"])))
            continue
        xml = fetch(batch)
        today = datetime.now(UTC).date()  # UTC: independent of the machine's zone
        xml_path.write_bytes(xml)
        meta_path.write_text(
            json.dumps(
                {"pmids": batch, "retrieved_on": today.isoformat(), "sha256": sha256(xml)},
                indent=1,
            )
        )
        log(f"  {kind} {number}/{len(todo)}: fetched {len(batch)} PMIDs")
        results.append((batch, xml, today))
    return results


def fetch_papers(
    pmids: Sequence[str], raw: pathlib.Path, client: PubMedClient
) -> tuple[list[Paper], list[Exclusion]]:
    papers: list[Paper] = []
    exclusions: list[Exclusion] = []
    for batch, xml, retrieved_on in cached_batches("batch", batches(pmids), raw, client.efetch):
        got, excluded = parse_pubmed_xml(xml, batch, retrieved_on)
        papers.extend(got)
        exclusions.extend(excluded)
    return papers, exclusions


def fetch_neighbors(
    pmids: Sequence[str], raw: pathlib.Path, client: PubMedClient
) -> dict[str, list[tuple[str, int]]]:
    todo = batches(pmids, NEIGHBOR_BATCH_SIZE)
    result: dict[str, list[tuple[str, int]]] = {}
    for _, xml, _ in cached_batches("neighbors", todo, raw, client.neighbors):
        result.update(parse_neighbors(xml))
    return result


def write_snapshot(
    out: pathlib.Path,
    name: str,
    requested: Sequence[str],
    papers: Sequence[Paper],
    exclusions: Sequence[Exclusion],
    extra: dict | None = None,
) -> dict:
    """papers.jsonl, exclusions.jsonl, and manifest.json; returns the manifest."""
    papers_blob = "".join(p.model_dump_json() + "\n" for p in papers).encode()
    (out / "papers.jsonl").write_bytes(papers_blob)
    (out / "exclusions.jsonl").write_text(
        "".join(json.dumps({"pmid": e.pmid, "reason": e.reason}) + "\n" for e in exclusions)
    )
    lengths = sorted(len(p.title) + 1 + len(p.abstract) for p in papers)
    manifest = {
        "name": name,
        "requested_sha256": sha256("\n".join(requested).encode()),
        "requested_unique": len(set(requested)),
        "papers": len(papers),
        "papers_sha256": sha256(papers_blob),
        "exclusions": dict(collections.Counter(e.reason for e in exclusions)),
        "source_status": dict(collections.Counter(p.source_status.value for p in papers)),
        "retrieved_on": sorted({p.retrieved_on.isoformat() for p in papers}),
        "searchable_chars": describe(lengths),
        **(extra or {}),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def read_papers(path: pathlib.Path) -> list[Paper]:
    return [Paper.model_validate_json(line) for line in path.read_text().splitlines() if line]


def describe(values: Sequence[int]) -> dict[str, int] | None:
    if not values:
        return None
    values = sorted(values)
    if len(values) == 1:
        return {"min": values[0], "p50": values[0], "p95": values[0], "max": values[0]}
    q = statistics.quantiles(values, n=100, method="inclusive")
    return {"min": values[0], "p50": round(q[49]), "p95": round(q[94]), "max": values[-1]}
