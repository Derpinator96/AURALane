"""core.pipeline.ingest end to end on the local stack.

Chest: the real DenseNet, in process (needs torch and torchxrayvision).
Brain: RecordedInference replays the output Shaurya's pipeline recorded for
BraTS case 00057 (_external/brainmri/data/studies/00000057/output, Dice
0.92 / 0.98 / 0.94 against ground truth, so it is model output). The brain
study under data/brain/dicom was converted from that same case's inputs, so the
replay is the model's answer for this study. It stands in for the SegResNet
checkpoint, which this build machine cannot download. Everything else in the
brain path runs for real: de-identification of 620 slices, STOW-RS, DICOM to
NIfTI, the adapter, the overlay, triage, the worklist row.

Needs: docker compose -f docker-compose.local.yml up -d, and both corpora.
"""
import json
import sys
import uuid
from pathlib import Path

import nibabel as nib
import pydicom
import pytest

from core.pipeline import ingest
from core.providers.aws._dynamodb import NO_STUDY
from core.providers.local import DynamoLocalTable, FileBlob, InProcessInference, OrthancDatastore
from core.registry import Registry
from core.types import Findings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sim" / "edge"))
import identity  # noqa: E402

STEPS = ["deidentify", "blob_put", "import", "infer", "adapt", "triage", "persist",
         "blob_delete"]
CASE57 = ROOT / "_external" / "brainmri" / "data" / "studies" / "00000057" / "output"


def _study_files(corpus):
    root = ROOT / "data" / corpus
    manifest = root / "manifest.json"
    if not manifest.exists():
        pytest.fail(f"{manifest} missing; build the corpus first")
    entries = json.loads(manifest.read_text())
    uid = entries[0]["study_uid"]
    return [root / e["path"] for e in entries if e["study_uid"] == uid], entries[0]


@pytest.fixture
def ports(tmp_path):
    table = DynamoLocalTable(prefix=f"test-{uuid.uuid4().hex[:8]}")
    return {"blob": FileBlob(tmp_path / "blob"), "datastore": OrthancDatastore(),
            "table": table, "registry": Registry(),
            "identity": identity.IdentityMap(str(tmp_path / "identity.db"))}


def _audit(table, study):
    rows = sorted(table.query("audit", study=study), key=lambda r: r["event_id"])
    return [(r["action"], r["outcome"]) for r in rows], rows


class RecordedInference:
    """Replays recorded segmentation output. Test double, never a provider."""

    def __init__(self, metrics: dict, prediction: Path):
        self.metrics, self.prediction = metrics, prediction
        self.seen = None

    def score(self, ref, model_cfg, **inputs):
        # Grids recorded now: the pipeline deletes its working files afterwards.
        self.seen = {ch: nib.load(path) for ch, path in inputs["nifti"].items()}
        self.seen = {ch: (img.shape, img.affine.copy()) for ch, img in self.seen.items()}
        return {**self.metrics, "_prediction_path": str(self.prediction)}


def test_chest_ingest_scores_and_audits_every_step(ports):
    files, source = _study_files("chest/studies")
    v = ingest(files, inference=InProcessInference(), **ports)

    assert v.status == "SCORED", v.error
    assert v.lane in {"CRITICAL", "URGENT", "EXPEDITED", "ROUTINE", "ABSTAIN"}
    study = v.ref.study_uid
    assert study != source["study_uid"], "StudyInstanceUID was not remapped"

    row = ports["table"].get_item("worklist", {"study": study})
    assert row["lane"] == v.lane and row["status"] == "SCORED"
    assert row["triage"]["acuity"] == v.triage["acuity"]

    steps, rows = _audit(ports["table"], study)
    assert steps == [(s, "ok") for s in STEPS]
    assert all(r["duration_ms"] > 0 for r in rows)
    assert len({r["detail"]["run_id"] for r in rows}) == 1

    # What the datastore indexed is the pseudonym, never the original.
    assert ports["datastore"].get_metadata(v.ref).patient_id != source["patient_id"]
    assert not list((ports["blob"].root / "transient").rglob("*.dcm"))


