"""The brain path refuses to run without monai instead of degrading.

_external/brainmri's mri_pipeline swallows a failed monai import and sets
SegResNet to None. These tests simulate both ways that can happen and assert
our provider raises, naming monai, before any model is built.
"""
import sys
import types

import pytest

from core.providers.local import inference
from core.providers.local.inference import InProcessInference, MissingDependency, require_monai
from core.types import StudyRef

ENTRY = {"output_type": "segmentation-probability"}
NIFTI = {k: "unused.nii.gz" for k in ("T1c", "T1", "T2", "FLAIR")}


def _block_monai(monkeypatch):
    # A None entry in sys.modules makes `import monai...` raise ImportError.
    for name in ("monai", "monai.networks", "monai.networks.nets", "monai.inferers"):
        monkeypatch.setitem(sys.modules, name, None)


def test_require_monai_raises_naming_monai(monkeypatch):
    _block_monai(monkeypatch)
    with pytest.raises(MissingDependency, match="monai"):
        require_monai()


def test_brain_inference_raises_before_touching_the_pipeline(monkeypatch):
    _block_monai(monkeypatch)
    built = []
    fake = types.ModuleType("backend.services.mri_pipeline")
    fake.MRIPipeline = lambda: built.append(1)
    monkeypatch.setitem(sys.modules, "backend.services.mri_pipeline", fake)
    with pytest.raises(MissingDependency, match="monai"):
        InProcessInference().score(StudyRef("s", "d"), ENTRY, nifti=NIFTI)
    assert built == []


def test_brain_inference_refuses_a_null_model_class(monkeypatch):
    # monai importable here, but the external module's own import failed.
    monkeypatch.setattr(inference, "require_monai", lambda: None)
    built = []
    fake = types.ModuleType("backend.services.mri_pipeline")
    fake.SegResNet, fake.SlidingWindowInferer = None, None
    fake.MRIPipeline = lambda: built.append(1)
    services = types.ModuleType("backend.services")
    services.mri_pipeline = fake
    monkeypatch.setitem(sys.modules, "backend", types.ModuleType("backend"))
    monkeypatch.setitem(sys.modules, "backend.services", services)
    monkeypatch.setitem(sys.modules, "backend.services.mri_pipeline", fake)
    with pytest.raises(MissingDependency, match="monai"):
        InProcessInference().score(StudyRef("s", "d"), ENTRY, nifti=NIFTI)
    assert built == []


@pytest.mark.slow
def test_monai_present_passes_the_precondition_and_the_external_module_sees_it():
    """with monai installed, the brain precondition passes and mri_pipeline's SegResNet is real"""
    pytest.importorskip("monai", reason="monai not installed. NOT VERIFIED: the monai-present path")
    require_monai()
    brainmri = str(inference.BRAINMRI)
    if brainmri not in sys.path:
        sys.path.insert(0, brainmri)
    from backend.services import mri_pipeline
    assert mri_pipeline.SegResNet is not None and mri_pipeline.SlidingWindowInferer is not None
