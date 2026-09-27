"""Check A: segmentation plausibility on the study's own images, no ground truth."""
import json
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from core import mask_check
from core.registry import Registry

LIMITS = Registry().get("brain-brats-monai-v0.5.4")["mask_check"]
STUDIES = Path(__file__).resolve().parents[1] / "_external" / "brainmri" / "data" / "studies"
RECORDED = ["00000057", "MRI-1790025179", "MRI-1790070297", "MRI-1790081977"]


def _volumes(lesion_bright=True):
    """A 40^3 'brain' in a 60^3 field, with noise, and one lesion: core,
    enhancing rim and surrounding edema."""
    rng = np.random.default_rng(1)
    t1c = np.zeros((60, 60, 60), np.float32)
    t1c[10:50, 10:50, 10:50] = rng.normal(100, 5, (40, 40, 40))
    flair = t1c.copy()
    pred = np.zeros(t1c.shape, np.uint8)
    pred[20:34, 20:34, 20:34] = 2          # edema
    pred[24:30, 24:30, 24:30] = 4          # enhancing
    pred[26:28, 26:28, 26:28] = 1          # necrotic core
    if lesion_bright:
        flair[pred == 2] += 40
        t1c[pred == 4] += 40
    return pred, t1c, flair


def test_plausible_lesion_passes():
    r = mask_check.check(*_volumes(), LIMITS)
    assert r["passed"] and r["failed"] == []
    assert set(r["criteria"]) == {"inside_brain", "edema_flair", "et_t1c", "largest_component"}


def test_each_criterion_can_fail_on_its_own():
    pred, t1c, flair = _volumes()
    flair[pred == 2] -= 80                                  # "edema" darker than brain on FLAIR
    assert mask_check.check(pred, t1c, flair, LIMITS)["failed"] == ["edema_flair"]

    pred, t1c, flair = _volumes()
    pred[0:10, 0:60, 0:60] = 2                              # mask spills outside the brain
    assert "inside_brain" in mask_check.check(pred, t1c, flair, LIMITS)["failed"]

    pred, t1c, flair = _volumes()
    t1c[pred == 4] -= 80                                    # "enhancing" but dark on T1c
    assert mask_check.check(pred, t1c, flair, LIMITS)["failed"] == ["et_t1c"]


def test_multifocal_disease_abstains_by_design():
    """Documented misfire: several separate lesions fail largest_component.
    Abstention is the chosen safe direction; this criterion loosens first."""
    pred, t1c, flair = _volumes()
    for x in (10, 30):                                      # two more separate lesions
        pred[x:x + 12, 36:48, 12:24] = 2
        flair[x:x + 12, 36:48, 12:24] += 40
    r = mask_check.check(pred, t1c, flair, LIMITS)
    assert r["failed"] == ["largest_component"]
    assert r["criteria"]["largest_component"]["components"] == 3


def test_empty_prediction_fails():
    pred, t1c, flair = _volumes()
    assert mask_check.check(np.zeros_like(pred), t1c, flair, LIMITS)["failed"] == ["empty"]


def test_reason_says_not_verified_never_broken():
    r = mask_check.check(np.zeros((4, 4, 4), np.uint8), np.ones((4, 4, 4)), np.ones((4, 4, 4)), LIMITS)
    text = mask_check.reason(r)
    assert text.startswith("Segmentation could not be automatically verified")
    assert "broken" not in text.lower() and "wrong" not in text.lower()


@pytest.mark.local_data
@pytest.mark.parametrize("case", RECORDED)
def test_recorded_cases_pass(case):
    """The four recorded model outputs pass: no currently scored study abstains."""
    if not (STUDIES / case / "output" / "prediction.nii.gz").exists():
        pytest.fail(f"{case} missing; clone shauryajain111/brainmri into _external/brainmri")
    load = lambda n: np.asarray(nib.load(STUDIES / case / n).dataobj)
    r = mask_check.check(load("output/prediction.nii.gz"), load("input/t1ce.nii"),
                         load("input/flair.nii"), LIMITS)
    assert r["passed"], r
