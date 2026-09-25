# Biomedical Literature Assistant — Implementation Plan

## 1. Purpose

Deliver the project described in the project PRD through milestones with observable completion checks. This plan follows the reference project's separation between product requirements, a technical specification, and implementation evidence.

This document schedules future work. Application development, dependency installation, corpus ingestion, provider calls, and deployment have not been started by creating this plan.

## 2. Agreed scope and technical direction

| Area | Decision |
|---|---|
| Project priorities | AI/ML portfolio first, real-user usefulness second, learning third |
| Primary task | Focused biomedical fact and list questions |
| Evidence | Published titles and abstracts; full text is deferred |
| Benchmark | BioASQ fact and list questions |
| Question set | 100 eligible questions: 50 development and 50 held-out test questions |
| Search collection | Supporting abstracts mixed with additional papers on similar topics |
| Corpus size | Not fixed; the earlier 5,000-abstract figure was only a proposal |
| Retrieval experiments | Compare keyword search and embedding-based search separately |
| Generation | OpenRouter free models; exact model remains open |
| Embedding model | Pinecone-hosted llama-text-embed-v2 as the initial candidate |
| Vector storage | Pinecone is the planned service, subject to feasibility checks |
| Frontend | Next.js and TypeScript |
| Backend | Python and FastAPI |
| Hosting | Vercel is the planned host; separate frontend/backend projects are the proposed arrangement |
| Answer presentation | Direct answer, brief cited explanation, and inspectable source abstracts/passages |
| Weak evidence | State that retrieved abstracts do not provide sufficient support; do not fill gaps from model memory |
| Ambiguous question | Ask one clarifying question before searching |
| Conversation scope | One research question and its clarification; follow-up conversations are deferred (added on 2026-09-24, after the held-out evaluation) |
| Budget | No paid services or paid fallback |

The [technical PRD](TECHNICAL_PRD.md) defines contracts, operating rules, and implementation defaults. Defaults can be resolved through documented development work; they are not additional product decisions requiring individual approval.

## 3. Documents needed

### Before application implementation

1. **Project PRD:** existing product requirements. Reconcile its open-decision list with the subsequently agreed question types, benchmark, and answer format when finalizing the planning documents.
2. **Technical PRD:** prepared alongside this plan. Define architecture, component responsibilities, data and API contracts, request outcomes, provider integration, retrieval behavior, limits, evaluation policy, and completion criteria.
3. **Implementation plan:** this document. Defines sequencing, dependencies, deliverables, and evidence required to complete each milestone.

Keep the data-selection protocol, evaluation design, initial UI sketch, and API contracts as sections of the technical PRD. They do not need separate planning documents at this scale.

### Produced during implementation

- **README/setup guide:** reproducible setup, configuration, commands, and demonstration instructions.
- **Data manifest:** BioASQ release, question IDs/splits, abstract provenance, collection rules, exclusions, and snapshot hashes. Keep reference answers and evaluation mappings outside the searchable corpus and public runtime assets.
- **Evaluation report:** baseline comparisons, metrics, per-question results, failure analysis, latency, available usage, and known limitations. Do not publish restricted data or full source texts merely because a report is public.

An architecture decision record is useful only if a major choice changes. Separate design documents, user manuals, infrastructure specifications, and a generic agent framework are not prerequisites.

## 4. Engineering defaults and implementation checks

### Starting directions specified in the technical PRD

| Decision | Recommended starting direction | Why it matters |
|---|---|---|
| Backend responsibilities | One shared Python retrieval/answering service used by the API and evaluation runner | Ensures experiments test the pipeline deployed to users |
| Searchable unit | Title plus complete abstract when it fits; split overlong abstracts into overlapping passages with the same paper ID | Preserves study context and traceable citations; sizing is resolved during implementation |
| Keyword baseline | BM25 over the same title/abstract content as vector retrieval | Provides a meaningful, understandable comparison |
| Clarification behavior | One clarification response; if still underspecified, explain what is missing and invite a new question | Prevents accidental multi-turn chat scope |
| Answer outcomes | Answered, needs clarification, insufficient evidence, unsupported request, and service unavailable | Separates scientific limits from operational failures |
| Citation validation | Reject invented source IDs and verify quoted passages against stored text | Establishes traceability without claiming automatic proof of scientific support |
| Request state | Send the original question plus at most one clarification answer; no saved conversation history | Keeps the agreed interaction bounded |
| Evaluation protocol | Freeze split and scoring rules before tuning; hold out final test results | Prevents optimistic results from repeated test-set tuning |
| Public-demo protection | Bounded requests, evidence length, retries, and shared rate/quota enforcement | Protects free allowances without introducing user accounts |
| Runtime storage | Pinecone for evidence; reproducible local data snapshots for offline work; resolve shared quota/cache storage explicitly | Local function memory is not a cross-instance budget counter |

### Resolve through limited feasibility checks once coding is authorized

