# Milestone 1 — Feasibility record

Status: **gate met 2026-09-23.** Every Milestone 1 integration has `LIVE` or
`LOCAL` evidence below; the one-time checks deferred to later milestones are
listed where they apply. This file accumulates measured evidence for the
Milestone 1 gate ("real integration evidence confirms that the proposed service
combination works").

Each finding is labelled by how it was obtained. Provider documentation is a
planning input; it is not integration evidence, and the technical PRD
(section 13) is explicit about that distinction.

| Label | Meaning |
|---|---|
| `DOC` | Read from provider documentation on the date shown. Not verified against an account. |
| `LOCAL` | Reproduced on the development machine. |
| `LIVE` | Verified against a real account with a real request. |

---

## 1. Local toolchain — `LOCAL` 2026-09-18

| Tool | Version |
|---|---|
| Python (system) | 3.11.4 (Anaconda) |
| Python (project) | 3.12.10 (Homebrew, selected by `uv`) |
| Node | 26.8.2 |
| npm | 11.19.1 |
| uv | 0.8.4 |
| git | 2.54.0 |
| gh | 2.96.0 |
| Next.js | 16.3.6 (Turbopack default) |
| React | 19.2.8 |

The project pins **Python 3.12** in `backend/.python-version` to match Vercel's
default runtime. The Anaconda 3.11 interpreter is not used for the backend.

## 2. Vercel — `DOC` 2026-09-18

Source: [Python runtime](https://vercel.com/docs/functions/runtimes/python),
[Functions limits](https://vercel.com/docs/functions/limitations).

| Property | Value | Consequence for this project |
|---|---|---|
| Python versions | 3.12 (default), 3.13, 3.14 | Pinned to 3.12 |
| FastAPI | First-class preset; ASGI detected automatically | No adapter/shim needed |
| Entrypoint | `app.py` / `main.py` with a top-level `app`, or `tool.vercel.entrypoint` | Set to `app:app` in `pyproject.toml` |
| Dependencies | `pyproject.toml` + `uv.lock` supported with zero config | Our lockfile deploys as-is |
| Max duration (Hobby) | **300s** default and maximum, with fluid compute | The 90s backend deadline fits comfortably |
| Memory (Hobby) | 2 GB / 1 vCPU | Ample |
| Bundle size (Python) | **500 MB** uncompressed | A bundled BM25 artifact is realistic |
| Request/response body | 4.5 MB | Ample for abstracts |

**This is better than the planning documents assumed.** The technical PRD
(section 8.1) hedges the 90s end-to-end deadline against a possible lower
deployment ceiling; on Hobby the ceiling is 300s, so no hedge is needed.

**Open option:** Vercel [Services](https://vercel.com/docs/services) can run the
Python backend and the frontend in **one** project on a shared domain. The plan
proposes two separate projects. One project would remove the cross-origin
configuration described in technical PRD section 8.2. Worth a real comparison
before Milestone 5; not yet decided.

### 2a. Vercel — `LIVE` 2026-09-23

Two Hobby projects, deployed from the CLI (no Git connection yet).

| Project | Production URL | Root |
|---|---|---|
| `bla-backend` | https://bla-backend.vercel.app | `backend/` |
| `bla-frontend` | https://bla-frontend-gilt.vercel.app | `frontend/` |

| Check | Result |
|---|---|
| Backend build | Python 3.12 from `.python-version`, uv installs from `uv.lock`; 5s |
| `GET /api/health` | HTTP 200, ~0.3–0.4s; both providers report configured from Vercel env vars |
| Frontend build | Next.js 16.3.6; `/` static; backend URL baked in at build time |
| CORS | Frontend origin and `localhost:3000` allowed, including on preflight; other origins get no allow header |
| Deployed frontend in headless Chrome | **Reachable**, correct values rendered |

Findings:

- **A CLI-created project has no framework preset**, and the first deploy
  built nothing (404). Both `vercel.json` files now set `framework`.
- **Hobby blocks deploys whose commit author is not the account owner**
  (`TEAM_ACCESS_REQUIRED`), even for CLI deploys from a git working tree. The
  repository's local `user.email` is set to the Vercel account's email.
- `*.vercel.app` names are global: `bla-frontend.vercel.app` belongs to an
  unrelated site, so the frontend is served at `bla-frontend-gilt`.
- Deployment Protection is on for everything except production domains, so
  per-deployment and preview URLs redirect to a Vercel login. That matters if
  Git-connected previews are added later.
- `NEXT_PUBLIC_API_BASE_URL` is fixed at build time: changing the backend URL
  requires a frontend redeploy. `ALLOWED_ORIGINS` must list the frontend URL.
- Deferred: cold-start behaviour under real traffic, and bundle size once a
  BM25 artifact ships (Milestone 3).

## 3. Pinecone — `DOC` 2026-09-18

Sources: [llama-text-embed-v2](https://docs.pinecone.io/models/llama-text-embed-v2),
[pricing](https://www.pinecone.io/pricing/).

| Starter (free) allowance | Value |
|---|---|
| Indexes | Up to 5 |
| Storage | Up to 2 GB |
| Write units | Up to 2M/month |
| Read units | Up to 1M/month |
| Egress | Up to 1 GB/month |
| `llama-text-embed-v2` tokens | **5M/month included** |
| `bge-reranker` | 500 requests/month included |

`llama-text-embed-v2`: dimensions **384 / 512 / 768 / 1024 / 2048**, metric
**cosine or dot product**, **max 2048 input tokens**.

Two consequences:

1. **Passage splitting is probably unnecessary.** A title plus a typical PubMed
   abstract runs a few hundred tokens, well inside the 2048-token input limit.
   The technical PRD (sections 3.3, 12.3) leaves passage sizing open; the
   evidence so far favours keeping "title + complete abstract" as one searchable
   unit and splitting only the rare overlong record. Confirm against measured
   abstract lengths in Milestone 2.
2. **The binding free-tier constraint is monthly embedding tokens, not
   storage.** At roughly 375 tokens per record, a 5,000-abstract corpus costs
   about 1.9M tokens per full ingest — so roughly two full re-index cycles per
   month. Storage for the same corpus is about 20 MB against a 2 GB cap.
   Corpus size should be chosen against the token allowance and the expected
   number of re-index cycles, not against storage.

A reranker is also available free (500 req/month), which makes the "optional
later experiment" in technical PRD section 5 cheaper than assumed.

### 3a. Pinecone — `LIVE` 2026-09-23

Starter account, SDK `pinecone` 10.0.0, AWS us-east-1.

| Check | Result |
|---|---|
| Create index with integrated `llama-text-embed-v2`, 1024 dims, cosine | Ready |
| Upsert 4 probe records | 4 vectors counted |
| Query "What drug blocks xanthine oxidase?" | Expected record ranked first (0.520; next 0.099). **PASS** |
| `PineconeRetriever` + `upsert_papers` on the smoke corpus (2 papers) | Upserted 2, refused 0; Wuhan-pneumonia question ranked PMID 31978945 first (0.429; next −0.024) |
| Probe indexes deleted afterwards | Yes |

Findings:

- **SDK 10 changed the response shapes.** `describe_index` reports dimension
  and metric per schema field, and search hits are `Hit` objects: `hit["_score"]`
  raises `KeyError`. The probe and `bla/retrieval/vector.py` were fixed, the
  unit tests now build real `Hit` objects, and `pyproject.toml` pins
  `pinecone>=10,<11`.
- **The index truncates overlong input silently** (`truncate: END` on both
  read and write). The existing `MAX_EMBED_CHARS` refusal in `vector.py` is
  what prevents silent truncation; it must stay.
- The smoke corpus contains PMID 20301295, "GeneReviews®", a book record rather
  than an article. Milestone 2 eligibility rules should decide whether such
  records belong in the collection.

## 4. OpenRouter — `DOC` 2026-09-18 — **constraint**

Source: [API limits](https://openrouter.ai/docs/api-reference/limits).

| Account state | Requests/min | Requests/day (free models) |
|---|---:|---:|
| No credits ever purchased | 20 | **50** |
| $10+ purchased, all-time | 20 | 1,000 |

The daily tier is set by all-time credits purchased. A single $10 purchase
raises the ceiling permanently.

### What 50 requests/day means here

The workflow spends two provider calls per question: one structured assessment
call (technical PRD 6.1) and one generation call (6.2), with a third permitted
for a retry (8.1).

| Activity | Calls | At 50/day | At 1,000/day |
|---|---:|---|---|
| One 50-question development pass | 100 | 2 days | 10% of one day |
| One 50-question held-out run | 100 | 2 days | 10% of one day |
| Ten development iterations | 1,000 | ~20 days | 1 day |
| One demo visitor at the 5 req/hour cap | 10–15/hour | Exhausts the day in 3–5 hours | Negligible |

At 50/day a single evaluation pass takes two days and blocks the public demo
for both of them. The development loop the plan depends on is not workable at
that allowance.

**This does not block Milestones 1–3.** Retrieval-only evaluation must not call
the generation model (technical PRD section 5), so corpus preparation and the
BM25-versus-vector comparison are unaffected. The decision is needed **before
Milestone 4**.

Options, for the record:

| Option | Keeps $0? | Effect |
|---|---|---|
| A. Purchase $10 of credits once | No — one-time $10 | Permanent 1,000/day. Smallest change; the workflow proceeds as specified. |
| B. Add a second free provider behind the existing adapter | Yes | Changes the agreed "OpenRouter free models only" decision. Needs its own feasibility check. |
| C. Drop the separate assessment call | Yes | Halves per-question cost to 1 call. Helps, but 50/day is still too tight alone. |
| D. Local model for development iteration only | Yes | Muddies "the deployed pipeline is the pipeline evaluated". Not recommended for evaluation runs. |

This is a cost/scope question, which technical PRD section 12 reserves for the
project owner rather than implementation-time resolution.

**Decided 2026-09-23 by the project owner: stay on the OpenRouter free tier.**
Option A is rejected; the project remains $0 and OpenRouter-only. The working
assumption is therefore 50 requests/day until `check_openrouter.py` reports the
account's actual allowance.

Consequences to resolve before Milestone 4 (proposed, not yet agreed):

- Evaluation runs are spread across days, and model responses are cached by
  (question, evidence, model, prompt version) so a re-scored run spends nothing.
- Development iteration uses small fixed subsets of the development split
  rather than full 50-question passes.
- The public demo's daily ceiling is small and shares the same 50; it fails
  closed (technical PRD 8.2) when exhausted, and evaluation days may pause it.
- Option C (one combined call) was declined on 2026-09-23. The two-call
  workflow in technical PRD 6.1–6.2 stands unchanged.

### 4a. OpenRouter — `LIVE` 2026-09-23

No credits purchased. Two requests spent.

| Check | Result |
|---|---|
| Key endpoint | usage 0, no credit limit. **The daily allowance is not reported**, so the 50/day figure is still `DOC`, not measured. The deprecated `rate_limit` field says nothing usable. |
| Free models listed | 24, of which 11 advertise `response_format` |
| `google/gemma-4-31b-it:free` | **HTTP 429 from the upstream provider's shared pool** ("temporarily rate-limited upstream"). This is not the account's own quota. |
| `nvidia/nemotron-3-super-120b-a12b:free` | HTTP 200; strict JSON schema honoured; returned model equals requested model; provider Nvidia; cost 0; 47 of 106 completion tokens were reasoning |

Findings:

- **Candidate model: `nvidia/nemotron-3-super-120b-a12b:free`.** It is the only
  model verified so far. Pin it only after it has handled a realistic evidence
  prompt, not just the four-line probe.
- Rejected from the listing: the `google/lyria-*` models (music generation),
  `stealth/*` and `*-preview` models (may be withdrawn at any time), and
  `openrouter/free` (a random router, forbidden by technical PRD 6.2).
- **Free models have a second failure mode besides the daily quota:** a shared
  upstream pool can return 429 regardless of the account's own remaining
  allowance. Under technical PRD 6.4 this maps to `service_unavailable`, and
  under 8.1 it is transient, so one retry is allowed. The daily attempt counter
  cannot rely on the key endpoint; it must count attempts itself, as 8.1
  already requires.
- The reasoning tokens in the response are private model reasoning; technical
  PRD 6.2 forbids exposing them.

## 5. BioASQ — `DOC` 2026-09-18

Source: [Task 14b guidance](https://participants-area.bioasq.org/general_information/Task14b/).

- Task B phase A is document/snippet retrieval; phase B is exact and ideal
  answers. This project's shape matches both phases over a controlled corpus.
- Question types: **yes/no, factoid, list, summary**. In scope here: factoid and
  list.
- Development dataset: gold articles, snippets, exact answers, and ideal
  answers, in JSON. (5,389 questions was the 13b count; 14b is measured below.)
- **Registration and login are mandatory** — "only registered users can download
  the development dataset". NLM terms apply, licence code 8283NLM123.
- Snippets carry section and offset fields, which matches the benchmark-question
  contract in technical PRD section 4.

**Terminology:** BioASQ says *factoid*; the planning documents say *fact*. Same
question type. The data manifest should state the mapping once so the
correspondence to the dataset is unambiguous.

### 5b. BioASQ — `LOCAL` 2026-09-23

Registered, and downloaded `BioASQ-training14b.zip` to `data/bioasq/`
(git-ignored under the NLM terms).

| File | SHA-256 |
|---|---|
| `BioASQ-training14b.zip` | `5a774c04915f95de0f0a3b22af44b0044bfc9b9a439e0953094fd01c465586b5` |
| `training14b.json` | `5669afbc0bbc8f50d54850edb4aa592ecff3e38b29b09ac6684bb52990b651b7` |

Training 14b is **cumulative**: it holds every earlier edition's questions,
including past test batches, so the "golden enriched" test files were
deliberately not downloaded. They would only add duplicates that could leak
across the development/test split. The bundled README notes a 2026-02-26
update to ideal answers for six questions; record the checksum above in the
Milestone 2 manifest.

`check_bioasq.py` output:

| Type | Questions |
|---|---:|
| factoid (in scope) | 1,695 |
| yesno | 1,541 |
| summary | 1,363 |
| list (in scope) | 1,130 |
| **Total** | **5,729** |

- **Structurally eligible factoid/list questions: 2,825 of 2,825.** Every one
  has an exact answer, gold documents, and snippets with offsets. The
  requirement is at least 100. **PASS**
- Snippet sections (structure only; no answers inspected): of the 2,825,
  **2,678 cite only titles and abstracts**. The other 147 cite full-text
  (`sections.0`) snippets, which this project cannot show as evidence.
  Milestone 2 eligibility should exclude them or state how they are handled.
- Mean 11.3 gold documents per question, so a 100-question set needs about
  1,134 gold abstracts before related-topic papers. At ~375 tokens each that
  is about 0.4M embedding tokens, well inside Pinecone's 5M/month.

## 5a. Local frontend to backend round trip — `LOCAL` 2026-09-23

Milestone 1 work item: "a minimal Vercel frontend-to-Python-backend flow". The
local half is verified; the deployed half still needs a Vercel account.

| Check | Result |
|---|---|
| `uv lock` resolves | 37 packages, Python 3.12.10 (re-run 2026-09-23) |
| `pytest` | 84 passed (re-run 2026-09-23) |
| `ruff check` / `ruff format --check` | clean |
| `eslint` / `tsc --noEmit` / `next build` | clean; `/` prerendered static |
| `GET /api/health` direct | HTTP 200; both providers report configured |
| CORS from `http://localhost:3000` | `access-control-allow-origin` returned, including on preflight |
| CORS from another origin | no allow header |
| Production build (`next start`) in headless Chrome | **Reachable**, correct values rendered |
| Light and dark themes | Both legible |

The frontend page is deliberately a status check, not the product UI. The
question-and-answer interface belongs to Milestone 5, and nothing on this page
anticipates the response contract in technical PRD section 7.1.

### Two defects found by running it

1. **Empty environment variables read as configured.** `.env` templates ship
   with `PINECONE_API_KEY=`, and an empty string is not `None`, so
   `/api/health` reported both providers as configured when neither key was
   set. Fixed in `backend/bla/config.py` with a validator that maps blank to
   `None`, plus three regression tests. This is the same discipline technical
   PRD section 8.1 requires of usage figures: absent is null, never a falsy
   value that later code reads as present.
2. **Dark mode was unreadable.** `create-next-app` ships a
   `prefers-color-scheme: dark` background while the page styles were
   hard-coded light. The palette is now defined as tokens in `globals.css` with
   a full dark redefinition, and `page.module.css` carries no literal colours.

Port note: `localhost:8000` was already occupied by an unrelated local process,
so the backend runs on **8010** in development. Nothing depends on the number;
`NEXT_PUBLIC_API_BASE_URL` carries it.

## 5b. PubMed abstract collection — `LIVE` 2026-09-23

Technical PRD 3.3 requires polite, resumable fetching with every requested
record accounted for. `scripts/corpus/fetch_pubmed.py` was run against NCBI
E-utilities (no API key, 3 req/s) on four hand-picked non-benchmark PMIDs plus
one duplicate.

| Input | Result |
|---|---|
| 9500320 (retracted 2010) | Excluded `retracted` — record carries both a `Retracted Publication` type and a `RetractionIn` link |
| 31978945 | Parsed: title, abstract, journal, year |
| 20301295 (GeneReviews) | Parsed as a `PubmedBookArticle`; abstract contains inline `<i>` markup, kept as text |
| 99999999999 | Excluded `not_returned` — NCBI **silently omits** unknown IDs, no error |
| Duplicate 31978945 | Collapsed before fetching |
| Re-run | Served from the saved raw XML; no network request |

Observed structure the parser now depends on:

- Nested `PMID` elements appear inside `CommentsCorrections`; the record's own
  ID is read from `MedlineCitation/PMID` only.
- NCBI can reply HTTP 200 with an `<eFetchResult><ERROR>` body, which the
  parser raises on instead of reading as zero papers.
- Book records use a different container (`BookDocument`) and have no journal.
  The GeneReviews landing record's title is just "GeneReviews®" — correct
  parsing, but corpus selection in Milestone 2 should probably exclude such
  book-level entries.

Two samples are not a length distribution; searchable text ran 849–1,774
characters. The measured distribution belongs to Milestone 2.

## 6. Shared quota store — not yet investigated

Technical PRD section 8.2 requires an atomic, cross-instance store for quota
counters, request fingerprints, and in-flight leases, and forbids
process-local memory as a substitute. No provider selected yet. Needed before
Milestone 5, not before Milestone 4.

---

## Outstanding for the Milestone 1 gate

| Check | Blocked on |
|---|---|
| BioASQ dataset access and eligibility counts | BioASQ registration |
| Pinecone index + embed + query round trip | Pinecone account |
| Free-model structured output, measured allowance | OpenRouter account |
| Vercel deploy and cold start | Vercel account |
| Local frontend → backend call | done — section 5a |
| PubMed abstract fetch | done — section 5b |
| Shared quota store selection | Provider survey (not started) |
| Generation budget decision | **Project owner** — see section 4 |
