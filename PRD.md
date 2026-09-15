# PRD: Biomedical Literature Assistant (Cardiology)

Status: draft, version 1 scope
Last updated: 2026-09-15

## Problem Statement

Clinicians and researchers cannot keep up with the medical literature. PubMed holds over 35 million citations. When a clinician needs to know what the evidence says about a specific question, the options today are a PubMed keyword search that returns hundreds of results with no synthesis, or a general chatbot that answers fluently and sometimes invents citations.

What is missing is a tool that answers a clinical evidence question in a few sentences, cites the specific papers behind each statement, ranks stronger study designs above weaker ones, and says "not enough evidence" instead of guessing.

This is an evidence-lookup tool for professionals. It is not medical advice for patients.

## Solution

A retrieval-augmented question answering system over PubMed abstracts in cardiology.

A user asks a question in plain language. The system expands medical synonyms, searches the abstract collection with three stacked stages, weighs study design and recency, and produces a short answer where every statement carries an inline PubMed ID. When retrieval is weak, the system abstains rather than answering.

## Scope of Version 1

| Area | Decision |
|---|---|
| Purpose | Portfolio project, later tested by 3 to 5 real clinicians or researchers |
| Answer style | Short answers first. Long, exhaustive answers are a later phase |
| Timeline | No date. Version 1 is done when the feature list below is complete |
| Budget | Zero cost, permanently. Generation runs on OpenRouter free models |
| Request budget | Assume free requests are scarce. Design for roughly 50 per day until verified |
| Corpus | Cardiology. All publication types from the last 5 years, plus 2000 to 2020 restricted to randomized controlled trials, meta-analyses, systematic reviews and guidelines |
| Sources | PubMed abstracts in version 1. ClinicalTrials.gov added in a later phase. PMC full text is out of scope |
| Indexing unit | One whole abstract per stored item, title included. Only over-long abstracts are split into two overlapping halves |
| Retrieval | Three stages built and measured one at a time: dense retrieval, lexical retrieval, cross-encoder reranking |
| Query expansion | Local MeSH synonym dictionary applied to the lexical stage. No LLM-based query rewriting |
| Evaluation | A hand-built set of 50 cardiology questions first, then a filtered subset of BioASQ |

## User Stories

1. As a cardiology fellow, I want a short answer to a clinical evidence question, so that I can prepare for journal club without reading twenty abstracts.
2. As a clinician, I want every statement in the answer to carry a PubMed ID, so that I can verify the claim at its source.
3. As a clinician, I want the strongest study designs ranked first, so that I am not persuaded by a single case report.
4. As a clinician, I want to see the study type next to each cited paper, so that I can judge the weight of the evidence myself.
5. As a clinician, I want the tool to tell me when the evidence is insufficient, so that I do not act on a confident-sounding guess.
6. As a clinician, I want studies that disagree presented separately rather than merged, so that I can see that a question is unsettled.
7. As a clinician, I want landmark older trials to be findable, so that established evidence is not missing just because it is old.
8. As a clinician, I want synonyms handled, so that asking about a heart attack finds papers about myocardial infarction.
9. As a clinician, I want exact drug and trial names matched precisely, so that a question about a named trial returns that trial.
10. As a researcher, I want an option to see the full evidence list rather than a summary, so that I can use the tool for a literature scan. (Later phase.)
11. As a researcher, I want to filter by study type and publication year, so that I can narrow results to the evidence I trust.
12. As a user, I want to know when a cited paper has been retracted, so that I do not rely on withdrawn evidence. (Phase decision open.)
13. As a user, I want the tool to refuse personal medical advice, so that its role as a professional lookup tool stays clear.
14. As the developer, I want a measured score after each retrieval stage, so that I can show what each component contributed.
15. As the developer, I want the answer checking step to run mostly offline, so that scarce free API requests are spent on generation.
16. As the developer, I want each stored item labelled with its source, so that clinical trial records can be added later without reindexing.
17. As the developer, I want the generation model swappable through configuration, so that a free model disappearing does not break the system.
18. As the developer, I want evaluation runs reproducible, so that a change in ranking can be attributed to a specific code change.
19. As a tester, I want answers to arrive quickly enough to try ten questions in a sitting, so that giving feedback is not a chore.
20. As a tester, I want a simple way to report that an answer was wrong, so that failures reach the developer with their question attached.

## Implementation Decisions

### Corpus construction

- Cardiology is defined by MeSH descriptors under cardiovascular disease. The exact descriptor set and resulting record count are to be verified against the E-utilities API before the download runs.
- Two download passes: last 5 years unrestricted, and 2000 to 2020 restricted to high-tier publication types. The rationale is that landmark evidence predates a 5-year window, and high-tier types are a small fraction of total volume.
- Records are stored with: PubMed ID, title, abstract, journal, publication year, MeSH descriptors, publication types, retraction status, and a source label.
- Study type is taken from the PubMed publication type field. Recently added records may not yet carry it; a fallback is required and is an open decision.

### Indexing

