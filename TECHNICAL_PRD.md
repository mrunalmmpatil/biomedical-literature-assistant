# Biomedical Literature Assistant — Technical PRD

## 1. Objective and scope

Implement the [project PRD](PRD.md) as a web application that answers focused biomedical questions from a controlled collection of titles and abstracts. Return a direct answer, a brief explanation with citations, and source text the user can inspect. When evidence is inadequate, explain the limitation instead of supplying an answer from model memory.

Use the [implementation plan](IMPLEMENTATION_PLAN.md) for milestone sequencing. This specification describes intended behavior and engineering starting points; it does not claim that integrations have been implemented or verified. The agreed scope below is fixed. Settings explicitly identified as defaults may be adjusted during implementation using development evidence, without another product interview. Changes to product scope, paid usage, or the held-out evaluation protocol require a separate decision.

### 1.1 Agreed decisions

| Area | Decision |
|---|---|
| Primary users | Biomedical researchers asking focused literature questions |
| Priority | AI/ML portfolio, then real-user usefulness, then learning |
| Question types | Fact and list questions; broad summaries deferred |
| Evidence | Titles and abstracts only |
| Benchmark | 100 eligible BioASQ questions: 50 development and 50 held-out tests |
| Collection | Reference abstracts plus other papers on related topics |
| Retrieval | Evaluate keyword and vector retrieval separately |
| Frontend | Next.js with TypeScript |
| Backend | Python with FastAPI |
| Initial embeddings | Pinecone-hosted llama-text-embed-v2 |
| Vector database | Pinecone, subject to free-tier feasibility |
| Generation | OpenRouter free models only |
| Hosting direction | Vercel |
| Interaction | One question, with one clarification step when needed |
| Answer | Direct answer, brief cited explanation, inspectable sources |
| Insufficient evidence | Explicit abstention rather than unsupported completion |

### 1.2 Engineering defaults

- Separate Vercel frontend and Python backend projects. Verify this arrangement in the first feasibility milestone.
- One shared Python service implements retrieval and answering for both HTTP requests and evaluation. The frontend contains no duplicate RAG logic.
- Use direct provider SDKs or HTTP clients behind small adapters. A general agent framework is unnecessary for this bounded workflow.
- Use Pydantic for validated contracts, pytest for Python behavior tests, and Playwright for browser tests. Resolve compatible dependency versions and commit lockfiles during implementation.
- Start with complete title-plus-abstract records. Split only when required by the actual embedding input limit; choose passage sizing during implementation.
- Use BM25 as the keyword baseline. Use vector retrieval initially in the application; select the final default using development results.
- No user accounts, conversation-history database, or long-running background worker in the initial application.
- Keep transient quota and duplicate-request state in a shared atomic store, separate from the evidence index. Select a free Redis-compatible service or an equivalent verified atomic mechanism during feasibility work. Never substitute process-local memory as a global counter.

## 2. Architecture and responsibilities

For a plain-language walkthrough with diagrams, see the [architecture guide](ARCHITECTURE.md).

```text
Browser: Next.js / TypeScript
              |
              v
Python FastAPI: request validation and outcome presentation
              |
              v
Shared question-answering service
   |          |             |
   |          |             +-- OpenRouter: classification / generation
   |          +-- Retrieval: BM25 or Pinecone embeddings and vector search
   +-- Shared quota / request-state adapter

Offline Python commands
   +-- BioASQ selection and reference labels (evaluation only)
   +-- PubMed abstract collection and immutable corpus snapshots
   +-- BM25 preparation and Pinecone ingestion
   +-- Evaluation through the same retrieval / answering service
```

| Component | Responsibility |
|---|---|
| Corpus preparation | Fetch, normalize, validate, deduplicate, and version titles/abstracts |
| Retrieval | Produce ranked evidence using a common interface for BM25 and vector search |
| Question assessment | Identify supported requests and material ambiguity without answering the question |
| Generation | Produce a structured answer from selected evidence |
| Validation | Enforce schemas, citation membership, source excerpts, and allowed outcomes |
| Request coordination | Timeouts, retry budgets, clarification continuity, quota admission, and error mapping |
| Evaluation | Load isolated answer keys, score frozen results, and report failures |
| Web interface | Collect questions, display progress/results, and expose evidence |

