"""Integration tests for the modality router and multi-modal adapters."""
import pytest
from modality_router import route, supported_modalities
import triage


def test_supported_modalities():
    mods = supported_modalities()
    assert "CXR" in mods
    assert "CT" in mods
    assert "MRI" in mods


def test_ct_head_routing():
    res = route("CT", preset="critical", seed=42)
    assert res.modality == "CT"
    assert res.body_part == "HEAD"
    assert res.status == "PRETRAINED PROTOTYPE"
    assert "Intracranial_Hemorrhage" in res.preds_dict

    tri = triage.score(res.preds_dict, modality="CT")
    assert tri["driver"] in res.preds_dict
    assert tri["lane"] in ["CRITICAL", "URGENT", "EXPEDITED", "ROUTINE", "ABSTAIN"]


def test_mri_brain_routing():
    res = route("MRI", preset="critical", seed=100)
    assert res.modality == "MRI"
    assert res.body_part == "BRAIN"
    assert res.status == "EXPERIMENTAL"
    assert "Structural_Lesion" in res.preds_dict

    tri = triage.score(res.preds_dict, modality="MRI")
    assert tri["driver"] in res.preds_dict
