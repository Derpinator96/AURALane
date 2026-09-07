"""Integration test for human override API endpoints."""
import pytest
from fastapi.testclient import TestClient
from server import app, _overrides


@pytest.fixture(autouse=True)
def clear_overrides():
    _overrides.clear()


client = TestClient(app)


def test_health_endpoint():
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert "scores" in data
    assert "overrides_count" in data


def test_override_endpoint():
    payload = {
        "study_id": "ST-001",
        "action": "OVERRIDE",
        "ai_lane": "ROUTINE",
        "human_lane": "CRITICAL",
        "reason": "Visible pneumothorax missed by low threshold",
        "reviewer": "Dr. Smith"
    }
    res = client.post("/api/override", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["override"]["human_lane"] == "CRITICAL"

    # Verify /api/overrides endpoint
    get_res = client.get("/api/overrides")
    assert get_res.status_code == 200
    all_overrides = get_res.json()["overrides"]
    assert "ST-001" in all_overrides
    assert all_overrides["ST-001"]["reviewer"] == "Dr. Smith"
