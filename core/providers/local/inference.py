"""InProcessInference: runs the model in this process, dispatching on the
registry entry's output_type.

multilabel                  chest DenseNet (TorchXRayVision). The DICOM pixel
                            array is written to an in-memory PNG at its native
                            bit depth and handed to imaging.predict, so there is
                            still one preprocessing path.
segmentation-probability    brain SegResNet, through Shaurya's pipeline in
                            _external/brainmri (read only). Returns the
                            metrics.json dict it writes.

torch, torchxrayvision and MONAI are imported lazily: the rest of the platform
runs without them.

The chest path runs Grad-CAM for the driver finding in the SAME forward pass
that produces the 18 outputs, and writes the overlay through BlobPort. It is
not generated on click: that would mean reloading weights per request. Brain
studies get no Grad-CAM: the segmentation mask is its own explanation, and a
better one.

The brain path has not been executed on the build container: the SegResNet
checkpoint is a Git LFS object it cannot fetch.
"""
from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from core.ports import InferencePort
from core.types import StudyRef

ROOT = Path(__file__).resolve().parents[3]
BRAINMRI = ROOT / "_external" / "brainmri"


def _png_bytes(pixels: np.ndarray) -> bytes:
    from PIL import Image
    if pixels.dtype not in (np.uint8, np.uint16):
        raise ValueError(f"expected uint8 or uint16 pixels, got {pixels.dtype}")
    buf = io.BytesIO()
    Image.fromarray(pixels).save(buf, format="PNG")
    return buf.getvalue()


def _slug(name: str) -> str:
    return "".join(c.lower() if c.isalnum() else "_" for c in name)


class _DriverTarget:
    """Grad-CAM target that picks the driver from the very outputs it is given.

    pytorch_grad_cam calls the target on each model output after the forward
    pass, before the backward pass. The driver is chosen exactly as the
    pipeline will choose it later (adapters.multilabel then triage via
    core.registry.rank), so the heatmap explains the finding that set the lane.
    """

    def __init__(self, pathologies, model_cfg):
        self.pathologies, self.model_cfg = list(pathologies), model_cfg
        self.driver = None

    def __call__(self, output):
        from adapters import multilabel
        from core.registry import rank
        preds = {p: float(v) for p, v in zip(self.pathologies, output.detach().cpu())}
        self.driver = rank(multilabel.adapt(preds, {"entry": self.model_cfg}),
                           self.model_cfg)["driver"]
        return output[self.pathologies.index(self.driver)]


def render_gradcam(model_input: np.ndarray, heat: np.ndarray, driver: str) -> bytes:
    """The 224 px image the model saw, with the Grad-CAM heat over it, as PNG.

    model_input is the normalised tensor (roughly -1024..1024); heat is 0..1.
    Yellow to red only. Below 0.2 nothing is drawn, so faint noise does not
    read as a region.
    """
    from PIL import Image, ImageDraw
    grey = np.clip((model_input + 1024) / 2048 * 255, 0, 255)
    rgb = np.repeat(grey[..., None], 3, axis=2)
    colour = np.stack([np.full_like(heat, 255), 220 * (1 - heat), np.zeros_like(heat)], -1)
    alpha = np.where(heat < 0.2, 0.0, 0.55 * heat)[..., None]
    rgb = (1 - alpha) * rgb + alpha * colour
    pic = Image.fromarray(rgb.astype(np.uint8)).resize((448, 448), Image.BILINEAR)
    out = Image.new("RGB", (448, 448 + 48), (0, 0, 0))
    out.paste(pic, (0, 0))
    draw = ImageDraw.Draw(out)
    for i, line in enumerate(("NON-DIAGNOSTIC", f"Triage rationale: Grad-CAM for {driver}",
                              "A sanity check on the ordering, not a localisation")):
        draw.text((6, 452 + 14 * i), line, fill=(255, 255, 255))
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


def render_heat_layer(heat: np.ndarray) -> bytes:
    """The Grad-CAM heat alone, as a transparent 224 px RGBA PNG, same colours
    and threshold as render_gradcam. The viewer stretches it over
    crop_box(...) so it sits on the frame the radiologist is looking at."""
    from PIL import Image
    colour = np.stack([np.full_like(heat, 255), 220 * (1 - heat), np.zeros_like(heat)], -1)
    alpha = np.where(heat < 0.2, 0.0, 0.55 * heat)[..., None] * 255
    rgba = np.concatenate([colour, alpha], -1).clip(0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="PNG")
    return buf.getvalue()


