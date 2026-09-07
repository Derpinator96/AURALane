"""Modality router — dispatches studies to the correct AI adapter.

Routes incoming study data to CXR, CT, or MRI adapters based on metadata.
Each adapter returns a normalised InferenceResult that the common triage
engine consumes.
"""
from models.base import ModalityAdapter
from models.cxr import ChestXRayAdapter
from models.ct_head import HeadCTAdapter
from models.mri_brain import BrainMRIAdapter
from schemas import InferenceResult

# Singleton adapter instances — models are loaded lazily inside each
_adapters: dict[str, ModalityAdapter] = {}


def _get_adapter(modality: str) -> ModalityAdapter:
    """Return the adapter for the given modality, creating it on first use."""
    if modality not in _adapters:
        if modality == "CXR":
            _adapters[modality] = ChestXRayAdapter()
        elif modality == "CT":
            _adapters[modality] = HeadCTAdapter()
        elif modality == "MRI":
            _adapters[modality] = BrainMRIAdapter()
        else:
            raise ValueError(f"Unknown modality: {modality!r}")
    return _adapters[modality]


def route(modality: str, source=None, **kwargs) -> InferenceResult:
    """Run inference through the appropriate modality adapter.

    modality : "CXR" | "CT" | "MRI"
    source   : image file path, file-like, or bytes (for CXR live upload)
    **kwargs : passed to the adapter's infer() method (e.g. preset, seed)
    """
    adapter = _get_adapter(modality)
    return adapter.infer(source, **kwargs)


def warm(modality: str) -> float:
    """Pre-load model weights for the given modality. Returns seconds taken."""
    adapter = _get_adapter(modality)
    return adapter.warm()


def get_adapter_info(modality: str) -> dict:
    """Return metadata about the adapter for the given modality."""
    adapter = _get_adapter(modality)
    return {
        "modality": adapter.modality,
        "body_part": adapter.body_part,
        "model_name": adapter.model_name,
        "model_version": adapter.model_version,
        "status": adapter.status,
    }


def supported_modalities() -> list[str]:
    """Return list of supported modality codes."""
    return ["CXR", "CT", "MRI"]
