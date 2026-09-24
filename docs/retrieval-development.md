# Milestone 3 — Retrieval comparison (development split)

Status: **baseline frozen 2026-09-23** as
[`evaluation/configs/retrieval-baseline-v1.json`](../evaluation/configs/retrieval-baseline-v1.json).

These are **development results on 50 questions** in a controlled 3,653-paper
collection ([data protocol](data-protocol.md)). The 50 held-out test questions
were not run. The results say nothing about searching all of PubMed.

| Record | Path |
|---|---|
| Run metadata and aggregates | [`evaluation/results/retrieval-development-20260923T234633Z.json`](../evaluation/results/retrieval-development-20260923T234633Z.json) |
| Paired analysis | [`…T234633Z.analysis.json`](../evaluation/results/retrieval-development-20260923T234633Z.analysis.json) |
| Per-question retrieved and missed PMIDs | `evaluation/runs/retrieval-development-20260923T234633Z/` (untracked: contains labels) |
| Index version | [`evaluation/manifests/index-bioasq14b-v1.u1.json`](../evaluation/manifests/index-bioasq14b-v1.u1.json) |

## Setup

- **Query input:** the benchmark question text only. No reference answer,
  snippet, or label reaches either retriever, and the generation model is
  never called.
- **Searchable units:** one per paper ("title\nabstract"). Only the 15
  papers over 6,000 characters are split into 41 sentence-bounded passages,
  for 3,679 units in total. A paper scores as its best unit. Both methods
  index exactly the same units.
- **BM25:** Okapi with k1 = 1.5 and b = 0.75, using the project tokenizer v1
  (lowercase, no stemming, biomedical identifiers kept whole). It runs in
  process.
- **Vector:** Pinecone index `bla-collection`, namespace `bioasq14b-v1.u1`,
  llama-text-embed-v2 (1024 dimensions, cosine). It requests 30 candidates
  and returns 10 unique papers.
- **Scoring:** paper level, de-duplicated. Relevant papers are the
  question's reference PMIDs that are in the collection; all 50 development
  questions have at least one. Settings are the starting defaults from
  technical PRD 5 and 8.1. **Nothing was tuned on these results.**

## Results

| n = 50 | BM25 | Vector | Vector − BM25, paired bootstrap 95% CI |
|---|---:|---:|---|
| Recall@5 | 0.493 | 0.510 | +0.017 [−0.016, +0.051] |
| Recall@10 | 0.639 | 0.652 | +0.013 [−0.029, +0.058] |
| MRR@10 | 0.832 | 0.804 | −0.028 [−0.104, +0.049] |
| Questions with ≥ 1 relevant paper in the top 10 | 50 | 50 | |
| Search latency p50 / p95 | 3 / 7 ms | 164 / 242 ms | |

| By type | Recall@10 BM25 | Recall@10 Vector | MRR@10 BM25 | MRR@10 Vector |
|---|---:|---:|---:|---:|
| Fact (25) | 0.599 | 0.607 | 0.863 | 0.799 |
| List (25) | 0.678 | 0.696 | 0.800 | 0.808 |

Questions where each method did better:

| Metric | Vector better | BM25 better | Tie |
|---|---:|---:|---:|
| Recall@5 | 11 | 9 | 30 |
| Recall@10 | 13 | 13 | 24 |
| MRR@10 | 7 | 10 | 33 |

**Finding: on this development set, the two methods are not
distinguishable.** Every confidence interval includes zero, and neither method
wins more questions. **No claim that one method is better is supported.**

Latency is the one clear difference. BM25 runs in process, while vector
search makes a network round trip to Pinecone that includes embedding the
query. Both are far inside the 90-second request budget.

## Why recall is below 1

**Recall@10 has a ceiling.** Reference papers per question range from 1 to 84,
with a median of 7, and 20 of the 50 questions list more than 10. A question
with 84 reference papers can reach at most 10/84 = 0.12. The mean ceiling is
**0.840**. Against that ceiling, BM25 reaches 0.759 and vector 0.765 of what
is achievable.

**Where missed papers rank.** Each method missed 345 relevant papers from
its top 10. Re-querying at depth 50:

| Missed paper's rank at depth 50 | BM25 | Vector |
|---|---:|---:|
| 11–20 | 118 (34%) | 100 (29%) |
| 21–50 | 130 (38%) | 140 (41%) |
| Not in the top 50 | 97 (28%) | 105 (30%) |

About a third of the misses are near misses, ranked 11–20. The rest reflect
ranking or vocabulary gaps, and some probably reflect BioASQ's own labels:
reference lists for broad questions include papers that are only loosely
related to the question text.

