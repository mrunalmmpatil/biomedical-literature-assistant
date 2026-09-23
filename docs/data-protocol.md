# Milestone 2 — Benchmark and collection

Status: **built 2026-09-23**, benchmark `bioasq14b-v1`, rules version 1.
The tracked record is [`evaluation/manifests/bioasq14b-v1.json`](../evaluation/manifests/bioasq14b-v1.json).
It holds identifiers, counts, and hashes only. Question text, answers, and
snippets stay in `data/`, which is never committed.

**This is a controlled collection, not a full-PubMed benchmark.** It
deliberately contains the reference papers for every benchmark question,
plus related papers. Retrieval scores measure ranking within these 3,653
papers. They do not measure discovery across PubMed's 38M records.

## Source

| | |
|---|---|
| Release | BioASQ Task B training 14b (`BioASQ-training14b.zip`, README dated 2026-02-26) |
| File SHA-256 | `5669afbc0bbc8f50d54850edb4aa592ecff3e38b29b09ac6684bb52990b651b7` |
| Access | Registration at participants-area.bioasq.org; NLM terms apply |
| Redistribution | None. Neither the dataset nor PubMed abstracts are committed or served |
| Attribution | Krithara et al., *BioASQ-QA: A manually curated corpus for Biomedical Question Answering*, bioRxiv 2022.12.14.520213 |

Training 14b is cumulative, so it already contains every earlier year's
questions, including past test batches. The "golden enriched" files were not
downloaded: they would only add duplicates that could cross the split.

BioASQ calls the first question type *factoid*; the project calls it *fact*.
They are the same type.

## Procedure

Every rule below was fixed before any selection ran. None of them reads answer
content: an answer must exist and be well formed, nothing more.

### 1. Structural eligibility — [`bla/benchmark/bioasq.py`](../backend/bla/benchmark/bioasq.py)

Rules are checked in order, and each question records the first rule it fails.

| Rule | Excluded |
|---|---:|
| Type is not factoid or list | 2,904 |
| Question over the application's 2,000-character limit | 0 |
| No exact answer | 0 |
| Malformed exact answer (wrong nesting, blank variant) | 3 |
| No documents | 0 |
| A document URL that is not a PubMed link | 10 |
| No snippets | 0 |
| Any snippet outside the title or abstract | 147 |
| A snippet citing a document the question does not list | 0 |
| A malformed snippet (negative offset, end before start, empty text) | 7 |
| **Structurally eligible** | **2,658** |

A question with any full-text snippet is excluded outright rather than having
that snippet dropped. The project only has titles and abstracts, so part of
such a question's reference evidence would be unreachable.

### 2. Duplicate and paraphrase grouping

Word overlap alone is a poor test in BioASQ. Many questions share a template
and differ only in the entity ("Which molecule is targeted by X?"). A pair is
grouped when any of these holds:

- the question token sets are identical; or
- word Jaccard ≥ 0.5 and relevant-paper Jaccard ≥ 0.3, which catches
  paraphrases; or
- relevant-paper Jaccard ≥ 0.6, which catches distinct questions built on
  the same source paper.

The thresholds were set by reading sampled pairs of question text, not
answers. Grouping is transitive. Result: **2,593 groups, 53 of them with more
than one member.** At most one question per group is selected. So no question
and its paraphrase can both enter the set, and a family of questions that
share evidence cannot straddle the split.

### 3. Selection and split — [`bla/benchmark/select.py`](../backend/bla/benchmark/select.py)

- **Seed `20260923`**, chosen once, before any run.
- Groups are shuffled with the seed, and members are shuffled within each
  group. The procedure walks the groups and takes the first member whose type
  quota (50 fact, 50 list) is not full and whose evidence resolves.
- **Evidence resolves** when at least one benchmark snippet appears verbatim,
  after the collection's own text normalization, in the title or abstract
  independently fetched from PubMed. This checks that the support is inside
  the searchable text, not only in BioASQ's copy of it.
- Each type's 50 questions are shuffled with a derived seed and split 25/25.
- Each candidate is judged only on its own data, so fetching papers for a
  longer prefix of the walk cannot change the selection. A unit test enforces
  this.

Result: **123 groups examined; 1 question rejected** because no snippet was
found in its source text.

| | Fact | List |
|---|---:|---:|
| Development | 25 | 25 |
| Test | 25 | 25 |

**Reference papers shared across the splits: 0.**

### 4. Collection