def heat_coverage(heat: np.ndarray) -> float:
    """Fraction of the model's view the overlay draws on (heat at or above the
    0.2 display threshold). 0.0 means Grad-CAM found no supporting region for
    the finding at that threshold, which the viewer says in words rather than
    showing an empty layer."""
    return round(float((heat >= 0.2).mean()), 4)


def crop_box(rows: int, cols: int) -> list[int]:
    """[x, y, size] in frame pixels of the square the model saw.

    torchxrayvision.datasets.XRayCenterCrop (checked in the installed source):
    crop_size = min(y, x); startx = x // 2 - crop_size // 2, likewise starty.
    """
    size = min(rows, cols)
    return [cols // 2 - size // 2, rows // 2 - size // 2, size]


class InProcessInference(InferencePort):
    def __init__(self, blob=None):
        """blob: a BlobPort for the Grad-CAM overlay. Without one, chest
        inference returns outputs only."""
        self.blob = blob
        self._chest = None
        self._brain = None
        self.handlers = {
            "multilabel": self._multilabel,
            "segmentation-probability": self._segmentation,
        }

    def score(self, ref: StudyRef, model_cfg: dict[str, Any], **inputs) -> Any:
        kind = model_cfg["output_type"]
        if kind not in self.handlers:
            raise ValueError(f"no in-process handler for output_type {kind!r}")
        return self.handlers[kind](model_cfg, ref=ref, **inputs)

    def _multilabel(self, model_cfg, *, pixels: np.ndarray, ref=None, **_) -> dict[str, Any]:
        """-> {"preds": {pathology: raw sigmoid}, "evidence": {...}}.

        The image goes through imaging.to_model_input, the one preprocessing
        path. One forward pass gives the outputs; Grad-CAM for the driver
        finding reuses it. tests/test_gradcam.py checks the outputs equal
        imaging.predict's.
        """
        import imaging                          # pulls in torch; lazy on purpose
        if self._chest is None:
            import torchxrayvision as xrv
            self._chest = xrv.models.DenseNet(weights="densenet121-res224-all")
        model = self._chest
        # A file-like, as server.py passes: skimage.io.imread (0.26) rejects raw
        # bytes despite imaging.read_grayscale's docstring.
        x = imaging.to_model_input(io.BytesIO(_png_bytes(pixels)))
        if self.blob is None or ref is None:
            return {"preds": imaging.predict(model, io.BytesIO(_png_bytes(pixels))),
                    "evidence": {}}

        from pytorch_grad_cam import GradCAM
        target = _DriverTarget(model.pathologies, model_cfg)
        with GradCAM(model=model, target_layers=[model.features]) as cam:
            heat = cam(input_tensor=x, targets=[target])[0]
            out = cam.outputs[0].detach().cpu().numpy()
        preds = {p: float(v) for p, v in zip(model.pathologies, out)}
        stem = f"evidence/{ref.study_uid}/gradcam_{_slug(target.driver)}"
        self.blob.put(f"{stem}.png", render_gradcam(x[0, 0].numpy(), heat, target.driver))
        self.blob.put(f"{stem}_layer.png", render_heat_layer(heat))
        return {"preds": preds,
                "evidence": {"gradcam_png": f"{stem}.png",
                             "gradcam_layer_png": f"{stem}_layer.png",
                             "gradcam_box": crop_box(*pixels.shape[:2]),
                             "gradcam_finding": target.driver,
                             "gradcam_coverage": heat_coverage(heat)}}

    def _segmentation(self, model_cfg, *, nifti: dict[str, Path], **_) -> dict[str, Any]:
        """nifti: {"T1c", "T1", "T2", "FLAIR"} -> paths. Returns metrics.json.

        No Grad-CAM here, deliberately: the segmentation mask is its own
        explanation, and a better one than a saliency map. adapters/brats.py
        renders it as the evidence overlay.

        Never passes gt_path. Without a loadable model, Shaurya's pipeline
        substitutes the ground-truth mask for the prediction; with no gt_path it
        raises instead, which is what we want.
        """
        if self._brain is None:
            if str(BRAINMRI) not in sys.path:
                sys.path.insert(0, str(BRAINMRI))
            from backend.services.mri_pipeline import MRIPipeline
            self._brain = MRIPipeline()
            if not self._brain.load_model():
                raise RuntimeError("brain model checkpoint or MONAI unavailable")
        out = Path(tempfile.mkdtemp(prefix="auralane-seg-")) / "prediction.nii.gz"
        metrics = self._brain.run_inference(
            t1_path=nifti["T1"], t1ce_path=nifti["T1c"], t2_path=nifti["T2"],
            flair_path=nifti["FLAIR"], output_seg_path=out, gt_path=None)
        metrics["_prediction_path"] = str(out)
        return metrics
