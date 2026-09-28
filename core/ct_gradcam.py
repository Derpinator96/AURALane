"""Head CT Grad-CAM evidence, from Mehak's triagelane-ct (used as is).

Ported from Shaurya's core/ct_hemorrhage.py (notes branch): the same evidence
keys and images, written where the CT model runs (the SageMaker CT container on
AWS, the local process otherwise) instead of inside the API.

    ct_slice_png          the top-scoring slice, brain window, native size
    gradcam_layer_png     the heat alone, transparent RGBA, same size
    gradcam_heatmap_png   the heat in the jet colour map
    gradcam_overlay_png   slice, heat and the localization box
    gradcam_tri_view_png  the three side by side (her save_gradcam_visualization)
    gradcam_bbox          heat >= her localization threshold, in frame pixels

Grad-CAM runs on the slice her pipeline ranked highest, for its dominant
subtype. NON-DIAGNOSTIC; DECISION SUPPORT ONLY.
"""
from __future__ import annotations

import io
import logging
import threading
from typing import Any

import numpy as np

log = logging.getLogger("core.ct_gradcam")
# Grad-CAM registers hooks on the shared model: one study at a time.
_LOCK = threading.Lock()


def _label(name: str) -> str:
    return name[:1].upper() + name[1:]


def _png(pixels: np.ndarray) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(pixels).save(buf, format="PNG")
    return buf.getvalue()


def evidence(top: tuple, dominant: str, top_index: int, n_slices: int, study: str, blob) -> dict[str, Any]:
    """top: (pixels, slope, intercept) of the chosen slice. Writes the images
    through blob under evidence/<study>/ and returns the evidence fields."""
    from triagelane_ct import gradcam, preprocessing as pre
    from core.providers.local.inference import heat_coverage, render_heat_layer

    px, slope, intercept = top
    with _LOCK:
        cam = gradcam.compute_gradcam(px, slope, intercept,
                                      gradcam._dominant_subtype_class_index(dominant))
    heat = cam["heatmap"]
    brain = pre.apply_window(pre.to_hounsfield(px, slope, intercept), *gradcam.BRAIN_WINDOW)
    brain8 = np.clip(brain, 0, 255).astype(np.uint8) if brain.dtype != np.uint8 else brain
    stem = f"evidence/{study}"
    layer = f"{stem}/gradcam_{dominant}_layer.png"
    blob.put(f"{stem}/ct_slice.png", _png(brain8))
    blob.put(layer, render_heat_layer(heat))
    bbox = cam.get("bounding_box")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        jet = matplotlib.colormaps["jet"]
        blob.put(f"{stem}/gradcam_heatmap.png", _png((jet(heat)[..., :3] * 255).astype(np.uint8)))

        def box(ax):
            if bbox is not None:
                ax.add_patch(plt.Rectangle((bbox["col_min"], bbox["row_min"]),
                                           bbox["col_max"] - bbox["col_min"],
                                           bbox["row_max"] - bbox["row_min"],
                                           fill=False, edgecolor="lime", linewidth=2))

        fig, axes = plt.subplots(1, 3, figsize=(12, 4))
        axes[0].imshow(brain8, cmap="gray")
        axes[0].set_title("Original slice (brain window)", fontsize=11, pad=6)
        axes[1].imshow(heat, cmap="jet")
        axes[1].set_title(f"Grad-CAM: {dominant}", fontsize=11, pad=6)
        axes[2].imshow(brain8, cmap="gray")
        axes[2].imshow(heat, cmap="jet", alpha=0.45)
        box(axes[2])
        axes[2].set_title("Overlay + localized region", fontsize=11, pad=6)
        for ax in axes:
            ax.axis("off")
        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="PNG", dpi=150, bbox_inches="tight")
        plt.close(fig)
        blob.put(f"{stem}/gradcam_tri_view.png", buf.getvalue())

        fig2, ax = plt.subplots(figsize=(6, 6))
        ax.imshow(brain8, cmap="gray")
        ax.imshow(heat, cmap="jet", alpha=0.45)
        box(ax)
        ax.axis("off")
        fig2.subplots_adjust(left=0, right=1, top=1, bottom=0)
        buf = io.BytesIO()
        fig2.savefig(buf, format="PNG", dpi=150, bbox_inches="tight", pad_inches=0)
        plt.close(fig2)
        blob.put(f"{stem}/gradcam_overlay.png", buf.getvalue())
        panels = True
    except Exception as e:                      # the slice and heat layer are enough
        log.warning("Grad-CAM panels not drawn: %s", e)
        panels = False

    rows, cols = px.shape
    out = {
        "ct_slice_png": f"{stem}/ct_slice.png",
        "gradcam_layer_png": layer,
        "gradcam_finding": _label(dominant),
        "gradcam_coverage": heat_coverage(heat),
        "gradcam_bbox": bbox,
        "gradcam_centroid": cam.get("centroid"),
        "gradcam_threshold": gradcam.GRADCAM_LOCALIZATION_THRESHOLD,
        "gradcam_slice_index": top_index,
        "gradcam_target_layer": cam.get("target_layer_name"),
        "frame_rows": int(rows),
        "frame_cols": int(cols),
        "gradcam_note": (f"Computed on slice {top_index + 1} of {n_slices}, the one with the "
                         f"highest urgency-weighted score."),
    }
    if panels:
        out.update(gradcam_heatmap_png=f"{stem}/gradcam_heatmap.png",
                   gradcam_overlay_png=f"{stem}/gradcam_overlay.png",
                   gradcam_tri_view_png=f"{stem}/gradcam_tri_view.png")
    return out
