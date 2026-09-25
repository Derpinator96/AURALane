"""Write the client test fixtures: API responses as the fixture API returns them.

    python scripts/export_client_fixture.py

client/src/test/worklist.api.json   GET /api/worklist
client/src/test/study.api.json      GET /api/studies/{STUDY} and its first series
client/src/test/admin.api.json      GET /api/admin/lane-mix and /api/admin/models

The client tests render these, so they test the shape the API really sends.
tests/test_client_fixture.py fails if either drifts from the API. The signed
blob URLs carry an expiry, so they are replaced by a fixed placeholder path.
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "client" / "src" / "test" / "worklist.api.json"
STUDY_OUT = ROOT / "client" / "src" / "test" / "study.api.json"
ADMIN_OUT = ROOT / "client" / "src" / "test" / "admin.api.json"
STUDY = "fixture-cr-ST-028"          # chest, driver Nodule, Grad-CAM coverage above zero


def _client(user="radiologist"):
    from fastapi.testclient import TestClient
    from core.api import create_app
    from core.providers.fixture import BLOB, FixtureDatastore, FixtureTable
    from core.providers.local import DevAuth, FileBlob, TemplateLLM
    table, auth = FixtureTable(), DevAuth()
    app = create_app({"runtime": "fixture", "blob": FileBlob(BLOB, url_base="/api/blob"),
                      "table": table, "datastore": FixtureDatastore(table), "auth": auth,
                      "llm": TemplateLLM()})
    return TestClient(app), {"Authorization": f"Bearer {auth.issue(user)}"}


def current() -> dict:
    c, h = _client()
    r = c.get("/api/worklist", headers=h)
    r.raise_for_status()
    return r.json()


def current_study() -> dict:
    c, h = _client()
    detail = c.get(f"/api/studies/{STUDY}", headers=h).json()
    detail["evidence_urls"] = {k: f"/api/blob/{detail['evidence'][k]}?signed"
                               for k in detail["evidence_urls"]}
    series = c.get(f"/api/studies/{STUDY}/series/{detail['series'][0]['series_uid']}",
                   headers=h).json()
    return {"detail": detail, "series": series}


def current_admin() -> dict:
    c, h = _client("admin")
    return {"lane_mix": c.get("/api/admin/lane-mix", headers=h).json(),
            "models": c.get("/api/admin/models", headers=h).json()}


def render(data: dict) -> str:
    return json.dumps(data, indent=1) + "\n"


if __name__ == "__main__":
    OUT.write_text(render(current()))
    STUDY_OUT.write_text(render(current_study()))
    ADMIN_OUT.write_text(render(current_admin()))
    print(f"wrote {OUT.relative_to(ROOT)}, {STUDY_OUT.relative_to(ROOT)} and "
          f"{ADMIN_OUT.relative_to(ROOT)}")
