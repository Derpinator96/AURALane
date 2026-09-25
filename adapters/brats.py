"""Brain adapter: Shaurya's BraTS segmentation metrics -> triage findings.

Model: MONAI brats_mri_segmentation bundle 0.5.4 (SegResNet). Its output is three
overlapping probability channels, not a label map (checked against the bundle's
configs/metadata.json):

    0 = TC tumour core    1 = WT whole tumour    2 = ET enhancing tumour

Labels 1/2/4 are the ground-truth convention only. Edema is not a channel:
edema = WT minus TC.

This adapter reads the metrics.json his pipeline writes
(_external/brainmri/backend/services/mri_pipeline.py). It performs no
volumetry of its own.

Signals use clinically anchored floors and ceilings from the registry entry,
never corpus z-scores: BraTS contains only positive cases, so "typical for the
corpus" means nothing. The model has never seen a normal brain and will
produce a mask on one, so below min_tumor_ml the study abstains (empty
findings) instead of scoring an invented lesion.

mass_effect is a proxy, not midline shift. True midline shift needs the
ventricles segmented, and BraTS does not label them. The finding is named for
what it measures.

WHY HIS POLICY ENGINE IS NOT PORTED. backend/services/mri_policy.py scores
wt_cm3 * 0.5 + et_cm3 * 1.2 + max_prob * 20. Do not re-add it:
  - max_prob is the maximum over the whole volume, so it is 1.0 for any study
    with a tumour and discriminates between nothing
  - the volume terms are unbounded and linear then clamped at 100, so a
    mid-size tumour already scores 88 and most cases would land CRITICAL
  - there is no abstention

NOT A DIAGNOSTIC DEVICE.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np

from core.types import Findings

FINDINGS = ("mass_effect", "enhancing_tumor", "tumor_burden", "edema_volume")

# Per channel overlay colour and opacity. Edema (WT minus TC) is drawn first so
# the core and the enhancing rim sit on top of it.
OVERLAY = (("edema", (255, 214, 0), 0.35),       # yellow
           ("tc", (255, 120, 0), 0.45),          # orange
           ("et", (220, 20, 20), 0.55))          # red

_brain_cm3: dict[str, float] = {}               # per-study cache, keyed by study UID


def finding_names(entry: dict) -> list[str]:
    return list(FINDINGS)


def _anchor(x: float, lo: float, hi: float) -> float:
    return max(0.0, min(1.0, (x - lo) / (hi - lo)))


def _axis(orientation, codes) -> int:
    for i, c in enumerate(orientation):
        if c in codes:
            return i
    raise ValueError(f"orientation {orientation} has no axis among {codes}")


def brain_volume_cm3(study: str, structural) -> float:
    """Voxels > 0 in a skull-stripped structural volume, times voxel volume.

    Counted from the image rather than derived from affine and shape: affine
    times shape gives the field of view (240 x 240 x 155 mm, about 8,900 cm3),
    not the brain. Valid because BraTS volumes are skull stripped, so every
    non-zero voxel is inside the head. Not valid for a scan that is not.
    Cached per study: the count is the same for every call on one study.
    """
    if study not in _brain_cm3:
        data = np.asarray(structural.dataobj)
        voxel_mm3 = float(np.prod(structural.header.get_zooms()[:3]))
        _brain_cm3[study] = float((data > 0).sum()) * voxel_mm3 / 1000.0
    return _brain_cm3[study]


def _from_ground_truth(metrics: dict) -> bool:
    """His pipeline substitutes the ground-truth mask when the model cannot run,
    and writes the same metrics.json. Perfect Dice on all three channels is the
    only trace that leaves."""
    dice = metrics.get("dice_validation") or {}
    return all(dice.get(k) == 1.0 for k in ("WT_dice", "TC_dice", "ET_dice"))


CAPTION_PX = 48


def _radiological(slice_rgb: np.ndarray, axial: int, orientation) -> np.ndarray:
    """Axial slice (two in-plane axes, then RGB) -> anterior at the top, patient
    left on image right. Read from the orientation codes, not assumed."""
    plane = [i for i in range(3) if i != axial]
    codes = [orientation[i] for i in plane]
    ap = next(k for k, c in enumerate(codes) if c in "AP")
    if ap == 1:                                   # rows must be the A-P axis
        slice_rgb = slice_rgb.transpose(1, 0, 2)
        codes = codes[::-1]
    if codes[0] == "A":                           # index grows anterior: flip so anterior is row 0
        slice_rgb = slice_rgb[::-1]
    if codes[1] == "R":                           # index grows to patient right: flip
        slice_rgb = slice_rgb[:, ::-1]
    return np.ascontiguousarray(slice_rgb)


def render_overlay(structural, prediction, orientation, slice_range) -> tuple[bytes, int]:
    """PNG of the axial slice with the largest tumour cross-section, mask overlaid."""
    from PIL import Image, ImageDraw

    seg = np.asarray(prediction.dataobj).astype(np.uint8)
    img = np.asarray(structural.dataobj).astype(np.float32)
    ax = _axis(orientation, "SI")
    lo, hi = slice_range
    areas = [(np.take(seg, z, axis=ax) > 0).sum() for z in range(lo, hi + 1)]
    z = lo + int(np.argmax(areas))

    s = np.take(img, z, axis=ax)
    lab = np.take(seg, z, axis=ax)
    top = np.percentile(s[s > 0], 99.5) if (s > 0).any() else 1.0
    grey = np.clip(s / top * 255, 0, 255)
    rgb = np.repeat(grey[..., None], 3, axis=2)

    masks = {"edema": lab == 2, "tc": np.isin(lab, (1, 4)), "et": lab == 4}
    for name, colour, alpha in OVERLAY:
        m = masks[name]
        rgb[m] = (1 - alpha) * rgb[m] + alpha * np.array(colour, np.float32)

    pic = Image.fromarray(_radiological(rgb.astype(np.uint8), ax, orientation))
    caption = Image.new("RGB", (pic.width, CAPTION_PX), (0, 0, 0))
    draw = ImageDraw.Draw(caption)
    for i, line in enumerate(("NON-DIAGNOSTIC", f"Axial {z}, largest tumour area",
                              "Patient left on image right")):
        draw.text((6, 4 + 14 * i), line, fill=(255, 255, 255))
    out = Image.new("RGB", (pic.width, pic.height + caption.height))
    out.paste(pic, (0, 0))
    out.paste(caption, (0, pic.height))
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue(), z


def resolve_channels(series, entry: dict) -> dict[str, Any]:
    """{model channel: series} from the de-identified sequence token. Never guesses.

    series: SeriesMeta-like objects with .description and .number, after
    de-identification. deid.py keeps an MR SeriesDescription only when the whole
    description is a known sequence name, rewritten to the canonical token
    (T1C, T1, T2, FLAIR); everything else reads as the dummy.

    Every model channel must be matched by exactly one series. Otherwise this
    raises, naming what was unresolved. There is no fallback to SeriesNumber:
    scanners number series by acquisition order, and scrambled channels give a
    confident, wrong segmentation with no error. Refusing is a visible failure;
    guessing is an invisible one.
    """
    channels = entry["input"]["channels"]
    wanted = {c.upper(): c for c in channels}
    found: dict[str, list] = {c: [] for c in channels}
    unmatched = []
    for s in series:
        channel = wanted.get(str(s.description).upper())
        (found[channel] if channel else unmatched).append(s)

    missing = [c for c in channels if not found[c]]
    doubled = {c: [x.number for x in found[c]] for c in channels if len(found[c]) > 1}
    if missing or doubled:
        parts = []
        if missing:
            parts.append(f"no series identified as {', '.join(missing)}")
        if doubled:
            parts.append("more than one series for " + ", ".join(
                f"{c} (series {n})" for c, n in doubled.items()))
        if unmatched:
            parts.append("unrecognised series: " + ", ".join(
                f"{x.number} {x.description!r}" for x in unmatched))
        raise ValueError(f"cannot identify the {entry['id']} input channels: "
                         + "; ".join(parts) + ". Refusing to guess the order.")
    return {c: found[c][0] for c in channels}


def findings_from_metrics(m: dict, entry: dict, brain_cm3: float,
                          lr_width: int) -> tuple[dict[str, float], dict[str, Any]]:
    """The findings arithmetic alone, on one metrics.json.

    brain_cm3: brain volume. lr_width: voxels along the left-right axis, the one
    the orientation codes name. Returns (findings, derived values for meta).
    """
    wt, tc, et = m["wt_volume_cm3"], m["tc_volume_cm3"], m["et_volume_cm3"]
    a = entry["anchors"]
    burden = _anchor(wt / brain_cm3, *a["tumor_burden"])

    # Off-midline eccentricity along the left-right axis, found from the
    # orientation codes, never assumed to be index 0. Assumes the volume is
    # centred on the head's midline, which holds for BraTS (registered to the
    # SRI24 atlas) and not for an arbitrary acquisition.
    lr = _axis(m["orientation"], "LR")
    ecc = min(1.0, abs(m["centroid_voxel"][lr] - lr_width / 2) / (lr_width / 2))

    # Combination rule is our choice and clinically unvalidated: volume carries
    # the signal, eccentricity scales it from half (central lesion) to full
    # (lesion at the edge of the volume). A small lateral lesion stays small.
    mass_effect = burden * (0.5 + 0.5 * ecc)

    findings = {
        "mass_effect": mass_effect,
        "enhancing_tumor": _anchor(et, *a["enhancing_tumor"]),
        "tumor_burden": burden,
        "edema_volume": _anchor(wt - tc, *a["edema_volume"]),
    }
    derived = {"brain_volume_cm3": round(brain_cm3, 1), "wt_fraction": wt / brain_cm3,
               "edema_cm3": round(wt - tc, 2), "eccentricity": ecc, "lr_axis": lr}
    return findings, derived


def adapt(model_output: dict[str, Any], context: dict[str, Any]) -> Findings:
    """model_output: metrics.json as a dict.

    context: entry (registry entry), study (StudyInstanceUID), structural (T1c,
    nibabel image), prediction (his label-map NIfTI, nibabel image), blob (a
    BlobPort, receives the overlay PNG). brain_volume_cm3 may be supplied to
    skip the count. From the pipeline, structural and prediction are absent and
    are loaded from inputs["nifti"]["T1c"] and model_output["_prediction_path"].
    A scored brain study always carries its overlay.
    """
    m, entry = model_output, context["entry"]
    study = context["study"]
    meta = {"model_id": entry["id"], "metrics": m}

    if _from_ground_truth(m):
        raise ValueError("metrics.json has Dice 1.0 on every channel: it was computed "
                         "from the ground-truth mask, not the model. Refusing to score.")

    wt, tc, et = m["wt_volume_cm3"], m["tc_volume_cm3"], m["et_volume_cm3"]
    if wt < entry["min_tumor_ml"]:                         # 1 cm3 = 1 ml
        meta["abstain_reason"] = (f"whole tumour {wt} ml is below min_tumor_ml "
                                  f"{entry['min_tumor_ml']}; the model is trained on "
                                  f"positives only and is not trusted to call this")
        return Findings(findings={}, evidence={}, meta=meta)

    # The pipeline passes paths; tests may pass loaded images.
    if context.get("structural") is None:
        context["structural"] = nib.load(context["inputs"]["nifti"]["T1c"])
    if context.get("prediction") is None:
        context["prediction"] = nib.load(m["_prediction_path"])

    brain = context.get("brain_volume_cm3") or brain_volume_cm3(study, context["structural"])
    lr = _axis(m["orientation"], "LR")
    findings, derived = findings_from_metrics(m, entry, brain, context["structural"].shape[lr])
    meta.update(derived)

    png, z = render_overlay(context["structural"], context["prediction"],
                            m["orientation"], m["slice_range"])
    key = f"evidence/{study}/segmentation_overlay.png"
    context["blob"].put(key, png)
    evidence = {"overlay_png": key, "axial_index": z,
                "channels": {"edema": "yellow", "tc": "orange", "et": "red"}}
    return Findings(findings=findings, evidence=evidence, meta=meta)
