"""core.pipeline.ingest end to end on the local stack.

Chest: the real DenseNet, in process (needs torch and torchxrayvision).
Brain: RecordedInference replays the output Shaurya's pipeline recorded in
_external/brainmri/data/studies/00000057/output (its Dice is not 1.0 on every
channel, so it is not the ground-truth substitute). It stands in for the
SegResNet, which tests do not run: its checkpoint is a Git LFS object the build
container cannot fetch. Everything else
in the brain path runs for real: de-identification of 620 slices, STOW-RS,
DICOM to NIfTI, the adapter and its mask check, the overlay, triage, the
worklist row.

A replay is only the model's answer for the study it was recorded on. Neither
study in data/brain/dicom is that study: they are BraTS2021_00495 and
BraTS2021_00621, and no recorded case in _external/brainmri has either one's
input volumes. So the scoring test converts 00000057's own four input volumes to
DICOM with data/brain/nifti_to_dicom.py and ingests that, and a second test
replays the same output onto BraTS2021_00495 and requires the mask check
(core/mask_check.py) to refuse it.

Needs: docker compose -f docker-compose.local.yml up -d, Tesseract, both
corpora and _external/brainmri.
"""
import datetime
import importlib.util
import json
import random
import shutil
import sys
import uuid
from pathlib import Path

import nibabel as nib
import numpy as np
import pydicom
import pytest

from core import mask_check
from core.pipeline import ingest
from core.providers.aws._dynamodb import NO_STUDY
from core.providers.local import DynamoLocalTable, FileBlob, InProcessInference, OrthancDatastore
from core.registry import Registry
from core.types import Findings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sim" / "edge"))
sys.path.insert(0, str(ROOT / "sim" / "generator"))
import identity    # noqa: E402
import make_dicom  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "nifti_to_dicom", ROOT / "data" / "brain" / "nifti_to_dicom.py")
n2d = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(n2d)

pytestmark = pytest.mark.privacy
TESSERACT = shutil.which("tesseract") is not None
STEPS = ["deidentify", "blob_put", "import", "prepare_inputs", "infer", "adapt", "triage",
         "persist", "blob_delete"]
CASE57 = ROOT / "_external" / "brainmri" / "data" / "studies" / "00000057"


def _synthetic_chest(tmp_path):
    """One CR instance built by the generator, written to tmp_path. No corpus needed."""
    when = datetime.datetime(2026, 9, 25, 7, 0, 0)
    ident = make_dicom.make_identity(300, random.Random(5), when, False)
    y, x = np.mgrid[0:256, 0:256]
    ds = make_dicom.build_instance((40 + (x + y) * 0.3).astype(np.uint8), 255, ident, when,
                                   "synthetic")
    path = tmp_path / "study" / "cr.dcm"
    path.parent.mkdir()
    ds.save_as(path, enforce_file_format=True)
    return [path], {"study_uid": ident["study_uid"], "patient_id": ident["patient_id"]}


def _study_files(corpus, case=None):
    """The first study in the corpus manifest, or the one converted from case."""
    root = ROOT / "data" / corpus
    manifest = root / "manifest.json"
    if not manifest.exists():
        pytest.skip(f"needs the corpus at {root} (not in git). NOT VERIFIED: end-to-end "
                    f"ingest of a real {corpus.split('/')[0]} study through all nine steps")
    entries = json.loads(manifest.read_text())
    if case is not None:
        entries = [e for e in entries if e["case"] == case]
        assert entries, f"{case} is not in {manifest}"
    uid = entries[0]["study_uid"]
    return [root / e["path"] for e in entries if e["study_uid"] == uid], entries[0]


def _replay57():
    if not (CASE57 / "output" / "metrics.json").exists():
        pytest.fail(f"{CASE57} missing; clone shauryajain111/brainmri into _external/brainmri")
    return RecordedInference(json.loads((CASE57 / "output" / "metrics.json").read_text()),
                             CASE57 / "output" / "prediction.nii.gz")


def _study_from_case57(tmp_path):
    """00000057's four input volumes as a DICOM study, all 155 slices, written by
    the same converter as data/brain/dicom. Its seg input is the case's label,
    which the converter only copies beside the study; nothing here reads it."""
    case = tmp_path / "raw" / "CASE57"
    case.mkdir(parents=True)
    for part, name in [("t1ce", "t1ce"), ("t1", "t1"), ("t2", "t2"), ("flair", "flair"),
                       ("seg", "ground_truth")]:
        shutil.copyfile(CASE57 / "input" / f"{name}.nii", case / f"CASE57_{part}.nii")
    when = datetime.datetime(2026, 9, 25, 9, 0, 0)
    ident = make_dicom.make_identity(n2d.IDENTITY_OFFSET + 57, random.Random(7), when, False)
    entries = n2d.convert_case(case, tmp_path / "dicom", 1, ident, when, make_dicom)
    assert n2d.verify(entries, tmp_path / "dicom", raw=tmp_path / "raw") == []
    return [tmp_path / "dicom" / e["path"] for e in entries]


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


@pytest.mark.local_data
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


