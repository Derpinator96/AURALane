"""Hosted-preview configuration: startup refusal, public blob URLs, CORS.

The hosted API is the fixture runtime on another origin than the client. These
tests pin the three things that differ from local development, and that local
development (loopback, no variables) behaves exactly as before.
"""
import pytest
from fastapi.testclient import TestClient

import core.run as run
from core.api import DEV_ORIGINS, create_app
from core.providers.fixture import BLOB, FixtureDatastore, FixtureTable
from core.providers.local import DevAuth, FileBlob, TemplateLLM

HOSTED = ("AURALANE_DEV_PASSWORD", "AURALANE_DEV_JWT_SECRET", "AURALANE_PUBLIC_URL")


@pytest.fixture
def served(monkeypatch):
    """Stub uvicorn.run and providers(), recording what serve would have done."""
    import uvicorn
    calls = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.update(app=app, **kw))
    monkeypatch.setattr(run, "providers", lambda: calls.setdefault("providers", True) and _fixture())
    monkeypatch.setenv("AURALANE_RUNTIME", "fixture")
    for v in HOSTED + ("AURALANE_CORS_ORIGINS",):
        monkeypatch.delenv(v, raising=False)
    return calls


def _fixture():
    table = FixtureTable()
    return {"runtime": "fixture", "blob": FileBlob(BLOB, url_base="/api/blob"), "table": table,
            "datastore": FixtureDatastore(table), "auth": DevAuth(password="x"),
            "llm": TemplateLLM()}


def test_non_loopback_serve_refuses_without_hosted_variables(served):
    with pytest.raises(SystemExit) as e:
        run.main(["serve", "--host", "0.0.0.0", "--port", "8101"])
    message = str(e.value)
    for v in HOSTED:
        assert v in message, f"{v} not named in: {message}"
    # refused before providers(): DevAuth never ran, so no password file was made
    assert "providers" not in served and "app" not in served


@pytest.mark.parametrize("missing", HOSTED)
def test_each_hosted_variable_is_required_on_its_own(served, monkeypatch, missing):
    for v in HOSTED:
        if v != missing:
            monkeypatch.setenv(v, "set")
    with pytest.raises(SystemExit) as e:
        run.main(["serve", "--host", "0.0.0.0"])
    assert missing in str(e.value)
    assert all(v not in str(e.value) for v in HOSTED if v != missing)


def test_non_loopback_serve_starts_with_all_hosted_variables(served, monkeypatch):
    for v in HOSTED:
        monkeypatch.setenv(v, "set")
    assert run.main(["serve", "--host", "0.0.0.0", "--port", "8101"]) == 0
    assert served["host"] == "0.0.0.0" and served["port"] == 8101


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
def test_loopback_serve_needs_nothing_new(served, host):
    """Local development is unchanged: no variables, and serve starts."""
    assert run.main(["serve", "--host", host]) == 0
    assert served["host"] == host


def test_default_serve_is_loopback(served):
    assert run.main(["serve"]) == 0
    assert served["host"] == "127.0.0.1"


def test_blob_urls_are_relative_by_default(monkeypatch):
    monkeypatch.delenv("AURALANE_PUBLIC_URL", raising=False)
    assert run._blob_url() == "/api/blob"


def test_blob_urls_are_absolute_when_hosted(monkeypatch):
    """Evidence overlays go straight into <img src>. A relative URL would resolve
    against the client's host, which has no API."""
    monkeypatch.setenv("AURALANE_PUBLIC_URL", "https://auralane-api.onrender.com/")
    monkeypatch.setenv("AURALANE_RUNTIME", "fixture")
    # From the environment, so DevAuth never creates data/dev files in a test.
    monkeypatch.setenv("AURALANE_DEV_PASSWORD", "x")
    monkeypatch.setenv("AURALANE_DEV_JWT_SECRET", "x")
    blob = run.providers()["blob"]
    url = blob.presigned_url("evidence/fixture-sample/gradcam_edema.png")
    assert url.startswith("https://auralane-api.onrender.com/api/blob/evidence/")


def test_cors_origins_parse(monkeypatch):
    monkeypatch.setenv("AURALANE_CORS_ORIGINS", " https://a.vercel.app/ , https://b.example , https://c.vercel.app/login")
    assert run.cors_origins() == ["https://a.vercel.app", "https://b.example", "https://c.vercel.app"]
    monkeypatch.setenv("AURALANE_CORS_ORIGINS", "")
    assert run.cors_origins() is None


def _preflight(client, origin):
    return client.options("/api/worklist", headers={
        "Origin": origin, "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization"})


def test_cors_allows_the_configured_origin_only():
    c = TestClient(create_app(_fixture(), cors_origins=["https://auralane.vercel.app"]))
    ok = _preflight(c, "https://auralane.vercel.app")
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == "https://auralane.vercel.app"
    assert "authorization" in ok.headers["access-control-allow-headers"].lower()
    bad = _preflight(c, "https://evil.example")
    assert "access-control-allow-origin" not in bad.headers


def test_cors_defaults_to_development_origins():
    c = TestClient(create_app(_fixture()))
    for origin in DEV_ORIGINS:
        assert _preflight(c, origin).headers["access-control-allow-origin"] == origin
    assert "access-control-allow-origin" not in _preflight(c, "https://x.vercel.app").headers


@pytest.mark.parametrize("origins", [["https://auralane.vercel.app"], ["*"]])
def test_cors_never_allows_credentials(origins):
    """Tokens travel in a header, not a cookie. Credentials stay off, so even a
    wildcard is never combined with them."""
    c = TestClient(create_app(_fixture(), cors_origins=origins))
    r = _preflight(c, "https://auralane.vercel.app")
    assert r.headers.get("access-control-allow-credentials") is None
    r = c.get("/api/health", headers={"Origin": "https://auralane.vercel.app"})
    assert r.headers.get("access-control-allow-credentials") is None
