"""Unit tests for Clinician Pinpoint Notes & Annotations persistent feature."""
import os
import pytest
from core.api import create_app
from core.run import providers
from core.types import Principal


@pytest.fixture
def client():
    from starlette.testclient import TestClient
    os.environ["AURALANE_RUNTIME"] = "fixture"
    p = providers()
    app = create_app(p)
    c = TestClient(app)
    token = p["auth"].issue("radiologist")
    c.headers["Authorization"] = f"Bearer {token}"
    return c


def test_annotations_crud_lifecycle(client):
    # 1. Get annotations for a study (initially empty or existing fixture)
    res = client.get("/api/studies/fixture-mr-brain-01/annotations")
    assert res.status_code == 200
    data = res.json()
    assert "annotations" in data
    assert data["study"] == "fixture-mr-brain-01"
    initial_count = data["total"]

    # 2. Create an MRI Brain Tumor Annotation (Spatially anchored: voxel & world_mm with ET region)
    mri_ann_payload = {
        "modality": "MR",
        "coordinate_space": "NIFTI_WORLD",
        "voxel": {"x": 140.5, "y": 82.0, "z": 70.0},
        "world_mm": {"x": -140.5, "y": 156.9, "z": 70.0},
        "segmentation_region": "ET (Enhancing Tumor)",
        "note_text": "Review enhancing rim margin for subtotal resection planning.",
        "viewer_context": {"sequence": "t1ce", "plane": "Axial"},
        "metadata": {"custom_tag": "urgent_eval"}
    }
    create_res = client.post(
        "/api/studies/fixture-mr-brain-01/annotations",
        json=mri_ann_payload
    )
    assert create_res.status_code == 200
    created_ann = create_res.json()["annotation"]
    ann_id = created_ann["id"]
    assert created_ann["study"] == "fixture-mr-brain-01"
    assert created_ann["note_text"] == "Review enhancing rim margin for subtotal resection planning."
    assert created_ann["segmentation_region"] == "ET (Enhancing Tumor)"
    assert created_ann["voxel"]["x"] == 140.5
    assert created_ann["world_mm"]["y"] == 156.9
    assert created_ann["created_by"].startswith("radiologist@")

    # 3. Retrieve by ID
    get_res = client.get(f"/api/annotations/{ann_id}")
    assert get_res.status_code == 200
    assert get_res.json()["annotation"]["id"] == ann_id

    # 4. Patch/Update the annotation
    patch_res = client.patch(
        f"/api/annotations/{ann_id}",
        json={"note_text": "Updated: Necrotic core transition confirmed."}
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["annotation"]["note_text"] == "Updated: Necrotic core transition confirmed."

    # 5. Query study annotations again and verify count increased
    list_res = client.get("/api/studies/fixture-mr-brain-01/annotations")
    assert list_res.status_code == 200
    assert list_res.json()["total"] == initial_count + 1

    # 6. Delete the annotation
    del_res = client.delete(f"/api/annotations/{ann_id}")
    assert del_res.status_code == 200
    assert del_res.json()["deleted"] is True

    # 7. Verify deletion
    list_after_del = client.get("/api/studies/fixture-mr-brain-01/annotations")
    assert list_after_del.json()["total"] == initial_count


def test_cxr_and_ct_annotation_support(client):
    # Chest X-Ray normalized coordinate annotation
    cxr_payload = {
        "modality": "CR",
        "coordinate_space": "IMAGE_NORMALIZED",
        "coordinate_x": 0.62,
        "coordinate_y": 0.41,
        "slice_index": 0,
        "segmentation_region": "Chest Radiograph",
        "note_text": "Right lower lobe consolidative opacity consistent with pneumonia."
    }
    cxr_res = client.post(
        "/api/studies/fixture-cr-chest-01/annotations",
        json=cxr_payload
    )
    assert cxr_res.status_code == 200
    cxr_ann = cxr_res.json()["annotation"]
    assert cxr_ann["coordinate_x"] == 0.62
    assert cxr_ann["coordinate_y"] == 0.41
    assert cxr_ann["coordinate_space"] == "IMAGE_NORMALIZED"

    # Head CT slice index annotation
    ct_payload = {
        "modality": "CT",
        "coordinate_space": "IMAGE_NORMALIZED",
        "coordinate_x": 0.54,
        "coordinate_y": 0.38,
        "slice_index": 18,
        "segmentation_region": "Localized subarachnoid Hemorrhage",
        "note_text": "Hyperdense signal in right sylvian fissure."
    }
    ct_res = client.post(
        "/api/studies/fixture-ct-head-01/annotations",
        json=ct_payload
    )
    assert ct_res.status_code == 200
    ct_ann = ct_res.json()["annotation"]
    assert ct_ann["slice_index"] == 18
    assert ct_ann["segmentation_region"] == "Localized subarachnoid Hemorrhage"
