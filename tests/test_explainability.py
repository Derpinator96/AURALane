"""Tests for the explainability module and Grad-CAM endpoints."""
import pytest
from fastapi.testclient import TestClient
from server import app
import explainability


client = TestClient(app)


def test_explain_endpoint_prototype_modality():
    payload = {
        "study_id": "CT-001",
        "filename": "ct_head_001.dcm",
        "target_pathology": "Intracranial_Hemorrhage",
        "modality": "CT"
    }
    res = client.post("/api/explain", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["supported"] is False
    assert "PROTOTYPE/EXPERIMENTAL" in data["reason"]


def test_explain_endpoint_cxr_missing_file():
    payload = {
        "study_id": "ST-001",
        "filename": "non_existent_file.png",
        "target_pathology": "Pneumothorax",
        "modality": "CXR"
    }
    res = client.post("/api/explain", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["supported"] is False
    assert "not found on disk" in data["reason"]
