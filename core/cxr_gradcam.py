"""Chest Grad-CAM for each of the top findings, computed for the study.

The driver's Grad-CAM (core/providers/local/inference.py) explains the finding
that set the lane. A reader also wants to see where the model looked for the
next findings, so the top GRADCAM_FINDINGS findings by weighted value (signal x
urgency, the quantity triage ranks by) each get one, from the same normalised
input, using pytorch_grad_cam's GradCAM on model.features: the driver's heat is
reused, the others come from one batched forward and backward pass.

Rendering follows Shaurya's XRAY branch (commit 45b29d0): Gaussian blur of the
map (a 15 px kernel), min-max stretch, the JET colour map, and a blend with the
image at 0.45 image to 0.55 heat. Three PNGs per finding, under
evidence/<study>/gradcam/:

    <slug>_layer.png     the heat alone on a transparent background (RGBA, 224 px),
                         which the viewer pins over the frame at the model's crop box
    <slug>_heatmap.png   the JET heat map alone (RGB, 224 px)
    <slug>_blended.png   the model's input with the heat over it (RGB, 448 px)

It uses numpy and scipy only (no OpenCV), so the Lambda image needs nothing new.
NON-DIAGNOSTIC; DECISION SUPPORT ONLY.
"""
from __future__ import annotations

import io
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np

log = logging.getLogger("core.cxr_gradcam")

# The top findings that get a map (the driver is always among them). Measured on the
# development machine (4 CPU threads, torch 2.14): the driver's own map costs 1.1 s and
# each further finding about 0.9 s of batched Grad-CAM, so 5 findings added 3.9 s, over
# the 3 s budget, and 3 add 2.6 s. AURALANE_GRADCAM_FINDINGS overrides it; the Lambda
# records the time it took in evidence["gradcam_findings_seconds"].
GRADCAM_FINDINGS = int(os.environ.get("AURALANE_GRADCAM_FINDINGS", "3"))
# Kernel of Shaurya's cv2.GaussianBlur((15, 15), 0): sigma = 0.3 * ((15 - 1) / 2 - 1) + 0.8.
BLUR_SIGMA = 2.6
BLEND_IMAGE, BLEND_HEAT = 0.45, 0.55


def slug(name: str) -> str:
    return "".join(c.lower() if c.isalnum() else "_" for c in name)


def normalise(heat: np.ndarray) -> np.ndarray:
    """Blur, then stretch to 0..1 (an all-flat map stays 0)."""
    from scipy.ndimage import gaussian_filter
    blurred = gaussian_filter(heat.astype(np.float32), sigma=BLUR_SIGMA, truncate=7 / BLUR_SIGMA)
    lo, hi = float(blurred.min()), float(blurred.max())
    if hi - lo < 1e-8:
        return np.zeros_like(blurred)
    return (blurred - lo) / (hi - lo)


def jet(v: np.ndarray) -> np.ndarray:
    """The JET colour map for values 0..1 -> uint8 RGB, the piecewise linear map
    OpenCV's COLORMAP_JET and matplotlib's jet both use."""
    r = np.clip(1.5 - np.abs(4 * v - 3), 0, 1)
    g = np.clip(1.5 - np.abs(4 * v - 2), 0, 1)
    b = np.clip(1.5 - np.abs(4 * v - 1), 0, 1)
    return (np.stack([r, g, b], -1) * 255).astype(np.uint8)


def _png(arr: np.ndarray, mode: str) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(arr, mode).save(buf, format="PNG")
    return buf.getvalue()


def render_layer(norm: np.ndarray) -> bytes:
    """JET heat on a transparent background: cold regions are see-through."""
    alpha = np.clip((norm - 0.15) / 0.85, 0, 1) * 0.75 * 255
    return _png(np.concatenate([jet(norm), alpha[..., None].astype(np.uint8)], -1), "RGBA")


def render_heatmap(norm: np.ndarray) -> bytes:
    return _png(jet(norm), "RGB")


def render_blended(model_input: np.ndarray, norm: np.ndarray) -> bytes:
    """model_input: the normalised tensor as an array (roughly -1024..1024)."""
    from PIL import Image
    grey = np.clip((model_input + 1024) / 2048 * 255, 0, 255)
    disp = np.repeat(grey[..., None], 3, axis=2)
    blended = BLEND_IMAGE * disp + BLEND_HEAT * jet(norm)
    pic = Image.fromarray(blended.astype(np.uint8)).resize((448, 448), Image.BILINEAR)
    buf = io.BytesIO()
    pic.save(buf, format="PNG")
    return buf.getvalue()


def select(signals: dict[str, float], urgency: dict[str, float], driver: str,
           count: int = GRADCAM_FINDINGS) -> list[str]:
    """The findings that get a map: the top `count` by weighted value, the driver
    first and always included."""
    weighted = {k: signals[k] * urgency.get(k, 0.15) for k in signals}
    order = sorted(weighted, key=lambda k: -weighted[k])
    top = [driver] + [k for k in order if k != driver]
    return top[:count]


def compute(model, x, names: list[str], have: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Heat (224 x 224, 0..1) for each of `names`. `have` holds maps already
    computed (the driver's); the rest come from one batched Grad-CAM pass."""
    heats = {n: have[n] for n in names if n in have}
    todo = [n for n in names if n not in heats]
    if todo:
        from pytorch_grad_cam import GradCAM
        from pytorch_grad_cam.utils.model_targets import ClassifierOutputTarget
        idx = [list(model.pathologies).index(n) for n in todo]
        batch = x.repeat(len(todo), 1, 1, 1)
        with GradCAM(model=model, target_layers=[model.features]) as cam:
            out = cam(input_tensor=batch, targets=[ClassifierOutputTarget(i) for i in idx])
        heats.update({n: out[i] for i, n in enumerate(todo)})
    return heats


def coverage(norm: np.ndarray) -> float:
    """Fraction of the model's view where the stretched heat is at or above 0.5."""
    return round(float((norm >= 0.5).mean()), 4)


def per_finding(model, x, signals: dict[str, float], urgency: dict[str, float], driver: str,
                driver_heat: np.ndarray, blob, study: str,
                count: int | None = None) -> list[dict[str, Any]]:
    """Write the three images for each selected finding to blob; return the list
    the API hands the viewer (evidence["gradcam_findings"]), driver first."""
    started = time.perf_counter()
    names = select(signals, urgency, driver, count or GRADCAM_FINDINGS)
    heats = compute(model, x, names, {driver: driver_heat})
    model_input = x[0, 0].numpy()
    entries, uploads = [], []
    for n in names:
        norm = normalise(heats[n])
        stem = f"evidence/{study}/gradcam/{slug(n)}"
        uploads += [(f"{stem}_layer.png", render_layer(norm)),
                    (f"{stem}_heatmap.png", render_heatmap(norm)),
                    (f"{stem}_blended.png", render_blended(model_input, norm))]
        entries.append({"name": n, "slug": slug(n), "signal": round(signals[n], 3),
                        "urgency": urgency.get(n, 0.15),
                        "weighted": round(signals[n] * urgency.get(n, 0.15), 3),
                        "driver": n == driver, "coverage": coverage(norm),
                        "layer_png": f"{stem}_layer.png", "heatmap_png": f"{stem}_heatmap.png",
                        "blended_png": f"{stem}_blended.png"})
    with ThreadPoolExecutor(8) as pool:          # 15 small objects: not one at a time
        list(pool.map(lambda kv: blob.put(*kv), uploads))
    log.info("Grad-CAM for %d findings of %s in %.2f s", len(names), study, time.perf_counter() - started)
    return entries
