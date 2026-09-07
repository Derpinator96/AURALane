"""Chest X-ray adapter — wraps the existing TorchXRayVision DenseNet pipeline.

This adapter delegates entirely to the existing imaging.py module, which is
NOT modified. The model loading pattern mirrors server.py's lazy get_model().
"""
import time
from models.base import ModalityAdapter
from schemas import InferenceResult, Finding


class ChestXRayAdapter(ModalityAdapter):
    """LIVE adapter — real TorchXRayVision DenseNet inference."""

    def __init__(self):
        self._model = None
        self._pathologies = None

    @property
    def modality(self) -> str:
        return "CXR"

    @property
    def body_part(self) -> str:
        return "CHEST"

    @property
    def model_name(self) -> str:
        return "densenet121-res224-all"

    @property
    def model_version(self) -> str:
        return "torchxrayvision-1.5"

    @property
    def status(self) -> str:
        return "LIVE"

    def _ensure_model(self):
        if self._model is None:
            import torchxrayvision as xrv
            self._model = xrv.models.DenseNet(weights="densenet121-res224-all")
            self._model.eval()
            self._pathologies = self._model.pathologies

    def warm(self) -> float:
        t = time.time()
        self._ensure_model()
        return round(time.time() - t, 2)

    def infer(self, source) -> InferenceResult:
        """Run TorchXRayVision on a chest X-ray image.

        source : file path, file-like object, or bytes
        """
        import imaging  # lazy import — keeps torch off the import path

        self._ensure_model()
        t0 = time.time()
        preds = imaging.predict(self._model, source)
        inference_ms = round((time.time() - t0) * 1000)

        findings = [
            Finding(name=name, raw_probability=prob)
            for name, prob in preds.items()
        ]

        return InferenceResult(
            study_id="",  # caller fills this in
            modality=self.modality,
            body_part=self.body_part,
            model_name=self.model_name,
            model_version=self.model_version,
            findings=findings,
            status=self.status,
            inference_ms=inference_ms,
        )
