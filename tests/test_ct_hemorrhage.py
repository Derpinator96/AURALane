"""Head CT hemorrhage triage and its Grad-CAM (core/ct_hemorrhage.py).

Fast tests stage uploads, map results onto rows and drive the upload route with
the model stubbed. The model tests run Mehak's pipeline on the local RSNA
studies in "ct scan data/" and require that core.ct_hemorrhage reproduces her
score_study_from_folder exactly: score, lane, driving subtype, Grad-CAM slice
and box. They skip only where that data or the cached weights are absent.
"""
import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from core import ct_hemorrhage as ct
from core.api import create_app
from core.providers.fixture import BLOB, WORKLIST, FixtureDatastore, FixtureTable
from core.providers.local import DevAuth, FileBlob, TemplateLLM

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "ct scan data"
PASSWORD = "ct-test-password"
DICM = b"\0" * 128 + b"DICM" + b"\0" * 16


# -- staging ------------------------------------------------------------------
def test_stage_takes_loose_dicom_and_zip_members_and_skips_the_rest(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("study/a.dcm", DICM)
        zf.writestr("study/no_extension", DICM)        # found by the DICM preamble
        zf.writestr("study/readme.txt", b"not an image")
        zf.writestr("../../escape.dcm", DICM)          # staged under our own name
    n = ct.stage_upload([("one.dcm", DICM), ("Thumbs.db", b"junk"),
                         ("study.zip", buf.getvalue())], tmp_path)
    staged = sorted(p.name for p in tmp_path.iterdir())
    assert n == 4 and len(staged) == 4
    assert all(name.endswith(".dcm") for name in staged)
    assert not (tmp_path.parent / "escape.dcm").exists()


def test_stage_refuses_an_upload_with_no_dicom(tmp_path):
    with pytest.raises(ct.InvalidCTInput, match="no DICOM"):
        ct.stage_upload([("scan.png", b"\x89PNG....")], tmp_path)
    with pytest.raises(ct.InvalidCTInput, match="zip"):
        ct.stage_upload([("broken.zip", b"PK not really")], tmp_path)


# -- mapping onto a worklist row ----------------------------------------------
def _scored(**over):
    r = {"study_score": 0.931, "raw_score": 0.812, "k_used": 5, "n_slices": 18,
         "dominant_subtype": "subarachnoid", "decision_reason": "Urgency-weighted ... ",
         "lane": "critical", "abstain": False, "in_abstention_tray": False,
         "sort_score": 0.931, "abstain_reason": None,
         "localization": {"slice_index": 15, "slice_id": "ID_1.dcm"}}
    r.update(over)
    probs = {"epidural": 0.01, "intraparenchymal": 0.05, "intraventricular": 0.02,
             "subarachnoid": 0.82, "subdural": 0.07}
    weights = {"epidural": 1.25, "subdural": 1.15, "subarachnoid": 1.15,
               "intraparenchymal": 1.05, "intraventricular": 1.0}
    return {"result": r, "subtype_probs": probs, "urgency_weights": weights}


def test_lanes_map_onto_the_worklist_lanes_with_their_sla():
    for theirs, ours in ct.LANES.items():
        lane, t, findings = ct.triage_fields(_scored(lane=theirs))
        assert lane == ours == t["lane"]
        assert t["sla"] == ct.SLA[ours][0] and t["sla_minutes"] == ct.SLA[ours][1]
    lane, t, findings = ct.triage_fields(_scored())
    assert t["acuity"] == 93.1 and t["signal"] == 0.931 and t["raw_score"] == 0.812
    assert t["driver"] == "Subarachnoid" and t["confidence"] == 0.82
    assert findings == {"Epidural": 0.01, "Intraparenchymal": 0.05, "Intraventricular": 0.02,
                        "Subarachnoid": 0.82, "Subdural": 0.07}
    assert t["top_findings"][0] == {"name": "Subarachnoid", "signal": 0.82, "urgency": 1.15}


def test_abstention_is_abstain_with_her_reason():
    lane, t, _ = ct.triage_fields(_scored(lane=None, abstain=True,
                                          abstain_reason="Borderline Critical/Urgent (score=0.852) "))
    assert lane == "ABSTAIN" and t["abstained"] is True
    assert t["reason"] == "Borderline Critical/Urgent (score=0.852)"
    assert t["sla_minutes"] is None


# -- in the pipeline: the CT endpoint's evidence reaches the row ----------------
# (His upload route scored CT inside the API; on this platform the CT endpoint
# writes the same evidence, core/ct_gradcam.py, and the adapter carries it.)
def test_the_ct_adapter_carries_the_gradcam_evidence_the_endpoint_wrote():
    from adapters import ct_hemorrhage as adapter
    from core.registry import Registry
    entry = Registry().get("ct-ich-vit-v1")
    out = {"raw_score": 0.8, "study_score": 0.8, "k_used": 3, "n_slices": 17,
           "dominant_subtype": "subdural", "top_slice_index": 4,
           "subtype_scores": {"subdural": 0.8},
           "evidence": {"ct_slice_png": "evidence/x/ct_slice.png",
                        "gradcam_layer_png": "evidence/x/gradcam_subdural_layer.png",
                        "gradcam_bbox": {"row_min": 1, "row_max": 5, "col_min": 2, "col_max": 6}}}
    f = adapter.adapt(out, {"entry": entry})
    assert f.evidence["ct_slice_png"] == "evidence/x/ct_slice.png"
    assert f.evidence["gradcam_bbox"]["row_max"] == 5
    assert f.evidence["ct"]["top_slice_index"] == 4


def test_the_fixture_ct_row_is_a_model_run_with_its_evidence_on_disk():
    rows = [r for r in json.loads(WORKLIST.read_text()) if r["modality"] == "CT"]
    assert len(rows) == 1
    row = rows[0]
    assert row["model_id"] == ct.MODEL_ID and "make_ct_fixture.py" in row["source"]
    for key in ("ct_slice_png", "gradcam_layer_png"):
        path = BLOB / row["evidence"][key]
        assert path.is_file(), path
    slice_ = Image.open(BLOB / row["evidence"]["ct_slice_png"])
    layer = Image.open(BLOB / row["evidence"]["gradcam_layer_png"])
    assert slice_.size == layer.size == (row["evidence"]["frame_cols"], row["evidence"]["frame_rows"])
    assert layer.mode == "RGBA"


# -- the model, on the local RSNA studies ----------------------------------------
def _model_available() -> str | None:
    if not DATA.is_dir():
        return f"{DATA.name}/ is not on this machine"
    try:
        import transformers  # noqa: F401
        from huggingface_hub import try_to_load_from_cache
    except ImportError as e:
        return f"transformers is not installed ({e})"
    ct._ct()
    from triagelane_ct.model import MODEL_NAME
    if not isinstance(try_to_load_from_cache(MODEL_NAME, "config.json"), str):
        return f"{MODEL_NAME} weights are not cached; run the pipeline once online"
    return None


STUDIES = sorted(p.name for p in DATA.iterdir() if p.is_dir()) if DATA.is_dir() else []


@pytest.fixture(scope="module")
def model():
    reason = _model_available()
    if reason:
        pytest.skip(reason)


@pytest.mark.parametrize("study", STUDIES[:2] or ["none"])
def test_matches_her_pipeline_exactly(model, study, tmp_path):
    from triagelane_ct.pipeline import score_study_from_folder
    folder = DATA / study
    out = ct.score_upload([(f.name, f.read_bytes()) for f in sorted(folder.iterdir())],
                          FileBlob(tmp_path), f"t-{study}")
    ref = score_study_from_folder(str(folder), generate_localization=True)
    t, ev = out["triage"], out["evidence"]
    assert t["signal"] == ref["study_score"] and t["raw_score"] == ref["raw_score"]
    assert t["abstained"] == ref["abstain"]
    assert t["lane"] == ("ABSTAIN" if ref["abstain"] else ref["lane"].upper())
    assert t["driver"].lower() == ref["dominant_subtype"]
    assert ev["gradcam_slice_index"] == ref["localization"]["slice_index"]
    assert ev["gradcam_bbox"] == ref["localization"]["bounding_box"]


def test_heat_layer_is_the_heatmap_on_the_slice(model, tmp_path):
    folder = DATA / "ID_bd8ef2b128"
    if not folder.is_dir():
        pytest.skip(f"{folder.name} is not in {DATA.name}/")
    blob = FileBlob(tmp_path)
    out = ct.score_upload([(f.name, f.read_bytes()) for f in sorted(folder.iterdir())],
                          blob, "t-layer")
    ev = out["evidence"]
    layer = np.asarray(Image.open(blob._path(ev["gradcam_layer_png"])))
    assert layer.shape == (ev["frame_rows"], ev["frame_cols"], 4)
    alpha = layer[..., 3] > 0
    assert round(float(alpha.mean()), 4) == pytest.approx(ev["gradcam_coverage"], abs=1e-3)
    # alpha = 0.55 * heat * 255, so alpha >= 71 means heat > 0.5, the box's own
    # threshold: every such pixel must fall inside the box, in the same frame.
    box = ev["gradcam_bbox"]
    rows, cols = np.nonzero(layer[..., 3] >= 71)
    assert rows.size > 0
    assert rows.min() >= box["row_min"] and rows.max() <= box["row_max"]
    assert cols.min() >= box["col_min"] and cols.max() <= box["col_max"]