@pytest.mark.local_data
def test_brain_ingest_scores_with_overlay(ports, tmp_path):
    inf = _replay57()
    v = ingest(_study_from_case57(tmp_path), inference=inf, **ports)

    assert v.status == "SCORED", v.error
    assert v.model_id == "brain-brats-monai-v0.5.4"
    assert v.findings.meta["mask_check"]["passed"], v.findings.meta["mask_check"]
    assert v.lane in {"CRITICAL", "URGENT", "EXPEDITED", "ROUTINE"}
    assert v.triage["confidence"] is None

    # The pipeline built the four model inputs on the prediction's grid.
    pred = nib.load(CASE57 / "output" / "prediction.nii.gz")
    for ch in ("T1c", "T1", "T2", "FLAIR"):
        shape, affine = inf.seen[ch]
        assert shape == pred.shape and (abs(affine - pred.affine) < 1e-3).all(), ch

    key = v.findings.evidence["overlay_png"]
    assert ports["blob"].get(key)[:8] == b"\x89PNG\r\n\x1a\n"
    row = ports["table"].get_item("worklist", {"study": v.ref.study_uid})
    assert row["evidence"]["overlay_png"] == key
    steps, _ = _audit(ports["table"], v.ref.study_uid)
    assert steps == [(s, "ok") for s in STEPS]


@pytest.mark.local_data
def test_brain_mask_from_another_case_abstains(ports):
    """00000057's recorded mask replayed onto BraTS2021_00495: the pipeline runs
    every step, and the mask check refuses to score a segmentation recorded on
    another case's images. No lane, no overlay."""
    files, _ = _study_files("brain/dicom", case="BraTS2021_00495")
    v = ingest(files, inference=_replay57(), **ports)

    assert v.status == "SCORED", v.error
    assert v.lane == "ABSTAIN"
    check = v.findings.meta["mask_check"]
    assert not check["passed"] and "edema_flair" in check["failed"], check
    assert v.triage["reason"] == mask_check.reason(check)
    assert v.findings.findings == {} and "overlay_png" not in v.findings.evidence

    row = ports["table"].get_item("worklist", {"study": v.ref.study_uid})
    assert row["lane"] == "ABSTAIN" and row["evidence"] == {}
    steps, rows = _audit(ports["table"], v.ref.study_uid)
    assert steps == [(s, "ok") for s in STEPS]
    adapt = next(r for r in rows if r["action"] == "adapt")["detail"]
    assert adapt["mask_check_passed"] is False and adapt["mask_check_failed"] == check["failed"]


def test_ocr_unavailable_fails_visibly_before_anything_is_stored(ports, monkeypatch, tmp_path):
    import pytesseract

    def missing(*a, **k):
        raise pytesseract.TesseractNotFoundError()
    monkeypatch.setattr(pytesseract, "image_to_data", missing)

    files, source = _synthetic_chest(tmp_path)
    v = ingest(files, inference=InProcessInference(), **ports)

    assert v.status == "FAILED" and v.lane == "FAILED"
    assert "OCRUnavailable" in v.error
    rows = ports["table"].scan("worklist")
    assert len(rows) == 1 and rows[0]["status"] == "FAILED"
    assert rows[0]["study"].startswith("run:")       # no pseudonym was ever assigned
    steps, _ = _audit(ports["table"], NO_STUDY)       # events before any pseudonym exists
    assert steps == [("deidentify", "failed"), ("persist", "ok"), ("blob_delete", "ok")]
    assert ports["datastore"].search(study_uid=source["study_uid"]) == []   # never imported
    assert not list(ports["blob"].root.rglob("*.dcm"))


@pytest.mark.skipif(not TESSERACT, reason=(
    "needs Tesseract: de-identification masks pixels before the step under test. "
    "NOT VERIFIED: that an inference failure leaves a FAILED worklist row and a full audit"))
def test_inference_failure_leaves_a_failed_row(ports, tmp_path):
    class Broken:
        def score(self, *a, **k):
            raise RuntimeError("model endpoint unreachable")

    files, _ = _synthetic_chest(tmp_path)
    v = ingest(files, inference=Broken(), **ports)
    assert v.status == "FAILED" and "unreachable" in v.error
    row = ports["table"].get_item("worklist", {"study": v.ref.study_uid})
    assert row["status"] == "FAILED" and row["lane"] == "FAILED"
    steps, rows = _audit(ports["table"], v.ref.study_uid)
    assert steps == [("deidentify", "ok"), ("blob_put", "ok"), ("import", "ok"),
                     ("prepare_inputs", "ok"), ("infer", "failed"), ("persist", "ok"),
                     ("blob_delete", "ok")]
    assert "unreachable" in rows[4]["detail"]["error"]


@pytest.mark.skipif(not TESSERACT, reason=(
    "needs Tesseract: de-identification masks pixels before the step under test. "
    "NOT VERIFIED: that an adapter with no findings puts the study in ABSTAIN"))
def test_empty_findings_abstain_rather_than_score(ports, monkeypatch, tmp_path):
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

    files, _ = _synthetic_chest(tmp_path)
    v = ingest(files, inference=Fixed(), **ports)
    assert v.status == "SCORED" and v.lane == "ABSTAIN"
    assert v.triage["reason"] == "below volume gate"