def test_brain_ingest_scores_with_overlay(ports):
    if not (CASE57 / "metrics.json").exists():
        pytest.fail(f"{CASE57} missing; clone shauryajain111/brainmri into _external/brainmri")
    files, _ = _study_files("brain/dicom")
    inf = RecordedInference(json.loads((CASE57 / "metrics.json").read_text()),
                            CASE57 / "prediction.nii.gz")
    v = ingest(files, inference=inf, **ports)

    assert v.status == "SCORED", v.error
    assert v.model_id == "brain-brats-monai-v0.5.4"
    assert v.lane in {"CRITICAL", "URGENT", "EXPEDITED", "ROUTINE", "ABSTAIN"}
    assert v.triage["confidence"] is None

    # The pipeline built the four model inputs on the prediction's grid.
    pred = nib.load(CASE57 / "prediction.nii.gz")
    for ch in ("T1c", "T1", "T2", "FLAIR"):
        shape, affine = inf.seen[ch]
        assert shape == pred.shape and (abs(affine - pred.affine) < 1e-3).all(), ch

    key = v.findings.evidence["overlay_png"]
    assert ports["blob"].get(key)[:8] == b"\x89PNG\r\n\x1a\n"
    row = ports["table"].get_item("worklist", {"study": v.ref.study_uid})
    assert row["evidence"]["overlay_png"] == key
    steps, _ = _audit(ports["table"], v.ref.study_uid)
    assert steps == [(s, "ok") for s in STEPS]


def test_ocr_unavailable_fails_visibly_before_anything_is_stored(ports, monkeypatch):
    import pytesseract

    def missing(*a, **k):
        raise pytesseract.TesseractNotFoundError()
    monkeypatch.setattr(pytesseract, "image_to_data", missing)

    files, source = _study_files("chest/studies")
    before = ports["datastore"].search(study_uid=source["study_uid"])
    v = ingest(files, inference=InProcessInference(), **ports)

    assert v.status == "FAILED" and v.lane == "FAILED"
    assert "OCRUnavailable" in v.error
    rows = ports["table"].scan("worklist")
    assert len(rows) == 1 and rows[0]["status"] == "FAILED"
    assert rows[0]["study"].startswith("run:")       # no pseudonym was ever assigned
    steps, _ = _audit(ports["table"], NO_STUDY)       # events before any pseudonym exists
    assert steps == [("deidentify", "failed"), ("persist", "ok"), ("blob_delete", "ok")]
    assert ports["datastore"].search(study_uid=source["study_uid"]) == before
    assert not list(ports["blob"].root.rglob("*.dcm"))


def test_inference_failure_leaves_a_failed_row(ports):
    class Broken:
        def score(self, *a, **k):
            raise RuntimeError("model endpoint unreachable")

    files, _ = _study_files("chest/studies")
    v = ingest(files, inference=Broken(), **ports)
    assert v.status == "FAILED" and "unreachable" in v.error
    row = ports["table"].get_item("worklist", {"study": v.ref.study_uid})
    assert row["status"] == "FAILED" and row["lane"] == "FAILED"
    steps, rows = _audit(ports["table"], v.ref.study_uid)
    assert steps == [("deidentify", "ok"), ("blob_put", "ok"), ("import", "ok"),
                     ("infer", "failed"), ("persist", "ok"), ("blob_delete", "ok")]
    assert "unreachable" in rows[3]["detail"]["error"]


def test_empty_findings_abstain_rather_than_score(ports, monkeypatch):
    """An adapter that abstains (e.g. the brain volume gate) yields lane ABSTAIN."""
    reg = ports["registry"]
    entry = reg.for_modality("CR")

    class Abstaining:
        @staticmethod
        def adapt(raw, ctx):
            return Findings({}, meta={"abstain_reason": "below volume gate"})
    monkeypatch.setitem(reg.adapters, entry["id"], Abstaining)

    class Fixed:
        def score(self, *a, **k):
            return {}

    files, _ = _study_files("chest/studies")
    v = ingest(files, inference=Fixed(), **ports)
    assert v.status == "SCORED" and v.lane == "ABSTAIN"
    assert v.triage["reason"] == "below volume gate"