- BioASQ release access, licensing/attribution, available question types, and suitability of supplied evidence for titles/abstracts.
- Abstract retrieval source and permissions, unavailable records, metadata quality, and retraction/correction handling.
- Exact corpus size, realistic token use, storage needs, and additional-paper selection method.
- Embedding configuration, passage limits, truncation behavior, dimensions, and hosted integration compatibility.
- A specific available free OpenRouter model that follows the required answer format and provides usable outputs.
- Vercel FastAPI deployment behavior, frontend/backend connectivity, allowed origins, timeouts, and packaging of the small keyword index if it is deployed.

### Resolve on development questions before final testing

- Retrieval depth and the number of papers supplied to generation.
- Whether BM25 or vector retrieval is the primary demo mode. Keep both in evaluation; do not assume vector retrieval wins.
- Insufficient-evidence rules and their measured failure rate. A similarity score alone is not confidence that an answer is supported.
- Numerical answer-quality and latency targets. Define targets before the held-out run, not after seeing test results.

Hybrid retrieval and reranking are optional later experiments. They are not required to finish the first baseline comparison.

## 5. Proposed system boundaries

The browser displays results and collects input. The Python backend validates requests, resolves clarification, retrieves evidence, calls generation, checks output structure and citation references, and returns a typed result. Provider keys remain on the backend.

The evaluation runner invokes the same Python service or its retrieval-only operation. It can evaluate retrieval without consuming generation requests. Corpus preparation is an offline operation, not part of a visitor's request.

Retrieved text is evidence, not instructions. Generation must preserve source limitations and must not present information unsupported by the retrieved abstracts. Citation checks establish identifier and text consistency; claim-level support requires additional review.

Proposed API operations are a question-answer endpoint and a readiness endpoint. Exact payloads belong in the technical PRD. The answer endpoint must represent clarification, abstention, and service failure explicitly rather than returning every outcome as an answer string.

## 6. Milestones and completion gates

Estimates below are rough hands-on development time for one developer. They exclude account access, free-provider waiting periods, and major redesign. No calendar deadline has been agreed.

### Milestone 0 — Finish planning

**Work**

- Review the technical PRD and its distinction between agreed scope and adjustable engineering defaults.
- Include an answer-page sketch, request/response examples, evidence schema, evaluation protocol, and bounded-request policy.
- Record assumptions and feasibility gates separately from established decisions.
- Reconcile the project PRD with the agreed product scope without adding engineering detail to it.

**Completion gate:** the technical PRD is reviewable, responsibilities and outcomes are unambiguous, and remaining experimental choices have explicit methods for resolution. Application implementation requires a subsequent instruction to begin.

### Milestone 1 — Prove service compatibility

**Estimate:** 1–2 days after implementation authorization.

**Work**

- Establish dependency versions and lockfiles for Python and the web application.
- Verify dataset access and inspect candidate records without tuning on final test answers.
- Index a small non-test set with the selected embedding model, then retrieve it from a natural-language question.
- Verify a real free-model generation request and a minimal Vercel frontend-to-Python-backend flow.
- Record quotas and limitations; do not silently substitute paid services if a check fails.

**Completion gate:** real integration evidence confirms that the proposed service combination works. A blocked capability is resolved or the architecture is revised before substantial implementation.

### Milestone 2 — Prepare the benchmark and corpus

**Estimate:** 2–4 days.

**Work**

- Define eligibility rules, including question type, answer availability, and title/abstract evidence. Apply consistent rules before assigning questions to splits.
- Select 100 eligible questions. Create and freeze a reproducible 50/50 development/test split, separating duplicates or close paraphrases and recording topic/type distributions.
- Obtain supporting abstracts and add papers on related topics using a documented selection method independent of system performance. Do not tune additional-paper selection based on held-out answer quality.
- Normalize paper IDs and text, deduplicate records, retain provenance, and record missing or excluded material. Missing reference papers are data-coverage failures, not automatically retrieval failures.
- Keep answer keys and question-to-paper mappings accessible to evaluation only. Including the source abstracts is intentional; exposing their test labels to the application is not.

**Completion gate:** a versioned manifest describes the 100-question set and final collection; references resolve or exclusions are explained; measured embedding/storage estimates fit the budget. The controlled collection is explicitly distinguished from a full-PubMed benchmark.

### Milestone 3 — Build and compare retrieval

**Estimate:** 2–3 days.

**Work**

- Implement one retrieval interface returning ranked papers and source text.
- Add BM25 and Pinecone vector retrieval over the same corpus.
- Apply the versioned searchable-unit policy selected during implementation; preserve source offsets and paper IDs. Deduplicate passage results at paper level for paper-level scoring.
- Compare methods using development questions and record retrieval depth, misses, and timing.
- Freeze the selected settings before the final test run. Retain both baselines even if one performs poorly.

**Completion gate:** reproducible development results show which expected papers each method retrieved and where it failed. Neither method uses reference answers as query input. No unsupported claim of improvement is made.

### Milestone 4 — Add answer generation and outcomes

