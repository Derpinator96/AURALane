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

UNVERIFIED in this build: neither model path has been executed here, because
the build container cannot reach download.pytorch.org. The dispatch itself is
tested with stand-in handlers.
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


class InProcessInference(InferencePort):
    def __init__(self):
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
        return self.handlers[kind](model_cfg, **inputs)

    def _multilabel(self, model_cfg, *, pixels: np.ndarray, **_) -> dict[str, float]:
        """-> {pathology: raw sigmoid}, the same dict prepare.py scores."""
        import imaging                          # pulls in torch; lazy on purpose
        if self._chest is None:
            import torchxrayvision as xrv
            self._chest = xrv.models.DenseNet(weights="densenet121-res224-all")
        # A file-like, as server.py passes: skimage.io.imread (0.26) rejects raw
        # bytes despite imaging.read_grayscale's docstring.
        return imaging.predict(self._chest, io.BytesIO(_png_bytes(pixels)))

    def _segmentation(self, model_cfg, *, nifti: dict[str, Path], **_) -> dict[str, Any]:
        """nifti: {"T1c", "T1", "T2", "FLAIR"} -> paths. Returns metrics.json.

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
