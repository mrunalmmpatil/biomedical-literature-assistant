"""Vercel Python entrypoint.

Vercel loads the top-level `app` from this file (see `tool.vercel.entrypoint`).
The same object serves local `uvicorn app:app --reload`.
"""

import pathlib
from functools import cache

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from bla import __version__
from bla.answering.service import (
    MAX_CLARIFICATION_CHARS,
    MAX_QUESTION_CHARS,
    AnswerService,
    InputError,
)
from bla.clarification import ClarificationSigner
from bla.config import settings
from bla.contracts import Outcome
from bla.ingest.snapshot import read_papers
from bla.llm import OpenRouter
from bla.retrieval.bm25 import BM25Retriever

app = FastAPI(title="Biomedical Literature Assistant", version=__version__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins(),
    allow_methods=["GET", "POST"],
    allow_headers=["content-type"],
)


@app.get("/api/health")
def health() -> dict[str, object]:
    """Readiness without a model call. Reports whether providers are configured,
    never the credentials themselves."""
    return {
        "status": "ok",
        "service_version": __version__,
        "corpus_version": settings.corpus_version,
        "providers_configured": {
            "pinecone": settings.pinecone_api_key is not None,
            "openrouter": settings.openrouter_api_key is not None,
        },
        "generation_enabled": _generation_blocker() is None,
    }


@app.get("/api/coverage")
def coverage() -> dict[str, object]:
    """What the assistant can and cannot answer from. No model call."""
    return {
        "corpus_version": settings.corpus_version,
        "scope": "Published PubMed titles and abstracts only; no full text.",
        "collection": (
            "A fixed collection of 3,653 PubMed records assembled for evaluation: "
            "reference papers for 100 BioASQ questions plus PubMed-related articles. "
            "It is not a search of all of PubMed."
        ),
        "question_types": ["fact", "list"],
        "not_supported": [
            "personal medical advice",
            "yes/no or open-ended summary questions",
            "questions outside biomedicine",
        ],
    }


class AnswerRequest(BaseModel):
    question: str = Field(max_length=MAX_QUESTION_CHARS)
    clarification_token: str | None = Field(default=None, max_length=4096)
    clarification_answer: str | None = Field(default=None, max_length=MAX_CLARIFICATION_CHARS)
    request_key: str | None = Field(default=None, max_length=128)


@app.post("/api/answer")
def answer(request: AnswerRequest) -> JSONResponse:
    blocker = _generation_blocker()
    if blocker:
        return JSONResponse(
            status_code=503,
            content={"outcome": Outcome.SERVICE_UNAVAILABLE.value, "message": blocker},
        )
    try:
        response, diag = _service().answer(
            request.question,
            clarification_token=request.clarification_token,
            clarification_answer=request.clarification_answer,
        )
    except InputError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    return JSONResponse(status_code=diag.http_status, content=response.model_dump(mode="json"))


def _generation_blocker() -> str | None:
    """Why generation is refused, or None. Public generation stays off until
    shared admission control exists (technical PRD 8.2)."""
    if not settings.allow_unmetered_generation:
        return "Answer generation is not enabled on this deployment yet."
    if not (settings.openrouter_api_key and settings.clarification_secret and settings.corpus_path):
        return "Answer generation is not configured."
    return None


@cache
def _service() -> AnswerService:
    papers = read_papers(pathlib.Path(settings.corpus_path))
    return AnswerService(
        BM25Retriever(papers),
        {p.pmid: p for p in papers},
        OpenRouter(settings.openrouter_api_key),
        ClarificationSigner(settings.clarification_secret),
        corpus_version=settings.corpus_version,
    )