**Estimate:** 3–5 days.

**Work**

- Implement input validation and the single clarification step, preserving the original question when clarification is supplied.
- Construct a bounded evidence context and generate the agreed direct answer, brief explanation, and citations.
- Validate response structure, citation membership, and supporting excerpts. Explain insufficient support rather than filling missing evidence from model memory.
- Add timeout, quota-exhaustion, malformed-output, and provider-error handling with bounded retries and no paid fallback.
- Exercise cases with no evidence, wrong evidence, ambiguity, unsupported requests, conflicting findings, and source text containing instructions.

**Completion gate:** a real end-to-end question can produce a traceable answer; controlled failure cases produce the correct distinct outcomes. Development review records unsupported-claim failures instead of hiding them behind valid citations.

### Milestone 5 — Deliver the web workflow

**Estimate:** 2–3 days.

**Work**

- Build the question form, progress display, one-step clarification, answer view, and source panels.
- Show collection coverage and the abstract-only limitation. Keep implementation settings out of the ordinary user flow.
- Connect the frontend to the same backend evaluated offline; configure deployment origins and secrets.
- Enforce the agreed public-demo request limits and show honest service-unavailable messages.
- Test the browser flow, mobile layout, keyboard use, double submissions, errors, and source links.

**Completion gate:** a visitor can ask a question, clarify once if necessary, and inspect a final answer or explicit outcome on the deployed demonstration. No credentials or evaluation answer keys are exposed.

### Milestone 6 — Final evaluation and portfolio release

**Estimate:** 2–4 days, plus provider quota waits.

**Work**

- Freeze code, corpus, prompts, model identity, settings, and scoring rules.
- Run both retrieval methods on the 50 held-out questions. Run the agreed generation experiment with fixed settings.
- Separate normal end-to-end answering from any diagnostic experiment supplying reference evidence directly; the latter does not measure retrieval.
- Report results by question type, aggregate metrics, source availability, abstentions, provider failures, latency, and available usage. Keep additional clarification/insufficient-evidence fixtures separate from the 100 benchmark questions.
- Write the evaluation report and README, and prepare a repeatable demonstration with development examples rather than presenting memorized test examples as unseen success.

**Completion gate:** every held-out question has a result or documented failure; accepted quality targets are assessed; the report distinguishes software correctness, model quality, and clinical validation. If targets are missed, report the shortfall. Further tuning requires a new clearly identified evaluation cycle; it must not overwrite the original test result.

## 7. Evaluation and test policy

### Proposed measurement set

- **Retrieval:** paper-level Recall@5 and Recall@10; mean reciprocal rank for the first relevant paper. Measure fact and list questions separately as well as together.
- **Exact answers:** normalized exact match allowing benchmark-provided synonyms for fact questions; precision, recall, and F1 for list questions. Specify matching rules before evaluation.
- **Citations:** reference validity plus a separate documented review of whether claims follow from their cited abstracts.
- **Insufficient evidence:** assess correctly declining and incorrectly declining on a separate controlled set; ordinary answerable BioASQ questions do not establish abstention quality by themselves.
- **Operations:** response latency, failures, and request/token consumption where available. A small 50-question test cannot support broad reliability claims.

These metric choices are recommended defaults for the technical PRD, not already agreed numeric performance targets.

### Verification approach

Use the complete question-to-result service as the main behavior-testing boundary, plus retrieval-only evaluation and browser checks. Add narrow tests for consequential rules such as citation validation, quota handling, split isolation, and preventing duplicate ingestion. Do not assert exact generated wording or test only prompt strings.

Mock provider responses for repeatable software tests. Use real providers for separately labeled model-quality and integration evidence. With no biomedical expert contact, disclose the limitations of reference-answer comparison and author review. An LLM judge alone does not establish scientific correctness.

## 8. Completion checklist

- Product scope and technical contracts agree.
- Real service compatibility is demonstrated within the free budget.
- The 100-question split and mixed corpus are documented and reproducible.
- Keyword and vector retrieval are measured independently of generation.
- Answers, citations, clarification, abstention, and service-failure states work end to end.
- The deployed pipeline is the pipeline evaluated, with model/settings differences disclosed.
- Held-out results, failures, and quality-target outcomes are reported without selective omission.
- Setup instructions, demonstration, and evaluation report are available.

## 9. Reference documents

- [Project PRD](PRD.md)
- [Technical PRD](TECHNICAL_PRD.md)
- [Reference project's technical PRD and completion gates](https://github.com/mrunalmmpatil/self-maintaining-api/blob/main/TECHNICAL_PRD.md)
- [BioASQ task guidance](https://participants-area.bioasq.org/general_information/Task14b/)
- [Pinecone model guidance](https://www.pinecone.io/learn/nvidia-for-pinecone-inference/)
- [Vercel Python runtime](https://vercel.com/docs/functions/runtimes/python)

External models, quotas, and deployment capabilities must be verified during feasibility work. References are planning inputs, not evidence that this project's integrations have already been tested.
