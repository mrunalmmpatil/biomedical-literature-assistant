from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_health_reports_ok_without_calling_a_model():
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "corpus_version" in body


def test_health_never_leaks_credentials():
    body = client.get("/api/health").text
    for secret_marker in ("api_key", "sk-", "pcsk_"):
        assert secret_marker not in body
    assert isinstance(body, str)


def test_blank_environment_values_are_not_configured(monkeypatch):
    """A .env template ships with empty values. Those must read as absent,
    not as a present credential."""
    from bla.config import Settings

    monkeypatch.setenv("PINECONE_API_KEY", "")
    monkeypatch.setenv("OPENROUTER_API_KEY", "   ")
    monkeypatch.setenv("CORPUS_VERSION", "")
    blank = Settings(_env_file=None)

    assert blank.pinecone_api_key is None
    assert blank.openrouter_api_key is None
    assert blank.corpus_version is None


def test_present_environment_values_are_configured(monkeypatch):
    from bla.config import Settings

    monkeypatch.setenv("PINECONE_API_KEY", "pcsk_example")
    configured = Settings(_env_file=None)
    assert configured.pinecone_api_key == "pcsk_example"


def test_origins_splits_and_trims(monkeypatch):
    from bla.config import Settings

    monkeypatch.setenv("ALLOWED_ORIGINS", "http://a.test, http://b.test ,")
    assert Settings(_env_file=None).origins() == ["http://a.test", "http://b.test"]
