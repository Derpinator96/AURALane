"""Head CT hemorrhage triage with Grad-CAM, through Mehak's pipeline in
CT_Mehak/triagelane-ct (used as is, never edited here).

Her package decides the study: per-slice ViT scores, top-k aggregation, lane
and abstention (triagelane_ct.pipeline.score_study, configs/ct_pipeline.yaml).
This module only stages the upload, maps her result onto a worklist row, and
writes the Grad-CAM evidence through BlobPort:

    ct_slice_png        the top-scoring slice, brain window, native size
    gradcam_layer_png   the heat alone as transparent RGBA, same size, so the
                        viewer can lay it over ct_slice_png and toggle it
    gradcam_bbox        heat >= her localization threshold, in frame pixels

score_study discards the heatmap after reducing it to a box, so Grad-CAM runs
once more on the slice it chose. Same weights, same input, eval mode: the box
comes out identical (tests/test_ct_hemorrhage.py checks it).

torch and transformers are imported on the first CT study, not at startup.
"""
from __future__ import annotations

import io
import sys
import tempfile
import threading
import zipfile
from pathlib import Path
from typing import Any

import numpy as np

import triage
from core.providers.local.inference import heat_coverage, render_heat_layer

ROOT = Path(__file__).resolve().parents[1]
# The submodule when it is checked out, else the read-only clone the pipeline
# and the CT container use (same repository, same commit).
SRC = next((d for d in (ROOT / "CT_Mehak" / "triagelane-ct" / "src",
                        ROOT / "_external" / "triagelane-ct" / "src")
            if (d / "triagelane_ct").is_dir()), ROOT / "CT_Mehak" / "triagelane-ct" / "src")
MODEL_ID = "ct-ich-vit-rsna"
LANES = {"critical": "CRITICAL", "urgent": "URGENT", "expedited": "EXPEDITED",
         "routine": "ROUTINE"}
SLA = {name: (label, minutes) for name, _, label, minutes in triage.LANES}
MAX_SLICES = 1000
MAX_ZIP_BYTES = 1 << 30

# One study at a time: Grad-CAM registers hooks on the shared model, and two
# concurrent backward passes would read each other's activations.
_LOCK = threading.Lock()


class InvalidCTInput(ValueError):
    """The upload is not a CT study the model can read. Nothing was scored."""


def _ct():
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    from triagelane_ct import dicom_io, gradcam, model, pipeline, preprocessing
    return dicom_io, gradcam, model, pipeline, preprocessing


def _looks_dicom(name: str, data: bytes) -> bool:
    return (name.lower().endswith((".dcm", ".dicom"))
            or (len(data) > 132 and data[128:132] == b"DICM"))


def stage_upload(payloads: list[tuple[str, bytes]], dest: Path) -> int:
    """Writes the uploaded slices into dest as .dcm files: loose DICOM files,
    or the DICOM members of a .zip. Other files (Thumbs.db and the like from a
    picked folder) are skipped. Names are ours, so no zip member can write
    outside dest. Returns the number staged."""
    n = 0

    def put(name: str, data: bytes):
        nonlocal n
        if n >= MAX_SLICES:
            raise InvalidCTInput(f"more than {MAX_SLICES} slices in one study")
        stem = "".join(c if c.isalnum() or c in "._-" else "_" for c in Path(name).stem)
        (dest / f"{n:04d}_{stem}.dcm").write_bytes(data)
        n += 1

    for name, data in payloads:
        if name.lower().endswith(".zip"):
            try:
                zf = zipfile.ZipFile(io.BytesIO(data))
            except zipfile.BadZipFile as e:
                raise InvalidCTInput(f"{name} is not a readable zip") from e
            members = [m for m in zf.infolist() if not m.is_dir()]
            if sum(m.file_size for m in members) > MAX_ZIP_BYTES:
                raise InvalidCTInput(f"{name} unpacks to more than 1 GB")
            for m in members:
                inner = zf.read(m)
                if _looks_dicom(m.filename, inner):
                    put(Path(m.filename).name, inner)
        elif _looks_dicom(name, data):
            put(name, data)
    if n == 0:
        raise InvalidCTInput("no DICOM files in the upload")
    return n