**The methods miss different papers.** Taking the union of both top-10
lists gives Recall@10 of **0.760**, against 0.639 and 0.652 for each method
alone. Keyword and semantic matching find different relevant papers. This is
the strongest lead for improvement. Hybrid retrieval is an optional
experiment under technical PRD 5, and any version of it must be evaluated on
development data as its own configuration before any test run.

## Decisions

- **Both baselines are retained and frozen** as `retrieval-baseline-v1`.
- **Depth stays at 10.** Supplying up to 5 papers to generation is revisited
  in Milestone 4, measured on answer quality, not retrieval alone.
- **Primary demo method: not yet decided.** Retrieval quality does not
  separate the methods. The choice will weigh generation results (Milestone
  4) and operating cost. BM25 costs nothing per query and needs its index
  deployed with the backend. Vector search uses Pinecone read units and
  query-embedding tokens, and it may handle lay phrasing better. That is
  untested here, because BioASQ questions are written by experts.
- **Hybrid retrieval was tried and not adopted.** See the next section.

## Hybrid experiment: retrieval-hybrid-v2 (registered, not adopted)

The union result above prompted one experiment. **Its configuration was
committed before it ran** ([`retrieval-hybrid-v2.json`](../evaluation/configs/retrieval-hybrid-v2.json),
commit `3a82f82`):

- reciprocal rank fusion, score = Σ 1 / (60 + rank), using the constant from
  Cormack et al. (2009) untuned;
- the top 50 candidates from each of BM25 and vector search, weighted
  equally;
- the top 10 fused papers returned. Fusion uses ranks only, so a BM25 score
  and a cosine similarity are never added together.

**Hypothesis:** fusion raises development Recall@10 above both baselines.

Run [`retrieval-development-20260924T021439Z`](../evaluation/results/retrieval-development-20260924T021439Z.json)
(analysis: [`….analysis.json`](../evaluation/results/retrieval-development-20260924T021439Z.analysis.json)).
BM25 and vector reproduced their earlier results exactly.

| n = 50 | BM25 | Vector | Hybrid |
|---|---:|---:|---:|
| Recall@5 | 0.493 | 0.510 | 0.481 |
| Recall@10 | 0.639 | 0.652 | **0.662** |
| MRR@10 | 0.832 | 0.804 | 0.797 |
| Recall@10 relative to ceiling | 0.759 | 0.765 | 0.781 |
| Missed papers not in the top 50 | 97 | 105 | 85 |
| Search latency p50 | 3 ms | 172 ms | 169 ms |

| Paired difference | Mean | 95% CI | Questions better / worse / tied |
|---|---:|---|---|
| Hybrid − BM25, Recall@10 | +0.023 | [−0.012, +0.058] | 15 / 8 / 27 |
| Hybrid − Vector, Recall@10 | +0.010 | [−0.021, +0.040] | 12 / 6 / 32 |
| Hybrid − BM25, Recall@5 | −0.012 | [−0.041, +0.017] | 10 / 7 / 33 |
| Hybrid − Vector, Recall@5 | −0.029 | [−0.059, −0.003] | 6 / 9 / 35 |
| Hybrid − BM25, MRR@10 | −0.035 | [−0.092, +0.017] | 6 / 7 / 37 |
| Hybrid − Vector, MRR@10 | −0.007 | [−0.083, +0.069] | 6 / 8 / 36 |

**Outcome: the hypothesis is not supported.** The Recall@10 gains are small,
and both intervals include zero. The hybrid wins more questions than it
loses, but by small amounts. It is **worse at Recall@5** than vector search:
fusion pushes some relevant papers from the top 5 down to ranks 6–10. Nine
paired comparisons were made, so one interval excluding zero is weak
evidence on its own. Still, it points the wrong way for Milestone 4, which
supplies up to the top 5 papers to generation.

The union's 0.760 did not carry over because the union is an oracle over 20
papers, both top-10 lists together. A fused list still has to choose 10.

**Decision:** retrieval-hybrid-v2 is **not adopted**. `retrieval-baseline-v1`
(BM25 and vector) remains the frozen configuration. As registered, no
variant (another rrf_k, weights, or depth) is tried on these 50 development
questions. Such a search would tune on the same small set that reports the
result. The fusion code stays in the repository (`bla/retrieval/hybrid.py`),
tested and unused.

## Operational notes

- Indexing 3,679 units took about 10 minutes, paced under Pinecone Starter's
  **250,000 embedding tokens per minute**, a limit measured when the first
  unpaced attempt was throttled. The build is resumable and never re-embeds
  a stored record.
- Title sanity queries: 5 of 5 papers retrieved at rank 1.
- The comparison used 100 vector queries (50 at depth 10 and 50 at depth 50),
  which is negligible against the Starter read and embedding allowances.