- **Reference papers:** every document the 100 questions list (1,079 PMIDs).
- **Related papers:** for each resolved reference paper, the top 3 of
  PubMed's own similar-articles links (elink `pubmed_pubmed`,
  `neighbor_score`). This rule uses paper IDs only, never question text or
  answers, and applies identically to development and test questions. Links
  already in the collection count toward the 3, so no paper reaches further
  down its list to compensate. Result: 2,616 related PMIDs requested.
- Records are fetched with efetch and normalized by
  [`bla/ingest/pubmed.py`](../backend/bla/ingest/pubmed.py). Retracted records
  are excluded by policy. Every raw efetch and elink response is saved
  unchanged under `data/`, so the snapshot is frozen.

| Collection | |
|---|---:|
| Papers | **3,653** |
| Excluded: no abstract | 35 |
| Excluded: retracted | 6 |
| Excluded: not returned by PubMed | 1 |
| Source status: corrected / expression of concern | 75 / 1 |
| Papers SHA-256 | `3652a06b139458bf7efc2ed03441664b425de575a8bb25396ea51faa118deea9` |

**Reference coverage:** 96 of the 100 questions have every reference paper in
the collection. 4 reference PMIDs are missing: 2 retracted, 1 with no abstract,
and 1 not returned. Under technical PRD 3.3 these are data-coverage failures,
not retrieval failures, and evaluation will report them that way.

## Size and budget

| Measure | Value |
|---|---|
| Searchable text per paper (chars) | min 224 · median 1,671 · p95 2,850 · max 48,093 |
| Estimated embedding tokens, one full ingest | 1.6M (4 chars/token) – 2.1M (3 chars/token) |
| Pinecone Starter allowance | 5M tokens/month |

A full ingest uses 32–43% of the monthly allowance. That leaves room for one
re-index plus development queries in the same month. Storage (about 15 MB
of vectors) is negligible against the 2 GB limit.

### Passage decision

**One searchable unit per paper ("title + abstract"), except for overlong
records.** 15 of 3,653 papers (0.4%) exceed the 6,000-character embedding guard
in [`vector.py`](../backend/bla/retrieval/vector.py), and 99% of papers are under
4,160 characters. **None of the 15 is a reference paper.** They are related
papers: book chapters, Cochrane reviews, and long reviews. Milestone 3 splits
only these records into passages on sentence boundaries, with offsets into the
normalized text, as technical PRD 3.3 specifies. Pinecone would otherwise
truncate them silently (`truncate: END`).

## Reproducing

```bash
cd backend
uv run python ../scripts/benchmark/build_benchmark.py ../data/bioasq/training14b.json
```

A re-run reuses every saved PubMed response. It was verified on 2026-09-23 to
make zero network requests and to produce a byte-identical manifest and
question file. Deleting `data/corpus/bioasq14b-v1/raw/` or
`data/benchmark/bioasq14b-v1/raw/` refetches deliberately, which creates a new
snapshot that must get a new name.

| Output | Tracked | Contents |
|---|---|---|
| `evaluation/manifests/bioasq14b-v1.json` | yes | IDs, split assignment, counts, hashes |
| `data/benchmark/bioasq14b-v1/questions.jsonl` | no | questions, answers, snippets, split. **Evaluation only** |
| `data/benchmark/bioasq14b-v1/coverage.json` | no | per-question reference coverage |
| `data/corpus/bioasq14b-v1/` | no | raw responses, `papers.jsonl`, manifest |

## Separation guarantees

- The application never imports `bla.benchmark`; a test enforces this.
- Benchmark question text, answers, relevant-paper labels, and snippets are
  never indexed. Searchable text comes only from the fetched PubMed record.
- The tracked manifest was checked on 2026-09-23 to contain no question text,
  answer variant, or snippet fragment.
- The 50 test questions must not be run, read, or inspected during
  development. Settings, prompts, and the model are chosen on the 50
  development questions only (technical PRD 9.1).

## Known limitations

- **Controlled collection.** Retrieval results do not transfer to open PubMed
  search.
- **BioASQ labels are incomplete.** Related papers may also support an answer
  without being labeled relevant. Such hits count as misses in Recall@k, and
  the held-out set is not relabeled after results are seen.
- **The similar-articles links change over time.** The saved elink responses
  freeze this snapshot's choice.
- **Mixed question ages.** The set spans 2013–2025 BioASQ editions. Some
  answers, such as drug approvals, reflect the state of knowledge when the
  question was written.