def score_folder(folder: Path) -> dict[str, Any]:
    """Her pipeline on one staged study, plus the Grad-CAM heatmap it chose."""
    import pydicom
    from pydicom.errors import InvalidDicomError
    dicom_io, gradcam, model, pipeline, _ = _ct()
    try:
        paths = dicom_io.discover_study_dicom_paths(str(folder))
        slices = []
        for p in paths:
            dcm = pydicom.dcmread(p)
            slices.append((dicom_io.validate_dicom_slice(dcm), dcm.RescaleSlope,
                           dcm.RescaleIntercept))
    except (FileNotFoundError, dicom_io.InvalidDicomSliceError, InvalidDicomError) as e:
        raise InvalidCTInput(f"not a readable CT study: {e}") from e

    names = [Path(p).name.split("_", 1)[-1] for p in paths]
    with _LOCK:
        result = pipeline.score_study(slices, slice_ids=names, generate_localization=True)
        top = slices[result["localization"]["slice_index"]]
        cam = gradcam.compute_gradcam(
            *top, gradcam._dominant_subtype_class_index(result["dominant_subtype"]))
        probs = model.predict_slice(*top)["subtype_probs"]
    return {"result": result, "top": top, "cam": cam, "subtype_probs": probs,
            "threshold": gradcam.GRADCAM_LOCALIZATION_THRESHOLD,
            "urgency_weights": dict(model.URGENCY_WEIGHTS)}


def _label(name: str) -> str:
    return name[:1].upper() + name[1:]


def _png(pixels: np.ndarray) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(pixels).save(buf, format="PNG")
    return buf.getvalue()


def write_evidence(scored: dict, blob, study_uid: str) -> dict[str, Any]:
    pre = _ct()[4]
    r, cam = scored["result"], scored["cam"]
    loc = r["localization"]
    px, slope, intercept = scored["top"]
    brain = pre.apply_window(pre.to_hounsfield(px, slope, intercept), *pre.BRAIN_WINDOW)
    stem = f"evidence/{study_uid}"
    layer = f"{stem}/gradcam_{r['dominant_subtype']}_layer.png"
    blob.put(f"{stem}/ct_slice.png", _png(brain))
    blob.put(layer, render_heat_layer(cam["heatmap"]))

    heat = cam["heatmap"]
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        jet = matplotlib.colormaps["jet"]

        # 1. Jet Heatmap alone (Panel 2)
        heat_rgb = (jet(heat)[..., :3] * 255).astype(np.uint8)
        blob.put(f"{stem}/gradcam_heatmap.png", _png(heat_rgb))

        # 2. Tri-View 3-panel visualization (matching CT_Mehak save_gradcam_visualization)
        fig, axes = plt.subplots(1, 3, figsize=(12, 4))
        axes[0].imshow(brain, cmap="gray")
        axes[0].set_title("Original slice (brain window)", fontsize=11, pad=6)
        axes[0].axis("off")

        axes[1].imshow(heat, cmap="jet")
        axes[1].set_title(f"Grad-CAM: {r['dominant_subtype']}", fontsize=11, pad=6)
        axes[1].axis("off")

        axes[2].imshow(brain, cmap="gray")
        axes[2].imshow(heat, cmap="jet", alpha=0.45)
        bbox = cam.get("bounding_box")
        if bbox is not None:
            rect = plt.Rectangle(
                (bbox["col_min"], bbox["row_min"]),
                bbox["col_max"] - bbox["col_min"],
                bbox["row_max"] - bbox["row_min"],
                fill=False,
                edgecolor="lime",
                linewidth=2,
            )
            axes[2].add_patch(rect)
        axes[2].set_title("Overlay + localized region", fontsize=11, pad=6)
        axes[2].axis("off")
        fig.tight_layout()
        tri_buf = io.BytesIO()
        fig.savefig(tri_buf, format="PNG", dpi=150, bbox_inches="tight")
        plt.close(fig)
        blob.put(f"{stem}/gradcam_tri_view.png", tri_buf.getvalue())

        # 3. Overlay with lime box alone (Panel 3)
        fig2, ax = plt.subplots(figsize=(6, 6))
        ax.imshow(brain, cmap="gray")
        ax.imshow(heat, cmap="jet", alpha=0.45)
        if bbox is not None:
            rect2 = plt.Rectangle(
                (bbox["col_min"], bbox["row_min"]),
                bbox["col_max"] - bbox["col_min"],
                bbox["row_max"] - bbox["row_min"],
                fill=False,
                edgecolor="lime",
                linewidth=2,
            )
            ax.add_patch(rect2)
        ax.axis("off")
        fig2.subplots_adjust(left=0, right=1, top=1, bottom=0)
        overlay_buf = io.BytesIO()
        fig2.savefig(overlay_buf, format="PNG", dpi=150, bbox_inches="tight", pad_inches=0)
        plt.close(fig2)
        blob.put(f"{stem}/gradcam_overlay.png", overlay_buf.getvalue())
    except Exception as e:
        import logging
        logging.getLogger("core.ct").warning("Grad-CAM visualization generation exception: %s", e)

    rows, cols = px.shape
    return {
        "ct_slice_png": f"{stem}/ct_slice.png",
        "gradcam_layer_png": layer,
        "gradcam_heatmap_png": f"{stem}/gradcam_heatmap.png",
        "gradcam_overlay_png": f"{stem}/gradcam_overlay.png",
        "gradcam_tri_view_png": f"{stem}/gradcam_tri_view.png",
        "gradcam_finding": _label(r["dominant_subtype"]),
        "gradcam_coverage": heat_coverage(cam["heatmap"]),
        "gradcam_bbox": cam["bounding_box"],
        "gradcam_centroid": cam["centroid"],
        "gradcam_threshold": scored["threshold"],
        "gradcam_slice_index": loc["slice_index"],
        "gradcam_slice_id": loc["slice_id"],
        "gradcam_target_layer": cam["target_layer_name"],
        "frame_rows": int(rows),
        "frame_cols": int(cols),
        "gradcam_note": (f"Computed on slice {loc['slice_index'] + 1} of {r['n_slices']}, "
                         f"the one with the highest urgency-weighted score."),
    }


