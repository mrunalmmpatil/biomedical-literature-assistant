# Biomedical Literature Assistant

Answers focused biomedical questions from a controlled collection of published
titles and abstracts, with citations and inspectable source text.

**Status: Milestone 3 complete; Milestone 4 (answer generation) next.**

- Milestone 1: every service was verified against a real account, and both
  apps are deployed ([feasibility report](docs/feasibility-report.md)):
  https://bla-frontend-gilt.vercel.app → https://bla-backend.vercel.app/api/health
- Milestone 2: 100 BioASQ questions (25 fact + 25 list per split) and a
  frozen 3,653-paper collection ([data protocol](docs/data-protocol.md)).
- Milestone 3: BM25 and Pinecone vector retrieval over the same units; on
  the development split they are statistically indistinguishable (Recall@10
  0.64 vs 0.65) ([retrieval report](docs/retrieval-development.md)).

Answer generation and the question-and-answer interface do not exist yet.

## Documents

| Document | What it covers |
|---|---|
| [`PRD.md`](PRD.md) | Product requirements, user stories, scope |
| [`TECHNICAL_PRD.md`](TECHNICAL_PRD.md) | Architecture, contracts, limits, evaluation protocol |
| [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) | Milestones and completion gates |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Plain-language walkthrough with diagrams |
| [`docs/feasibility-report.md`](docs/feasibility-report.md) | Measured provider limits and integration evidence |
| [`docs/data-protocol.md`](docs/data-protocol.md) | Benchmark selection, split, collection, and budget |
| [`docs/retrieval-development.md`](docs/retrieval-development.md) | BM25 vs vector retrieval on the development split |

## Layout

```text
backend/              FastAPI service (Vercel entrypoint: app.py)
frontend/             Next.js interface
scripts/feasibility/  Milestone 1 provider probes
scripts/benchmark/    Milestone 2 benchmark and collection builder
scripts/corpus/       Ad-hoc PubMed snapshot fetcher
scripts/indexing/     Pinecone collection loader (resumable, rate-paced)
scripts/evaluation/   Retrieval evaluation and paired analysis (development only)
evaluation/manifests/ Tracked benchmark and index manifests (IDs and hashes; no answers)
evaluation/configs/   Frozen configurations
evaluation/results/   Tracked aggregate results; per-question runs stay in evaluation/runs/
docs/                 Setup, data protocol, evaluation reports
```

## Running locally

Requires Python 3.12 (via `uv`) and Node 20.9+.

```bash
# Backend — http://localhost:8010
cd backend
cp .env.example .env          # fill in keys as they become available
uv sync --extra dev
uv run uvicorn app:app --port 8010

# Frontend — http://localhost:3000
cd frontend
cp .env.local.example .env.local
npm install
npm run dev
```

Port 8010 rather than 8000 only because 8000 was occupied during development;
`NEXT_PUBLIC_API_BASE_URL` in `frontend/.env.local` carries the choice.

## Checks

```bash
cd backend  && uv run pytest && uv run ruff check .
cd frontend && npx tsc --noEmit && npm run build
```

## Feasibility probes

These need real credentials. The OpenRouter probe spends no chat quota unless
`--generate` is passed, because the free-model allowance is small.

```bash
cd backend
uv run python ../scripts/feasibility/check_pinecone.py
uv run python ../scripts/feasibility/check_openrouter.py
uv run python ../scripts/feasibility/check_openrouter.py --generate <model-id>
uv run python ../scripts/feasibility/check_bioasq.py ../data/bioasq/<file>.json
```

## Corpus preparation

Fetches titles and abstracts from PubMed (public; an optional `NCBI_API_KEY`
raises the rate limit). Writes a resumable snapshot under `data/corpus/<name>/`.

```bash
cd backend
uv run python ../scripts/corpus/fetch_pubmed.py pmids.txt --name <snapshot-name>
```

## Benchmark and collection

Needs `data/bioasq/training14b.json` (BioASQ registration required). This
rebuilds `bioasq14b-v1` reproducibly from saved PubMed responses:

```bash
cd backend
uv run python ../scripts/benchmark/build_benchmark.py ../data/bioasq/training14b.json
```

## Retrieval evaluation

```bash
cd backend
uv run --env-file .env python ../scripts/indexing/build_index.py bioasq14b-v1   # once per collection version
uv run --env-file .env python ../scripts/evaluation/run_retrieval.py         # development split only
uv run --env-file .env python ../scripts/evaluation/analyze_retrieval.py <run_id>
```

## Constraints worth knowing

- **Zero paid services** is a project constraint. OpenRouter's free tier allows
  **50 requests/day**, which is tight against a 100-question benchmark — see
  section 4 of the feasibility report.
- Pinecone's free tier includes **5M embedding tokens/month**, which bounds
  corpus size and re-index cycles more than its 2 GB storage does.
- BioASQ data requires registration and carries NLM terms. Answer keys and
  split labels must never reach the searchable corpus or the frontend bundle.
