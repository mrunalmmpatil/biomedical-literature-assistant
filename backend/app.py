"""Vercel Python entrypoint.

Vercel loads the top-level `app` from this file (see `tool.vercel.entrypoint`).
The same object serves local `uvicorn app:app --reload`.
"""

import hashlib
import pathlib
from functools import cache

from fastapi import FastAPI, Request
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
from bla.followup import FollowUpSigner
from bla.ingest.snapshot import read_papers
from bla.llm import OpenRouter
from bla.quota import (
    AdmissionDenied,
    DailyCeilingReached,
    KeyConflict,
    MeteredLLM,
    Quota,
    StoreUnavailable,
    UpstashStore,
)
from bla.retrieval.bm25 import BM25Retriever

BACKEND = pathlib.Path(__file__).resolve().parent

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
        "snapshot_date": "2026-09-23",
        "question_types": ["fact", "list"],
        "not_supported": [
            "personal medical advice",
            "yes/no or open-ended summary questions",
            "questions outside biomedicine",
        ],
        "limits": {
            "questions_per_hour": settings.client_hourly_limit,
            "question_characters": MAX_QUESTION_CHARS,
        },
    }


class AnswerRequest(BaseModel):
    question: str = Field(max_length=MAX_QUESTION_CHARS)
    clarification_token: str | None = Field(default=None, max_length=4096)
    clarification_answer: str | None = Field(default=None, max_length=MAX_CLARIFICATION_CHARS)
    followup_token: str | None = Field(default=None, max_length=131072)
    request_key: str | None = Field(default=None, max_length=128)


def _refusal(status: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"outcome": Outcome.SERVICE_UNAVAILABLE.value, "message": message},
    )


@app.post("/api/answer")
def answer(body: AnswerRequest, request: Request) -> JSONResponse:
    blocker = _generation_blocker()
    if blocker:
        return _refusal(503, blocker)
    quota = _quota()
    fingerprint = key = None
    try:
        if quota:
            fingerprint = Quota.fingerprint(
                body.model_dump(
                    include={
                        "question",
                        "clarification_token",
                        "clarification_answer",
                        "followup_token",
                    }
                )
            )
            key = body.request_key
            if key:
                stored = quota.begin(key, fingerprint)
                if stored:  # a finished duplicate: return it, spend nothing
                    return JSONResponse(status_code=stored.http_status, content=stored.body)
            try:
                quota.admit(quota.client_key(_client_address(request)))
            except AdmissionDenied:
                if key:
                    quota.release(key)
                return _refusal(
                    429,
                    f"You have reached the limit of {quota.client_limit} questions per hour. "
                    "Please try again later.",
                )
        try:
            response, diag = _service().answer(
                body.question,
                clarification_token=body.clarification_token,
                clarification_answer=body.clarification_answer,
                followup_token=body.followup_token,
            )
        except InputError as exc:
            if key:
                quota.release(key)
            return JSONResponse(status_code=400, content={"detail": str(exc)})
        except DailyCeilingReached:
            if key:
                quota.release(key)
            return _refusal(
                429, "The demo has reached its daily question limit. Please try again tomorrow."
            )
        content = response.model_dump(mode="json")
        if key:
            quota.finish(key, fingerprint, content, diag.http_status)
        return JSONResponse(status_code=diag.http_status, content=content)
    except KeyConflict as exc:
        return JSONResponse(status_code=409, content={"detail": str(exc)})
    except StoreUnavailable:
        # Fail closed (technical PRD 8.2): no unmetered generation.
        return _refusal(503, "The answer service is unavailable right now. Please try again later.")


def _client_address(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def _corpus_file() -> pathlib.Path | None:
    if not settings.corpus_path:
        return None
    path = pathlib.Path(settings.corpus_path)
    return path if path.is_absolute() else BACKEND / path


def _generation_blocker() -> str | None:
    """Why generation is refused, or None. Public generation needs shared
    admission control (technical PRD 8.2); unmetered use is local-only."""
    corpus = _corpus_file()
    if not (settings.openrouter_api_key and settings.clarification_secret and corpus):
        return "Answer generation is not configured."
    if not corpus.exists():
        return "The paper collection is not available on this deployment."
    if not (_quota() or settings.allow_unmetered_generation):
        return "Answer generation is not enabled on this deployment yet."
    return None


@cache
def _quota() -> Quota | None:
    if not (settings.kv_rest_api_url and settings.kv_rest_api_token):
        return None
    salt = hashlib.sha256(f"quota|{settings.clarification_secret}".encode()).hexdigest()
    return Quota(
        UpstashStore(settings.kv_rest_api_url, settings.kv_rest_api_token),
        salt=salt,
        client_limit=settings.client_hourly_limit,
        daily_ceiling=settings.public_daily_attempts,
    )


@cache
def _service() -> AnswerService:
    papers = read_papers(_corpus_file())
    llm = OpenRouter(settings.openrouter_api_key)
    quota = _quota()
    return AnswerService(
        BM25Retriever(papers),
        {p.pmid: p for p in papers},
        MeteredLLM(llm, quota) if quota else llm,
        ClarificationSigner(settings.clarification_secret),
        corpus_version=settings.corpus_version,
        followups=FollowUpSigner(settings.clarification_secret),
    )