Bulk fetching, indexing, and evaluation run from the developer's machine or a suitable notebook. They do not execute as visitor-triggered indexing jobs. The runtime corpus is read-only; its credentials must not grant ingestion rights where the provider supports separation.

## 3. Corpus and benchmark preparation

### 3.1 Selection protocol

Choose a specific accessible BioASQ release during feasibility work. Record source, release date, access requirements, attribution, and applicable usage terms. Do not assume that the dataset licence also licenses redistribution of every article abstract.

Before assigning splits, filter for fact/list questions with usable reference answers, resolvable papers, and supporting title/abstract evidence. Log exclusions consistently. Do not choose questions because an early system already answers them well.

Select 100 eligible questions with a recorded random seed. Aim for both types to be represented in each 50-question split, and record the actual distribution. Group duplicates or close paraphrases before splitting. Shared source papers are allowed in this controlled collection, but disclose overlap between development and test questions.

If 100 eligible questions cannot be obtained, report the data limitation rather than silently reducing the set or inventing labels. This is a data feasibility gate, not a reason to tune on test results.

### 3.2 Mixed literature collection

Use reference-paper IDs to assemble the relevant evidence, then add related papers through documented topic searches or metadata rules. Apply the same procedure across the set before tuning. Do not use held-out answers to craft search queries, tune distractors, or change ranking.

The selected corpus intentionally contains reference evidence. It measures retrieval within a controlled collection, not discovery across all PubMed. Reference answers, benchmark question text, relevant-paper labels, and benchmark-provided snippets must not be embedded as retrieval documents. Snippets are evaluation references; searchable text comes from the independently fetched source record.

The earlier 5,000-abstract estimate is not a requirement. Measure actual token and storage use, leave capacity for development queries and retries, and freeze a feasible corpus size. Preserve a copy of the original fetched records and a normalized snapshot outside the deployed frontend.

### 3.3 Normalization and versions

Use PMID as the stable paper identifier for PubMed records. Preserve title, abstract, available publication metadata, source URL, retrieval date, source status, and a normalized-text hash. Missing fields are null, not generated. Collect retraction/correction markers when available; initially exclude records explicitly marked retracted and record this policy and its coverage limits.

Fetch politely with documented source limits, bounded retries, and resumable batches. Missing abstracts, withdrawn records, or changing source text must appear in the data report. Freeze the evaluation snapshot; do not silently refresh it during a benchmark run.

Store the complete normalized abstract even when it is indexed as passages. Each passage has its paper ID, passage ID, index within the paper, and offsets into normalized source text. Repeat the title as needed, split on sentence boundaries where practical, and avoid silent token truncation.

A collection version identifies the corpus snapshot, embedding model/configuration, searchable-unit policy, and ingestion code version. Ingestion is idempotent. Changes to text or passage layout remove obsolete records in the replacement collection; publish the replacement only after counts and sample queries pass.

## 4. Data contracts

Use versioned schemas. These are implementation targets; equivalent field names are acceptable if the semantics remain explicit.

| Record | Required information |
|---|---|
| Paper | PMID, title, abstract, source URL, nullable publication metadata, source status, retrieval date, content hash |
| Search item | Stable item ID, PMID, text, source offsets, corpus/collection version, embedding configuration |
| Evidence result | Source ID local to this response, PMID, title, excerpt with offsets, available abstract, retrieval rank and method |
| Benchmark question | Question ID, type, text, exact/ideal references, relevant PMIDs, reference snippets, split, dataset version |
| Evaluation result | Question ID, run/configuration ID, retrieved PMIDs, outcome, generated answer, citations, scores, latency, usage, failure reason |

