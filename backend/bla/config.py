"""Backend configuration.

Secrets are read from the environment only. Nothing here is returned to clients;
`/api/health` reports readiness flags, never values.
"""

from typing import Annotated

from pydantic import BeforeValidator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _blank_to_none(value: object) -> object:
    """An unset variable and a variable set to "" both mean "not configured".

    `.env` templates ship with empty values, so without this an empty string
    would read as a present credential. Absent is null, never a falsy value
    that later code treats as configured.
    """
    if isinstance(value, str) and not value.strip():
        return None
    return value


Optional = Annotated[str | None, BeforeValidator(_blank_to_none)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Provider credentials. Absent values mean "not configured yet", not an error:
    # milestone 1 runs before the accounts exist.
    pinecone_api_key: Optional = None
    openrouter_api_key: Optional = None

    # NCBI E-utilities (offline corpus preparation only). Both optional: a key
    # raises the polite rate from 3 to 10 requests/second, and NCBI asks for a
    # contact email so it can reach the operator before blocking a client.
    ncbi_api_key: Optional = None
    ncbi_email: Optional = None

    # Signs clarification tokens (technical PRD 6.1). Required before the
    # answer endpoint can issue one; never sent to clients.
    clarification_secret: Optional = None

    # Corpus identity. Set once a snapshot is frozen (technical PRD section 3.3).
    corpus_version: Optional = None

    allowed_origins: str = "http://localhost:3000"

    # Answer generation (technical PRD 8.2). Public generation requires shared
    # admission control, which does not exist yet, so it is off unless this
    # is explicitly enabled for local development. Fail closed by default.
    allow_unmetered_generation: bool = False
    corpus_path: Optional = None
    """papers.jsonl of the frozen collection the answer endpoint searches;
    relative paths resolve against the backend directory."""

    # Shared admission control (technical PRD 8.2): Upstash Redis, provisioned
    # through the Vercel integration, which sets these names.
    kv_rest_api_url: Optional = None
    kv_rest_api_token: Optional = None
    public_daily_attempts: int = 300
    """Site-wide provider attempts per UTC day, below the 1,000 free allowance."""
    client_hourly_limit: int = 5

    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


settings = Settings()
