# Biomedical Literature Assistant — Project PRD

Status: Draft synthesized from the project discussion on 2026-09-16. This is the project brief, not the technical implementation specification. Proposed product defaults and open decisions below are not claims of user confirmation. The main testing boundary awaits confirmation. Issue-tracker publication awaits a destination.

## Problem Statement

A biomedical researcher investigating a question must locate relevant publications, read their abstracts, and assemble an answer whose supporting evidence can be checked. Relevant findings may be distributed across papers with different terminology, study populations, methods, and outcomes. A fluent summary is not sufficient if it misses relevant studies, overstates findings, or cites a paper that does not support the associated claim.

The proposed user needs a faster starting point for understanding published evidence: a focused answer, the papers behind it, and a clear explanation when the available abstracts cannot support an answer. The assistant's usefulness to actual researchers remains a hypothesis to validate; no researcher interviews or expert evaluations have been completed.

The project author's priorities, in order, are demonstrating AI/ML engineering capability to hiring managers, helping real users, and learning. The project must therefore produce inspectable evaluation evidence and honest limitations alongside an accessible demonstration.

## Solution

Provide a biomedical literature assistant that accepts a research question, retrieves relevant abstracts from a defined collection, and produces an answer with verifiable citations. Users can inspect the source abstracts and supporting text to assess the answer themselves.

Begin with a benchmark-led scope: select an existing biomedical evaluation resource, check that its questions and evidence support the intended task, and use it to establish the initial corpus and question coverage. No specialty is selected yet. Narrow the product scope as evidence about quality and usefulness becomes available.

Evaluate retrieval independently from answer generation so that improvements and failures can be attributed to the appropriate part of the system. A working demonstration alone is not evidence of retrieval quality or scientific correctness.

Proposed initial experience: a focused question-and-answer page with a concise answer, linked citations, an inspectable evidence list, and clear insufficient-evidence or service-unavailable states. The exact answer layout and length remain open. This is a research aid using abstracts, not a substitute for reading full papers or professional judgment.

## User Stories

The stories below describe proposed MVP requirements derived from the agreed direction. They do not establish that every detail has been independently confirmed.

1. As a biomedical researcher, I want to ask a research question in plain language, so that I can explore evidence without constructing a database query.
2. As a biomedical researcher, I want to understand the assistant's topic and corpus coverage, so that I know whether my question falls within its scope.
3. As a biomedical researcher, I want relevant abstracts retrieved for my question, so that I can begin with potentially useful evidence.
4. As a biomedical researcher, I want retrieval to handle differences in terminology where possible, so that relevant studies are not overlooked simply because they use different wording.
5. As a biomedical researcher, I want named interventions and study details preserved, so that an answer does not confuse related but distinct concepts.
6. As a biomedical researcher, I want a focused answer to my question, so that I can identify the main findings efficiently.
7. As a biomedical researcher, I want factual claims linked to their supporting papers, so that I can verify the evidence.
8. As a biomedical researcher, I want to inspect the source text associated with a citation, so that I can judge whether it supports the claim.
9. As a biomedical researcher, I want paper titles, identifiers, and available bibliographic details, so that I can locate the original publications.
10. As a biomedical researcher, I want to read the retrieved abstracts, so that I can assess evidence beyond the generated summary.
11. As a biomedical researcher, I want to know that the answer uses abstracts rather than full text, so that I understand its limits.
12. As a biomedical researcher, I want study populations and outcomes retained when relevant and available, so that findings are not presented without their context.
13. As a biomedical researcher, I want uncertainty and limitations in the retrieved abstracts reflected in the answer, so that tentative findings are not overstated.
14. As a biomedical researcher, I want disagreements in the available evidence acknowledged, so that conflicting findings are not merged into an unsupported conclusion.
15. As a biomedical researcher, I want the assistant to state when evidence is insufficient, so that I am not given a confident answer without support.
16. As a biomedical researcher, I want missing information identified as unavailable, so that absent details are not invented.
17. As a biomedical researcher, I want absence of evidence in this collection distinguished from absence of evidence in all literature, so that I do not mistake limited coverage for a universal conclusion.
18. As a biomedical researcher, I want service failures distinguished from insufficient evidence, so that I know whether to retry or investigate other sources.
19. As a demo user, I want visible progress while a question is processed, so that I understand that the request is underway.
20. As a demo user, I want a clear explanation when a free-service allowance is exhausted, so that a temporary limitation is understandable.
21. As a demo user, I want example questions matched to the supported scope, so that I can understand how to try the assistant.
22. As the project author, I want a benchmark with traceable reference questions and papers, so that quality can be measured against an external reference.
23. As the project author, I want retrieval evaluated independently, so that I can determine whether failures begin with missing evidence.
24. As the project author, I want generated answers evaluated separately, so that finding relevant papers is not mistaken for producing supported conclusions.
25. As the project author, I want comparable retrieval baselines, so that the value of vector retrieval and any later additions is measurable.
26. As the project author, I want evaluation questions reserved from development, so that reported results are not merely the result of tuning on the test set.
27. As the project author, I want corpus, model, and experiment settings recorded, so that results can be interpreted and rerun where external services permit.
28. As the project author, I want failures categorized with concrete examples, so that future improvements address observed weaknesses.
29. As the project author, I want free usage limits respected without paid fallback, so that the project stays within its zero-paid-usage constraint.
30. As an AI/ML hiring reviewer, I want to inspect the methodology, baselines, results, and limitations, so that I can assess engineering decisions beyond the interface.
31. As an AI/ML hiring reviewer, I want a shareable demonstration with supporting documentation, so that I can understand the project's behavior and evidence of quality.
32. As the project author, I want later researcher feedback to assess usefulness separately from benchmark performance, so that technical scores are not presented as proof of user value.