Scores are retrieval-method-specific. Do not compare raw BM25 scores with cosine similarity or display either as medical confidence.

Keep benchmark records in evaluation-only storage. Public response objects contain no reference answers, split labels, private provider errors, or credentials.

## 5. Retrieval

Expose one retrieval operation accepting question text, corpus version, method, and bounded result depth. Return ranked paper-level evidence with provenance.

BM25 and vector retrieval search the same normalized source content. Start BM25 with a documented tokenizer that preserves biomedical identifiers as far as practical; choose normalization rules on development data. For passage-based indexing, aggregate by paper using a documented rule, initially the best passage score, before scoring paper-level retrieval.

Pinecone integration must use compatible passage/query settings for the selected embedding model. Verify available dimensions, input limits, metric, and SDK calls in a real smoke test. Do not assume that two equally sized vectors from different models are compatible.

Starting defaults: retrieve 10 unique papers and supply up to 5 to generation within a token budget. Query more passage candidates when needed to obtain unique papers, with a fixed ceiling. Adjust depth and evidence size using development questions and record the changes.

Retain retrieval-only execution for both methods. It must not call the answer-generation model. Hybrid retrieval, cross-encoder reranking, query expansion, and a second embedding model are optional later experiments, not initial completion requirements.

## 6. Question and answer workflow

### 6.1 Question assessment and clarification

Validate length and empty input before paid-or-free provider work. Use a small structured assessment call to identify whether the request is a supported fact/list question, clearly out of scope, or missing a material detail. Treat a named biomedical entity as usable unless there is evidence of ambiguity; do not require users to express every question in a clinical template.

If ambiguous, return one specific clarifying question. Include a short-lived server-signed token binding the original question, clarification prompt, request ID, and policy version. The next request supplies that token and the user's clarification answer. Verify integrity and expiry; do not trust a browser flag claiming assessment has already happened.

After one clarification, either proceed with the combined question or return an explanation that more detail is still needed and invite a new question. Do not start a second clarification loop or treat it as general conversational memory. The evaluation pipeline counts clarification as an outcome; it does not use reference answers to simulate a helpful user.

Follow-up questions (added 2026-09-24, after the held-out evaluation). An `answered` or `insufficient_evidence` response carries a signed follow-up token binding the last ten exchanges (each question as answered and the answer items shown), with a one-hour expiry and a signing key separate from clarification tokens. A follow-up request presents the token with the new question. The assessment call is replaced by a follow-up assessment (separate prompt, `FOLLOWUP_PROMPT_VERSION`) that rewrites the follow-up into a standalone question and classifies it by the same rules; retrieval, generation, and the citation check then run on the standalone question exactly as for any question, and the response returns it as `interpreted_question`. Each new token appends its exchange and drops the oldest, so no conversation is stored on the server. The single-question prompts stay those frozen for final-v1, and the evaluation runners do not enable follow-ups, so the held-out results describe single questions only; follow-up quality has not been evaluated.

### 6.2 Generation

Select a specific currently available free OpenRouter model during feasibility work. Verify structured output or reliable JSON parsing with that model. Keep the model fixed within an evaluation run and record requested/returned model IDs and provider metadata when supplied. Do not use a randomly selecting free-model router for controlled comparisons. If the selected model becomes unavailable, pause or start a separately identified run with a replacement; never silently mix models.

The evidence prompt supplies the question and source records identified as S1, S2, and so on. Require a structured response with:

- An answered or insufficient-evidence outcome.
- Exact answer entities as a list, including a single item for a fact question.
- A brief explanation divided into factual statements with source IDs.
- Supporting excerpt references for cited claims.
- Reported qualifications or missing evidence where relevant.

Do not expose private model reasoning. Source text and user input cannot override system constraints. Limit the answer to supplied evidence; preserve material populations, conditions, and uncertainty. Prompt instructions are not a guarantee of compliance.

### 6.3 Validation and abstention

