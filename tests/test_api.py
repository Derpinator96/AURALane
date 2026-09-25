"""The worklist API (python -m core.run serve), against DynamoDB Local."""
import uuid

import pytest
from fastapi.testclient import TestClient

from core.providers.local import DevAuth, DynamoLocalTable, FileBlob, OrthancDatastore, TemplateLLM
from core.run import DISCLAIMER, create_app
from core.types import AuditEvent


@pytest.fixture
def api(tmp_path):
    auth = DevAuth()
    table = DynamoLocalTable(prefix=f"test-{uuid.uuid4().hex[:8]}")
    rows = [("s-routine", "ROUTINE", 10.0), ("s-crit", "CRITICAL", 90.0),
            ("s-abstain", "ABSTAIN", None), ("s-urgent-lo", "URGENT", 55.0),
            ("s-urgent-hi", "URGENT", 70.0), ("run:abc", "FAILED", None)]
    for i, (study, lane, acuity) in enumerate(rows):
        table.put_item("worklist", {
            "study": study, "lane": lane, "status": "FAILED" if lane == "FAILED" else "SCORED",
            "model_id": "cxr-densenet-v1", "datastore_id": "orthanc-id",
            "triage": {"acuity": acuity, "driver": "Edema"} if acuity else {},
            "findings": {"Edema": 0.9}, "evidence": {}, "created_at": f"2026-09-25T00:00:0{i}Z"})
    table.append_audit(AuditEvent("pipeline", "triage", "s-crit", "2026-09-25T00:00:00Z",
                                  "ok", 0.2))
    app = create_app({"runtime": "local", "blob": FileBlob(tmp_path), "table": table,
                      "datastore": OrthancDatastore(), "auth": auth, "llm": TemplateLLM()})
    return TestClient(app), {"Authorization": f"Bearer {auth.issue('radiologist')}"}


def test_health_is_open_and_carries_disclaimer(api):
    client, _ = api
    assert client.get("/api/health").json()["disclaimer"] == DISCLAIMER


def test_every_other_route_needs_a_token(api):
    client, _ = api
    for url in ("/api/worklist", "/api/studies/s-crit", "/api/studies/s-crit/frame_url?series=1&instance=2"):
        assert client.get(url).status_code == 401
        assert client.get(url, headers={"Authorization": "Bearer nonsense"}).status_code == 401


def test_worklist_order_matches_the_round2_queue(api):
    client, auth = api
    body = client.get("/api/worklist", headers=auth).json()
    assert body["disclaimer"] == DISCLAIMER
    assert [r["study"] for r in body["studies"]] == [
        "s-crit", "s-urgent-hi", "s-urgent-lo", "s-abstain", "run:abc", "s-routine"]


def test_study_detail_has_audit_and_template_draft(api):
    client, auth = api
    body = client.get("/api/studies/s-crit", headers=auth).json()
    assert [a["action"] for a in body["audit"]] == ["triage"]
    assert body["draft"].startswith("NON-DIAGNOSTIC")
    assert client.get("/api/studies/missing", headers=auth).status_code == 404


def test_frame_url_is_a_url_not_pixels(api):
    client, auth = api
    r = client.get("/api/studies/s-crit/frame_url?series=1.2&instance=3.4&frame=1", headers=auth)
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["url"].endswith("/studies/s-crit/series/1.2/instances/3.4/frames/1")