## Implementation Decisions

### Confirmed direction

- Build a retrieval-augmented biomedical literature question-answering project with a vector database.
- Prioritize AI/ML portfolio value, followed by real-user usefulness and learning.
- Use abstracts as the initial evidence source. Answers must remain within what those abstracts support.
- Start benchmark-led rather than choosing a specialty first. Select the initial coverage after examining usable evaluation data.
- Evaluate retrieval separately from generated answers.
- Use free services only. OpenRouter free models are the selected direction for generation; no exact model has been selected.
- Investigate hosted embeddings first, including Pinecone integrated embeddings, subject to allowance and quality checks.
- Produce a project PRD before a separate technical PRD. This document does not authorize application implementation.

### Proposed architecture and responsibilities

- Vercel is the proposed host for the web interface and request coordination. Pinecone is the proposed hosted vector database and embedding option. These choices remain subject to compatibility, evaluation, and free-tier feasibility.
- Separate corpus preparation, retrieval, answer generation, evidence presentation, and evaluation responsibilities without requiring separate deployed services.
- Perform bulk corpus preparation and evaluation independently of interactive user requests; the eventual execution environment remains open.
- Use one question-answering interface as the main behavioral boundary. A request supplies a question; the result exposes an answer or explicit outcome, retrieved evidence, and citation mappings. Exact schemas and API contracts belong in the technical PRD.
- Preserve stable paper identities and evidence provenance. Do not invent bibliographic fields or source locations.
- Use compatible document and query embedding configurations. Changing the embedding approach must not silently mix incompatible vectors.
- Keep provider credentials on the server. Public source abstracts are the intended input; patient records are not part of this project.
- A provider failure or exhausted allowance must be reported as an operational problem, not as a scientific finding or evidence insufficiency.
- Keep generation models fixed within comparison runs and record their identity. Free-provider availability can change and must not be described as guaranteed.
- Define citation existence checks and scientific claim-support checks separately. A valid paper identifier does not prove that its abstract supports a statement.
- Keep exact models, retrieval stages, prompts, ranking rules, data schemas, operational limits, and deployment details in the later technical specification.

## Testing Decisions

### Prior art and proposed primary boundary

The current workspace contains no application code, domain glossary, architecture decision records, or reusable tests. An earlier implementation was removed at the user's request; it is not a baseline for this project. The separate API-maintenance project is a document-structure reference only.

Propose one main integration boundary: submit a question against a fixed test corpus and inspect the returned answer, retrieved paper identifiers, citations, and outcome. Exercise retrieval and generation through this boundary. Use the retrieved evidence portion to evaluate retrieval independently; evaluation must not require running the generation model for every retrieval experiment. This boundary awaits user confirmation as required by the PRD workflow.

### Behavior to verify

- Relevant reference papers are retrieved for supported questions, with rankings evaluated against the chosen benchmark.
- Displayed citations resolve to the actual retrieved evidence and its correct publication identity.
- Unsupported questions and insufficient source material produce an explicit outcome rather than invented findings.
- Known source limitations, missing metadata, and contradictory evidence are handled transparently in appropriate fixtures.
- Invalid input, provider failures, and exhausted allowances produce distinct, understandable outcomes.
- The browser flow supports question submission, result display, source inspection, and failure states.

Test externally visible behavior rather than exact prompts, helper-function calls, vector values, or one prescribed answer wording. Add narrow tests only where the integrated boundary cannot adequately cover a material risk. Deterministic tests may use controlled model responses; label them as software-behavior tests rather than evidence of live-model quality.

### Evaluation design

- Select a benchmark only after checking access terms, reference evidence, question types, and suitability for abstract-only question answering.
- Distinguish candidate metrics from accepted targets. Retrieval recall at a chosen depth and a ranking metric are candidates; answer correctness, citation validity, claim support, and appropriate abstention are separate candidates. Exact metrics and thresholds remain open.
- Compare a keyword retrieval baseline with vector retrieval on the same corpus and question split. Additional retrieval stages are optional experiments, not confirmed MVP commitments.
- Freeze a held-out test set before tuning. Do not use test answers to create queries, adjust prompts, or choose retrieval settings.
- Build a documented corpus with meaningful non-relevant candidate papers rather than indexing only the gold papers for test questions. Disclose corpus size, construction rules, missing references, and coverage limitations.
- Record benchmark version, corpus snapshot, models, settings, experiment variants, failures, and available usage information.
- Examine benchmark contamination and incomplete reference labels as limitations. A public benchmark may have appeared in model training data.
- Without an expert contact, use reference answers and documented review procedures while acknowledging uncertainty in scientific interpretation. An automated judge is an evaluation aid, not clinical validation.
- Report small-corpus and benchmark results within their tested scope. Do not claim performance over all PubMed or usefulness to real researchers without corresponding evidence.

