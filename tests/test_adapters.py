"""Adapter behaviour. The brain tests use one real case from Shaurya's repo
(_external/brainmri/data/studies/00000057: metrics.json, prediction.nii.gz and
the T1c input). Its Dice is not 1.0 on every channel, so the metrics are the
model's own output rather than the ground-truth substitute. No Dice figure is
quoted here: MRI-1790025179 records WT Dice 0.0 and is unexplained.
"""
import copy
import io
import json
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest
from PIL import Image

import triage
from adapters import brats
from core.providers.local import FileBlob
from core.registry import Registry, rank
from core.types import Findings

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "_external" / "brainmri" / "data" / "studies" / "00000057"
REG = Registry()
BRAIN = REG.get("brain-brats-monai-v0.5.4")


@pytest.fixture(scope="module")
def case():
    if not (CASE / "output" / "metrics.json").exists():
        pytest.fail(f"{CASE} missing; clone shauryajain111/brainmri into _external/brainmri")
    return (json.loads((CASE / "output" / "metrics.json").read_text()),
            nib.load(CASE / "input" / "t1ce.nii"),
            nib.load(CASE / "output" / "prediction.nii.gz"))


def _ctx(tmp_path, structural, prediction, study="1.2.3", **extra):
    return {"entry": BRAIN, "study": study, "structural": structural,
            "prediction": prediction, "blob": FileBlob(tmp_path), **extra}


def test_brats_findings_from_real_metrics(case, tmp_path):
    m, t1c, pred = case
    f = brats.adapt(m, _ctx(tmp_path, t1c, pred, study="case-57"))

    brain = float((np.asarray(t1c.dataobj) > 0).sum()) / 1000       # 1 mm isotropic
    burden = (m["wt_volume_cm3"] / brain - 0.005) / (0.10 - 0.005)
    ecc = abs(m["centroid_voxel"][0] - 120) / 120                    # L,P,S: axis 0 is L-R
    assert f.findings == pytest.approx({
        "enhancing_tumor": (m["et_volume_cm3"] - 0.5) / (40 - 0.5),
        "edema_volume": (m["wt_volume_cm3"] - m["tc_volume_cm3"] - 5) / (100 - 5),
        "tumor_burden": burden,
        "mass_effect": burden * (0.5 + 0.5 * ecc),
    })
    assert f.meta["brain_volume_cm3"] == pytest.approx(1480.2, abs=0.1)

    t = rank(f, BRAIN)
    assert t["lane"] in {"CRITICAL", "URGENT", "EXPEDITED", "ROUTINE", "ABSTAIN"}
    assert t["confidence"] is None and t["raw"] is None      # no fabricated confidence


def test_brats_overlay_png(case, tmp_path):
    m, t1c, pred = case
    ctx = _ctx(tmp_path, t1c, pred, study="case-57")
    f = brats.adapt(m, ctx)
    png = Image.open(io.BytesIO(ctx["blob"].get(f.evidence["overlay_png"])))
    assert png.size == (240, 240 + brats.CAPTION_PX)
    seg = np.asarray(pred.dataobj)
    areas = {z: (seg[:, :, z] > 0).sum() for z in range(m["slice_range"][0], m["slice_range"][1] + 1)}
    assert f.evidence["axial_index"] == max(areas, key=areas.get) == 75
    # Overlay pixels exist: red (ET) channel dominant somewhere in the image.
    arr = np.asarray(png.convert("RGB")).astype(int)
    assert ((arr[..., 0] - arr[..., 2]) > 80).sum() > 100


def test_empty_mask_abstains(case, tmp_path):
    m, t1c, pred = case
    empty = copy.deepcopy(m)
    for k in ("wt", "tc", "et"):
        empty[f"{k}_voxels"], empty[f"{k}_volume_mm3"], empty[f"{k}_volume_cm3"] = 0, 0.0, 0.0
    empty["bounding_box"], empty["centroid_voxel"], empty["slice_range"] = [0] * 6, [0.0] * 3, [0, 0]
    empty["dice_validation"] = None
    f = brats.adapt(empty, _ctx(tmp_path, t1c, pred))
    assert f.findings == {} and f.evidence == {}
    assert "min_tumor_ml" in f.meta["abstain_reason"]


def test_below_min_tumor_ml_abstains(case, tmp_path):
    m, t1c, pred = case
    small = copy.deepcopy(m)
    small["wt_volume_cm3"] = 0.99
    assert brats.adapt(small, _ctx(tmp_path, t1c, pred)).findings == {}


def test_ground_truth_metrics_refused(case, tmp_path):
    m, t1c, pred = case
    gt = copy.deepcopy(m)
    gt["dice_validation"] = {"WT_dice": 1.0, "TC_dice": 1.0, "ET_dice": 1.0}
    with pytest.raises(ValueError, match="ground-truth"):
        brats.adapt(gt, _ctx(tmp_path, t1c, pred))


def test_midline_axis_follows_orientation(tmp_path):
    """Left-right on axis 1 (P,L,S): eccentricity must read axis 1, not axis 0."""
    shape = (100, 200, 20)
    seg = np.zeros(shape, np.uint8)
    seg[40:60, 150:170, 5:15] = 4
    img = nib.Nifti1Image(np.ones(shape, np.int16), np.eye(4))
    m = {"wt_volume_cm3": 50.0, "tc_volume_cm3": 30.0, "et_volume_cm3": 10.0,
         "orientation": ["P", "L", "S"], "centroid_voxel": [50.0, 160.0, 10.0],
         "slice_range": [5, 14], "dice_validation": None}
    f = brats.adapt(m, _ctx(tmp_path, img, nib.Nifti1Image(seg, np.eye(4)),
                            brain_volume_cm3=1000.0))
    assert f.meta["lr_axis"] == 1
    assert f.meta["eccentricity"] == pytest.approx(60 / 100)   # |160 - 100| / 100, not |50 - 50| / 50