Deterministically check output shape, permitted fields, source membership, claim-to-citation links, and excerpt offsets/text. The server constructs paper URLs and citation labels from stored records, not from model-generated URLs.

A response cannot be shown as answered if its citations refer to missing sources, quotations do not match, or factual answer items have no citation mapping. Never merely remove an invalid citation and leave its unsupported claim visible.

No usable retrieved evidence yields insufficient evidence without generation. A valid model response explicitly stating insufficient support also yields that outcome. Invalid provider output yields service unavailable with an internal validation reason, unless an allowed retry produces a valid response. A provider error is not a scientific abstention.

Start with evidence-conditioned generation and structural validation. Test insufficient-evidence behavior on controlled development fixtures. Do not treat a vector threshold as a universal answerability test. Add or calibrate any threshold on development data only. Automated claim verification is not established by these structural checks; review claim support separately and disclose residual errors.

### 6.4 Request outcomes

| Outcome | Meaning |
|---|---|
| answered | Structured answer passes source-reference checks; scientific support is still subject to evaluation |
| needs_clarification | One detail is requested before retrieval |
| insufficient_evidence | Available abstracts do not adequately support an answer |
| unsupported_request | Request is outside scope, or remains too vague after its clarification |
| service_unavailable | Provider, quota, timeout, or output-validation failure prevents completion |

The UI must not use an overall scientific-confidence badge merely because validation passed.

## 7. API and interface

### 7.1 API targets

| Endpoint | Behavior |
|---|---|
| GET /api/health | Non-secret readiness and corpus version; no model call |
| GET /api/coverage | Collection description, abstract-only scope, snapshot date, and development example questions |
| POST /api/answer | Accept question, optional signed clarification token/answer, and request key; return a typed outcome |

Reject empty or oversized inputs with validation errors. Use 429 for application quota exhaustion, 503 for provider unavailability, and 504 for request timeout, each with a safe response body. Do not expose upstream stack traces. Semantic outcomes such as insufficient evidence return a completed response, not a server error.

Example request:

```json
{"question": "Which proteins are associated with condition X?", "request_key": "client-generated-unique-id"}
```

Example response shape:

```text
schema_version, request_id, outcome, message
answer: {items[], explanation_claims[{text, source_ids[]}] } | null
sources[{source_id, pmid, title, url, abstract, excerpts[]}]
clarification: {question, token} | null
corpus_version
```

The question above is a structural example, not a benchmark item. Validate both requests and provider outputs. Retrieval settings and model selection are developer configuration, not ordinary public request parameters.

### 7.2 UI sketch

```text
Biomedical Literature Assistant
Collection scope and abstract-only notice

[ Research question                              ] [Ask]

[One clarification field, only when requested]

Direct answer
Brief explanation with [1] [2] citations

Sources
[1] Paper title — available year / journal
    Supporting excerpt
    Expand abstract | Open original paper
```

Show a simple pending state, prevent duplicate clicks, and preserve entered text after errors. Do not imply detailed backend progress without actual events. Non-streaming results are the starting default so validation happens before the answer is displayed. Source panels must support keyboard navigation and mobile layouts.

Browser refresh may clear the current interaction; there is no saved history. Signed clarification and follow-up tokens and request records expire rather than becoming permanent conversation storage.

## 8. Operational controls and hosting

### 8.1 Starting budgets

These are configurable engineering defaults, not measured performance claims:

| Limit | Starting value |
|---|---:|
| Initial question | 2,000 characters |
| Clarification answer | 1,000 characters |
| Clarification-token lifetime | 10 minutes |
| Unique retrieved papers | 10 |
| Papers supplied to generation | Up to 5, further bounded by tokens |
| Total OpenRouter attempts per HTTP request | 4, including assessment, generation, and retries (raised from 3 on 2026-09-24; see below) |
| Individual generation-provider request | 25 seconds |
| End-to-end backend deadline | 90 seconds, or deployment ceiling minus margin if lower |
| Public-client admission | 20 requests/hour per network address (raised from 5 on 2026-09-24, agreed by the project owner, because people sharing one network share the limit); a site-wide daily cap protects the provider allowance |

