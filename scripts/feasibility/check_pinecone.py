"""Milestone 1 probe: Pinecone integrated embedding and retrieval round trip.

Verifies the things the technical PRD (section 5) says must not be assumed:
available dimensions, input limits, metric, and the actual SDK calls. Uses a
throwaway index and a handful of public non-benchmark abstracts.

    uv run python ../scripts/feasibility/check_pinecone.py
    uv run python ../scripts/feasibility/check_pinecone.py --keep   # leave index
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from pinecone import Pinecone

INDEX_NAME = "bla-feasibility-probe"
MODEL = "llama-text-embed-v2"
# Documented at fetch time: dimensions 384/512/768/1024/2048, max 2048 input tokens.
# This probe confirms what the account actually accepts.
DIMENSION = 1024
METRIC = "cosine"

# Short stand-in records. Deliberately NOT BioASQ items: smoke tests must not
# touch benchmark questions (technical PRD section 10).
RECORDS = [
    {
        "_id": "probe-1",
        "text": "Allopurinol and xanthine oxidase. Allopurinol is a xanthine oxidase "
        "inhibitor that lowers serum urate and is used in the long-term management of gout.",
    },
    {
        "_id": "probe-2",
        "text": "Metformin in type 2 diabetes. Metformin reduces hepatic glucose production "
        "and improves insulin sensitivity; it is a first-line oral agent for type 2 diabetes.",
    },
    {
        "_id": "probe-3",
        "text": "BRCA1 and hereditary breast cancer. Pathogenic BRCA1 variants substantially "
        "increase lifetime risk of breast and ovarian cancer and inform screening decisions.",
    },
    {
        "_id": "probe-4",
        "text": "Photosynthetic carbon fixation in C4 plants. PEP carboxylase concentrates CO2 "
        "in bundle sheath cells, reducing photorespiration relative to C3 pathways.",
    },
]

QUERY = "What drug blocks xanthine oxidase?"
EXPECTED_TOP = "probe-1"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--keep", action="store_true", help="do not delete the probe index")
    args = p.parse_args()

    key = os.environ.get("PINECONE_API_KEY")
    if not key:
        print("PINECONE_API_KEY is not set. Create the key, then:")
        print("  export PINECONE_API_KEY=pcsk_...")
        return 2

    pc = Pinecone(api_key=key)

    print("== existing indexes ==")
    for idx in pc.list_indexes():
        print(f"  {idx.name}  fields={list(idx.to_dict()['schema']['fields'])}")
    print()

    if not pc.has_index(INDEX_NAME):
        print(f"== creating index '{INDEX_NAME}' with integrated {MODEL} ==")
        pc.create_index_for_model(
            name=INDEX_NAME,
            cloud="aws",
            region="us-east-1",
            embed={
                "model": MODEL,
                "field_map": {"text": "text"},
                "metric": METRIC,
                "dimension": DIMENSION,
            },
        )
        print("  created")
    else:
        print(f"== reusing existing index '{INDEX_NAME}' ==")

    desc = pc.describe_index(INDEX_NAME)
    # Pinecone SDK 10 describes integrated-embedding indexes by schema field,
    # not by top-level dimension/metric.
    field = desc.to_dict()["schema"]["fields"]["text"]
    print(f"  host:      {desc.host}")
    print(f"  model:     {field['model']}")
    print(f"  metric:    {field['metric']}")
    print(f"  write:     {field['write_parameters']}")
    print(f"  read:      {field['read_parameters']}")
    print()

    index = pc.Index(INDEX_NAME)

    print(f"== upserting {len(RECORDS)} probe records ==")
    index.upsert_records(namespace="probe", records=RECORDS)
    print("  upserted; waiting for freshness")
    time.sleep(10)
    print(f"  stats: {index.describe_index_stats()}")
    print()

    print(f"== searching: {QUERY!r} ==")
    results = index.search(
        namespace="probe",
        query={"inputs": {"text": QUERY}, "top_k": 3},
        fields=["text"],
    )
    hits = results["result"]["hits"]
    for rank, hit in enumerate(hits, 1):
        snippet = hit.fields["text"][:70].replace("\n", " ")
        print(f"  {rank}. {hit.id}  score={hit.score:.4f}  {snippet}...")
    print()

    top = hits[0].id if hits else None
    ok = top == EXPECTED_TOP
    print(f"  expected top hit: {EXPECTED_TOP}; got: {top}  ->  {'PASS' if ok else 'FAIL'}")
    print("  NOTE: a similarity score is not medical confidence (technical PRD 4).")

    if not args.keep:
        print(f"\n== deleting probe index '{INDEX_NAME}' ==")
        pc.delete_index(INDEX_NAME)
        print("  deleted")
    else:
        print(f"\n  index '{INDEX_NAME}' kept; delete it before measuring the free-tier budget")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