def test_multilabel_matches_triage_signal():
    ref = json.loads((ROOT / "reference.json").read_text())
    preds = {k: v["mean"] + 1.7 * v["sd"] for k, v in ref.items()}
    f = REG.adapter(REG.get("cxr-densenet-v1")).adapt(preds, {"entry": REG.get("cxr-densenet-v1")})
    assert f.findings == triage.signals(preds, ref)
    assert list(f.findings) == list(preds)


@pytest.mark.parametrize("codes", [("L", "P", "S"), ("R", "A", "S"), ("P", "L", "S"), ("A", "R", "I")])
def test_overlay_display_is_radiological(codes):
    """A marker at the patient's anterior-left lands top right, whatever the storage order."""
    lr = next(i for i, c in enumerate(codes) if c in "LR")
    ap = next(i for i, c in enumerate(codes) if c in "AP")
    idx = [0, 0, 0]
    idx[lr] = 9 if codes[lr] == "L" else 0         # far patient-left
    idx[ap] = 9 if codes[ap] == "A" else 0         # far anterior
    shape = [10, 10, 10]
    vol = np.zeros(shape + [3], np.uint8)
    si = next(i for i, c in enumerate(codes) if c in "SI")
    idx[si] = 0
    vol[tuple(idx)] = 255
    sl = np.take(vol, 0, axis=si)
    out = brats._radiological(sl, si, codes)
    assert out[0, 9, 0] == 255, codes              # row 0 = anterior, last column = patient left


# -- real metrics.json from Shaurya's pipeline --------------------------------
# Four distinct cases (several study folders are byte-identical copies of case
# 00000057). Two are L,P,S and two R,A,S, so the left-right axis is read from
# the orientation codes on real output in both conventions. Brain volume and
# the left-right width come from each case's own T1c input.

STUDIES = ROOT / "_external" / "brainmri" / "data" / "studies"
REAL_CASES = ["00000057", "MRI-1790025179", "MRI-1790070297", "MRI-1790081977"]


def _expected(m, brain, width):
    """The findings, written out independently of the adapter."""
    lr = [i for i, c in enumerate(m["orientation"]) if c in "LR"][0]
    clamp = lambda x: max(0.0, min(1.0, x))
    burden = clamp((m["wt_volume_cm3"] / brain - 0.005) / (0.10 - 0.005))
    ecc = min(1.0, abs(m["centroid_voxel"][lr] - width / 2) / (width / 2))
    return {
        "enhancing_tumor": clamp((m["et_volume_cm3"] - 0.5) / (40 - 0.5)),
        "edema_volume": clamp((m["wt_volume_cm3"] - m["tc_volume_cm3"] - 5) / (100 - 5)),
        "tumor_burden": burden,
        "mass_effect": burden * (0.5 + 0.5 * ecc),
    }


@pytest.mark.parametrize("case", REAL_CASES)
def test_findings_on_real_metrics(case):
    metrics = STUDIES / case / "output" / "metrics.json"
    if not metrics.exists():
        pytest.fail(f"{metrics} missing; clone shauryajain111/brainmri into _external/brainmri")
    m = json.loads(metrics.read_text())
    t1c = nib.load(next((STUDIES / case / "input").glob("t1ce.nii*")))
    lr = [i for i, c in enumerate(m["orientation"]) if c in "LR"][0]
    brain = float((np.asarray(t1c.dataobj) > 0).sum()) * float(np.prod(t1c.header.get_zooms()[:3])) / 1000

    findings, derived = brats.findings_from_metrics(m, BRAIN, brain, t1c.shape[lr])

    assert findings == pytest.approx(_expected(m, brain, t1c.shape[lr]))
    assert all(0.0 <= v <= 1.0 for v in findings.values())
    assert derived["lr_axis"] == lr == 0
    assert 900 < brain < 2000, f"{case}: brain volume {brain:.0f} cm3 is implausible"
    t = rank(Findings(findings), BRAIN)
    assert t["lane"] in {"CRITICAL", "URGENT", "EXPEDITED", "ROUTINE", "ABSTAIN"}


def test_real_cases_are_distinct_and_cover_both_orientations():
    metrics = [json.loads((STUDIES / c / "output" / "metrics.json").read_text()) for c in REAL_CASES]
    assert len({m["wt_volume_cm3"] for m in metrics}) == 4
    assert {tuple(m["orientation"]) for m in metrics} == {("L", "P", "S"), ("R", "A", "S")}


def test_volume_gate_abstains_on_zero_volume_dict():
    zero = {"wt_volume_cm3": 0.0, "tc_volume_cm3": 0.0, "et_volume_cm3": 0.0,
            "orientation": ["L", "P", "S"], "centroid_voxel": [0.0, 0.0, 0.0],
            "slice_range": [0, 0], "dice_validation": None}
    f = brats.adapt(zero, {"entry": BRAIN, "study": "zero"})
    assert f.findings == {} and f.evidence == {}
    assert "below min_tumor_ml" in f.meta["abstain_reason"]