At most two retries are allowed within the total attempt and time budgets (raised from one on 2026-09-24 with the project owner's agreement, after 26% of free-model attempts failed on the provider side during development; see docs/answering-development.md). Do not retry authentication errors or daily quota exhaustion. Respect Retry-After only when it fits the remaining deadline. Clarification submission is another HTTP request and consumes budget; the signed token does not grant free calls.

Set a shared daily provider-attempt ceiling from the verified account allowance, reserving capacity for development. Count attempts before dispatch with atomic operations. Do not hardcode yesterday's published quota as the account's actual remaining allowance. Missing usage is null, not zero.

### 8.2 Request state and privacy

Use the shared quota store for atomic counters, expiring request fingerprints, in-flight leases, and short-lived completed responses. A duplicate key with different content is rejected; an in-flight duplicate does not trigger another generation. If a process dies, mark its expired lease retryable with a new admitted attempt; exact-once provider billing is not guaranteed.

Do not use Pinecone as an atomic rate limiter or rely on CORS as abuse prevention. If shared admission control is unavailable, fail closed for public generation while retaining a clear status message. The storage provider and free allowance are a feasibility gate; an uncontrolled public endpoint is not an acceptable substitute.

Keep secrets in backend environment configuration. Permit only intended frontend origins. Store only bounded diagnostic data; avoid raw prompts and full abstract dumps in routine logs. Use expiring pseudonymous client keys for limits and do not claim that IP-based limits identify individuals reliably.

### 8.3 Deployment

Deploy the Next.js frontend and FastAPI backend separately initially. Validate current Vercel runtime support, timeout settings, environment variables, cold-start behavior, origin configuration, and artifact sizes early. Do not depend on writable local function storage for durable data.

Bundle a read-only corpus/BM25 artifact if measured packaging and memory permit it. Otherwise keep BM25 evaluation offline and document which retrieval mode the public demo uses, or revise the backend artifact-loading approach within the free budget. Do not serve a different undocumented corpus.

Cache/index versions must change with the corpus, retrieval configuration, prompts, or model. Disable cross-question answer caching during quality/timing measurements or explicitly report cache effects. No scheduled corpus refresh is required for this version.

## 9. Evaluation protocol

### 9.1 Separation and reproducibility

Use the 50 development questions for settings, prompt changes, and model choice. Freeze configuration before accessing held-out outcomes. Keep evaluator labels out of API assets, model contexts, retrieval records, and frontend bundles.

Store run ID, commit, dependency versions, dataset/corpus hashes, retrieval method/settings, prompts, model metadata, timing, and available usage. Resume interrupted runs only under the same frozen configuration; separately identify changed-model or changed-corpus runs.

The same Python retrieval and answer service drives evaluation and the application. An optional run given reference evidence is a diagnostic answering experiment, never an end-to-end retrieval result.

### 9.2 Metrics

- Paper-level Recall@5 and Recall@10 for both BM25 and vector retrieval; MRR@10 with zero for no relevant paper in the first ten. Deduplicate PMIDs before scoring.
- Fact questions: normalized exact match against the accepted reference variants. List questions: entity-level precision, recall, and F1 with one-to-one matching and a normalization policy frozen on development data. Publish per-type results and counts.
- Citation-reference validity separately from claim support. Review held-out factual claims against the cited abstracts with a documented supported/unsupported/unclear rubric. Record reviewer identity/role and lack of expert validation.
- Abstention and clarification on a separate controlled fixture set with known expected behaviors. These fixtures do not enlarge the 100-question BioASQ benchmark. Report incorrect abstentions on answerable questions too.
- Latency distribution, request counts, available token usage, operational failure counts, and corpus coverage. Report attempted-question and successful-response denominators so dropping provider failures cannot improve the headline result.

A question yielding clarification or abstention without a scored answer remains a non-answer in the end-to-end benchmark. No reference answer may be supplied as its clarification. Additional relevant papers missing from BioASQ labels are a known limitation; do not silently relabel the held-out set after seeing favorable results.

### 9.3 Acceptance and quality targets

Hard software gates: no displayed unknown-source citations; matching excerpts; distinct outcomes; functioning limits; no answer-key leakage; complete accounting for all test questions; and a tested question-to-source browser flow.

Numerical quality targets are an implementation task. Record them after development baselines and before the held-out run, including retrieval coverage, answer correctness/support, incorrect abstention, and latency. Explain the practical rationale. Never invent a threshold now or retroactively lower it to label test results successful.

If quality gates are missed, report the application as an evaluated prototype with those limitations. Software completion does not establish clinical suitability or researcher benefit.

## 10. Verification strategy

Use pytest at the shared service boundary for valid answers, empty evidence, invented citations, mismatched excerpts, malformed model output, clarification expiry/tampering, remaining ambiguity, unavailable providers, budgets, retries, and duplicate requests. Use focused ingestion checks for stable IDs, replacement, and passage-to-source mapping.

Mock providers for deterministic software behavior; clearly distinguish those tests from live integration and quality evidence. Run a small live smoke suite on non-test examples before freezing the benchmark configuration.

Use Playwright for submitting questions, clarification, source inspection, invalid input, mobile/keyboard interaction, and error recovery. Validate that public responses and browser assets do not contain API secrets or reference answers. Passing a test of citation structure does not imply claim entailment.

## 11. Repository and delivery structure

```text
backend/          Python service, provider adapters, API, and tests
frontend/         Next.js interface and browser tests
scripts/          Offline data preparation, indexing, and evaluation commands
evaluation/       Evaluation definitions and permitted result artifacts
docs/             Setup, data protocol, and evaluation reports
PRD.md
TECHNICAL_PRD.md
IMPLEMENTATION_PLAN.md
```

Large corpora, raw restricted datasets, answer keys, credentials, caches, and local environments are ignored. Track manifests, configurations, dependency locks, and permissible evaluation summaries. Do not publish downloaded data without checking its terms.

Milestones and estimates remain in the implementation plan. Completion requires a reproducible setup, working deployed flow, separate retrieval and generation results, visible failures, and retained evaluation artifacts. Model fine-tuning, full-text ingestion, user accounts, hybrid retrieval, and reranking remain deferred. Follow-up questions were added after the held-out evaluation (section 6.1).

## 12. Implementation-time decisions and feasibility gates

The developer can resolve these through documented experiments without another setting-by-setting interview:

1. Pin the BioASQ release, corpus size, topic sampling rules, and handling of unavailable records.
2. Verify service access and free allowances, select the exact generation model, and pin dependencies.
3. Measure abstract lengths and choose passage splitting, embedding dimensions, and evidence budgets.
4. Test retrieval settings and abstention behavior on development data; document quality targets before held-out testing.
5. Verify Vercel deployment and shared quota storage; revise engineering defaults if measured limits require it.

Escalate only changes affecting agreed scope, cost, or evaluation integrity. A blocked integration is reported with its alternatives; it is not silently replaced with a paid service. Creating this specification does not start application implementation.

## 13. References

- [BioASQ Task 14b guidance](https://participants-area.bioasq.org/general_information/Task14b/)
- [BioASQ datasets and licensing](https://participants-area.bioasq.org/datasets/)
- [Pinecone embedding model guidance](https://www.pinecone.io/learn/nvidia-for-pinecone-inference/)
- [Pinecone limits](https://docs.pinecone.io/reference/api/database-limits/rate-limits)
- [OpenRouter limits](https://openrouter.ai/docs/api_reference/limits)
- [Vercel Python runtime](https://vercel.com/docs/functions/runtimes/python)
- [Reference technical PRD](https://github.com/mrunalmmpatil/self-maintaining-api/blob/main/TECHNICAL_PRD.md)

Verify provider capabilities when implementing; external documentation is not a substitute for a real integration check.