## Out of Scope

- Hospital-record analytics, SQL assistance for clinical datasets, RPA, and operational hospital reporting.
- Patient-specific advice, diagnosis, treatment recommendations, or validated clinical decision support.
- Full-text PDF ingestion, OCR, figure interpretation, and table extraction in the initial version.
- An exhaustive or publication-ready systematic review, meta-analysis, or automated evidence-grading service.
- Guaranteed coverage of all biomedical publications, all specialties, or the latest research.
- A specialist cardiology corpus merely because an earlier deleted brief used that scope.
- Model fine-tuning or training a new foundation model.
- Paid APIs, paid hosting, automatic paid fallback, or bypassing service quotas.
- Autonomous external actions beyond the explicitly authorized documentation publication workflow.
- Detailed engineering contracts or application implementation as part of this project PRD.

Accounts, collaboration, uploads, saved conversations, export formats, scheduled literature updates, and dedicated feedback features are deferred unless later product discussion establishes a need.

## Further Notes

### Suggested milestones

1. Confirm the project brief and primary testing boundary.
2. Assess benchmark suitability and corpus feasibility; document the selected task, coverage, access terms, and limitations.
3. Prepare the technical PRD, resolving implementation choices and acceptance thresholds.
4. Establish measured retrieval baselines on a fixed corpus.
5. Add grounded generation and evaluate it separately from retrieval.
6. Deliver the shareable web demonstration with evidence inspection and clear failure states.
7. Publish a reproducible evaluation report, failure analysis, setup guide, and demonstration; seek researcher feedback when available.

These are a proposed sequence, not authorization to start implementation or a committed schedule.

### Proposed acceptance criteria

- A user can submit an in-scope question and receive an answer with inspectable citations, or a clear insufficient-evidence or operational outcome.
- Displayed evidence can be traced to the stored abstract and publication identifier; the abstract-only scope is visible.
- A benchmark, corpus construction method, and development/test split are documented.
- Retrieval and answer-generation results are reported separately, with baseline comparisons and representative failures.
- Live provider tests are distinguished from mocked software tests; unavailable evaluation results are not fabricated.
- The selected architecture fits verified free allowances for the declared demonstration workload and provides understandable exhaustion behavior.
- A shareable demonstration and documentation explain both capabilities and limitations.
- Numerical performance gates are agreed after benchmark assessment and before final evaluation. Until then, these criteria establish deliverables, not a claim of acceptable scientific quality.

### Open decisions

- Benchmark, question types, corpus source and size, specialty coverage, and coverage dates.
- Final answer format, length, evidence presentation, and handling of user questions outside scope.
- Generation and embedding models; whether Pinecone integrated embeddings meet retrieval needs and quota constraints.
- Final deployment arrangement, execution environment for bulk work, and query-time embedding path.
- Evaluation metrics, success thresholds, citation-support review, and abstention policy.
- Timeline, researcher feedback method, and issue-tracker publication destination.

### Feasibility notes from the discussion

As checked on 2026-09-16, Pinecone publishes a free Starter plan with 5 million embedding tokens per month per model and 2 GB of database storage. A hypothetical 5,000 abstracts at 500 tokens each plus 1,000 questions at 50 tokens each uses 2.55 million embedding tokens. This is an illustration, not a selected corpus or verified end-to-end capacity estimate. Re-embedding, storage, database units, and provider request limits must be assessed separately.

Vercel's Hobby plan is intended for personal, non-commercial usage. A portfolio demonstration must stay within the applicable service terms and quotas. OpenRouter free-model availability and allowances must be rechecked before experiments.

### References

- [Pinecone pricing](https://www.pinecone.io/pricing/)
- [Pinecone rate and embedding limits](https://docs.pinecone.io/reference/api/database-limits/rate-limits)
- [Vercel pricing](https://vercel.com/pricing)
- [OpenRouter limits](https://openrouter.ai/docs/api_reference/limits)
- [Reference project brief](https://github.com/mrunalmmpatil/self-maintaining-api/blob/main/PRD.md)
- [Reference technical PRD](https://github.com/mrunalmmpatil/self-maintaining-api/blob/main/TECHNICAL_PRD.md)

### Publication status

A local project PRD draft has been prepared. No Git remote or issue-tracker destination is configured in the current workspace. The referenced setup-matt-pocock-skills workflow was not found in the available local skill roots. The API-maintenance repository was supplied as an example, not as this project's publication destination. Publish to the selected project issue tracker with the ready-for-agent label after the testing boundary is confirmed and the destination is identified. That label is a documentation triage requirement and does not override the user's instruction to defer application implementation.
