# Biomedical Literature Assistant

Answers focused biomedical questions from a controlled collection of published
titles and abstracts, with citations and inspectable source text.

**Status: Milestone 2 built; Milestone 3 (retrieval comparison) next.**

- Milestone 1: every service was verified against a real account, and both
  apps are deployed ([feasibility report](docs/feasibility-report.md)):
  https://bla-frontend-gilt.vercel.app → https://bla-backend.vercel.app/api/health
- Milestone 2: 100 BioASQ questions (25 fact + 25 list per split) and a
  frozen 3,653-paper collection ([data protocol](docs/data-protocol.md)).

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

## Layout

```text
backend/              FastAPI service (Vercel entrypoint: app.py)
frontend/             Next.js interface
scripts/feasibility/  Milestone 1 provider probes
scripts/benchmark/    Milestone 2 benchmark and collection builder
scripts/corpus/       Ad-hoc PubMed snapshot fetcher
evaluation/manifests/ Tracked benchmark manifests (IDs and hashes; no answers)
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

## Constraints worth knowing

- **Zero paid services** is a project constraint. OpenRouter's free tier allows
  **50 requests/day**, which is tight against a 100-question benchmark — see
  section 4 of the feasibility report.
- Pinecone's free tier includes **5M embedding tokens/month**, which bounds
  corpus size and re-index cycles more than its 2 GB storage does.
- BioASQ data requires registration and carries NLM terms. Answer keys and
  split labels must never reach the searchable corpus or the frontend bundle.
