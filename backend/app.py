"""Vercel Python entrypoint.

Vercel loads the top-level `app` from this file (see `tool.vercel.entrypoint`).
The same object serves local `uvicorn app:app --reload`.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bla import __version__
from bla.config import settings

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
    }
