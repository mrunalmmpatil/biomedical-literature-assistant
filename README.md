# Biomedical Literature Assistant

Answers focused biomedical questions from a controlled collection of published
titles and abstracts, with citations and inspectable source text.

**Status: Milestone 1 — proving service compatibility.** Provider-independent
core is in place and tested: data contracts, PubMed collection (verified live),
the BM25 baseline, the Pinecone retriever (not yet run against a real index),
answer/citation validation, and signed clarification tokens. No corpus or
answer generation exists yet. See [`docs/feasibility-report.md`](docs/feasibility-report.md)
for what has actually been verified, and against what evidence.

## Documents

| Document | What it covers |
|---|---|
| [`PRD.md`](PRD.md) | Product requirements, user stories, scope |
| [`TECHNICAL_PRD.md`](TECHNICAL_PRD.md) | Architecture, contracts, limits, evaluation protocol |
| [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) | Milestones and completion gates |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Plain-language walkthrough with diagrams |
| [`docs/feasibility-report.md`](docs/feasibility-report.md) | Measured provider limits and integration evidence |

## Layout

```text
backend/              FastAPI service (Vercel entrypoint: app.py)
frontend/             Next.js interface
scripts/feasibility/  Milestone 1 provider probes
evaluation/           Evaluation definitions and permitted artifacts
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

## Constraints worth knowing

- **Zero paid services** is a project constraint. OpenRouter's free tier allows
  **50 requests/day**, which is tight against a 100-question benchmark — see
  section 4 of the feasibility report.
- Pinecone's free tier includes **5M embedding tokens/month**, which bounds
  corpus size and re-index cycles more than its 2 GB storage does.
- BioASQ data requires registration and carries NLM terms. Answer keys and
  split labels must never reach the searchable corpus or the frontend bundle.
