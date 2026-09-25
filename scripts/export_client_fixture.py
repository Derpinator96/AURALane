"""Write client/src/test/worklist.api.json: /api/worklist as the fixture API returns it.

    python scripts/export_client_fixture.py

The client tests render this file, so they test the shape the API really
sends. tests/test_client_fixture.py fails if it drifts from the API.
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "client" / "src" / "test" / "worklist.api.json"


def current() -> dict:
    from fastapi.testclient import TestClient
    from core.api import create_app
    from core.providers.fixture import FixtureDatastore, FixtureTable
    from core.providers.local import DevAuth, FileBlob, TemplateLLM
    table, auth = FixtureTable(), DevAuth()
    app = create_app({"runtime": "fixture", "blob": FileBlob(tempfile.mkdtemp()),
                      "table": table, "datastore": FixtureDatastore(table), "auth": auth,
                      "llm": TemplateLLM()})
    r = TestClient(app).get("/api/worklist",
                            headers={"Authorization": f"Bearer {auth.issue('radiologist')}"})
    r.raise_for_status()
    return r.json()


def render(data: dict) -> str:
    return json.dumps(data, indent=1) + "\n"


if __name__ == "__main__":
    OUT.write_text(render(current()))
    print(f"wrote {OUT.relative_to(ROOT)}")