def triage_fields(scored: dict) -> tuple[str, dict[str, Any], dict[str, float]]:
    """(lane, triage, findings) for the worklist row. Lane and scores are hers,
    copied; acuity is her urgency-weighted study score on the 0-100 scale the
    worklist shows."""
    r, probs, weights = scored["result"], scored["subtype_probs"], scored["urgency_weights"]
    lane = "ABSTAIN" if r["abstain"] else LANES[r["lane"]]
    sla, minutes = SLA.get(lane, ("a human picks the lane", None))
    driver = r["dominant_subtype"]
    t = {
        "acuity": round(r["study_score"] * 100, 1),
        "lane": lane,
        "sla": sla,
        "sla_minutes": minutes,
        "abstained": bool(r["abstain"]),
        "driver": _label(driver),
        "confidence": round(probs[driver], 3),
        "signal": r["study_score"],
        "raw_score": r["raw_score"],
        "k_used": r["k_used"],
        "n_slices": r["n_slices"],
        "decision_reason": (r["decision_reason"] or "").strip(),
        "reason": (r["abstain_reason"] or "").strip() or None,
        "urgency_weights": {_label(k): v for k, v in weights.items()},
        "top_findings": [{"name": _label(k), "signal": round(v, 4), "urgency": weights[k]}
                         for k, v in sorted(probs.items(), key=lambda kv: -kv[1])],
    }
    findings = {_label(k): round(v, 4) for k, v in probs.items()}
    return lane, t, findings


def score_upload(payloads: list[tuple[str, bytes]], blob, study_uid: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="auralane-ct-") as tmp:
        stage_upload(payloads, Path(tmp))
        scored = score_folder(Path(tmp))
    lane, t, findings = triage_fields(scored)
    return {"lane": lane, "triage": t, "findings": findings,
            "evidence": write_evidence(scored, blob, study_uid),
            "n_slices": scored["result"]["n_slices"]}