- One embedding per abstract. Abstracts exceeding the encoder input limit are split into two overlapping halves, both pointing at the same PubMed ID.
- Dense embeddings come from a biomedical retrieval encoder, MedCPT being the default candidate, run once in bulk on a free GPU session.
- A lexical index is built alongside the dense index over the same text.
- Storage engine is an open decision, with a local vector database and a Postgres extension as the two candidates.

### Retrieval

- Stage one: dense retrieval over abstract embeddings.
- Stage two: lexical retrieval, with MeSH synonyms appended to the query terms.
- Stage three: cross-encoder reranking over a merged candidate set. Candidate depth is a tuning parameter with an initial target of 30 to 50, constrained by CPU latency on an Apple silicon laptop.
- Each stage is added and measured separately. The resulting per-stage score table is a required deliverable, not an optional extra.
- Ranking adjustments for study design and recency are applied as additive bonuses to the relevance score rather than as a hard sort, so that an exact match cannot be displaced by a weakly related review. Weights are tuned against the hand-built evaluation set. Final form is an open decision.

### Generation and verification

- Generation runs against an OpenRouter free model, selected through configuration so it can be swapped in one place.
- Every cited PubMed ID must appear in the retrieved set. Citations outside that set are removed before display.
- The claim-level verification method is an open decision: a second model call, a local entailment model, or a local model with escalation to a model call only for uncertain claims.
- Abstention behaviour and its threshold are an open decision.

### Interface

- Presentation layer choice is an open decision between a minimal Python app and a full web front end.
- The answer view shows the answer text with inline citations, followed by an evidence list carrying study type and year per paper.

## Testing Decisions

Good tests here assert externally observable behaviour: given a question, which PubMed IDs are retrieved, in what order, and whether the answer abstains. They do not assert internal scores or intermediate data structures.

### Evaluation sets

1. Hand-built set, 50 cardiology questions, built first. Approximately 40 answerable questions drawn from five major cardiology areas, plus approximately 10 that must trigger abstention: out-of-specialty questions, questions with no published evidence, requests for personal medical advice, and questions naming a non-existent drug.
   - Gold PubMed IDs are taken from guideline and review reference lists rather than from the system's own search output, to avoid circularity.
   - Each question records gold papers, the expected strongest study type, the expected answer direction, and the expected year range.
   - The set is frozen before tuning begins.
2. Filtered BioASQ, built second. Only questions whose gold documents fall inside the corpus are kept. Used as an external check on retrieval quality.
3. PubMedQA is not used as a system benchmark, because it supplies the abstract directly and therefore exercises neither retrieval nor citation behaviour.

### Metrics

- Retrieval recall at 10 and at 30. Runs locally, costs no API requests, and is therefore the metric used during iteration.
- Ranking behaviour: whether the expected strongest study type appears in the top results.
- Citation validity: the share of cited PubMed IDs present in the retrieved set.
- Claim support: the share of statements supported by their cited abstract.
- Abstention accuracy, measured on the abstention questions.
- End-to-end latency at the 95th percentile, measured on the target laptop.

## Out of Scope for Version 1

- PMC full text.
- ClinicalTrials.gov integration, deferred to a later phase.
- Long-form exhaustive answers, deferred to a later phase.
- Any specialty other than cardiology.
- Paid models or paid hosting of any kind.
- Patient-facing use or clinical decision support claims.

## Open Decisions

| Ref | Decision | Current recommendation |
|---|---|---|
| Q9 | What verifies that claims are supported | Local entailment model first, escalating to a model call only for uncertain claims |
| Q16 | How strongly study design shifts ranking | Additive bonus tuned on the evaluation set, plus a visible badge, plus user filters |
| Q17 | When the system abstains | Threshold on reranker score, calibrated on the abstention questions |
| Q18 | How conflicting evidence is displayed | Separate supporting and opposing groups, never merged into one claim |
| Q19 | Answer layout, length and warnings | Short answer, evidence table beneath, explicit non-advice notice |
| Q20 | Retracted papers: flag, exclude, or defer | Flag in version 1 using PubMed's own retraction markers |
| Q21 | One-time corpus download versus scheduled updates | One-time download for version 1, scheduled updates deferred |
| Q22 | Storage engine | Local vector database for version 1 |
| Q23 | Interface | Minimal Python app in version 1 |
| Q24 | Where it runs | Local machine, with a recorded walkthrough as the portfolio artefact |

## Facts To Verify Before Building

1. Cardiology record counts for both download passes, and the resulting index size.
2. OpenRouter free-tier request limits, and whether they depend on a prior credit purchase.
3. The share of PubMed abstracts that exceed the encoder input limit.
4. Whether recently indexed records reliably carry publication type and MeSH data, and how long indexing lags.
5. BioASQ access terms, and how many of its questions survive the corpus filter.
6. Retraction data access through Crossref, including update cadence and licence.
7. Cross-encoder latency on Apple silicon at candidate depths of 20, 30 and 50.

## Environment Notes

- The desktop workspace shell can reach the GitHub API but is blocked from the NCBI E-utilities endpoint by the network policy. Corpus downloads therefore run either from the user's own macOS terminal or from the cloud workspace, not from the desktop workspace shell.
