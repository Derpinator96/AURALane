"""Check A: is a brain segmentation plausible on its own images?

Runs on every brain study, inside the adapt step, before any finding is
scored. It needs no ground truth, so it behaves identically in the demo and in
production. A study that fails any criterion gets no lane: it goes to NEEDS
HUMAN TRIAGE with the failed criterion named. The wording is always "could not
be automatically verified", never "the mask is broken": failing these checks
means the segmentation is not consistent with the images in a way we can
confirm, not that it is proven wrong.

Criteria, thresholds from the registry entry's mask_check block:

  inside_brain      share of predicted whole tumour inside the brain mask,
                    at least inside_brain_min. The brain mask is T1c > 0, which
                    assumes skull-stripped input (true for BraTS, as for
                    brain_volume_cm3 in adapters/brats.py).
  edema_flair       predicted edema (label 2) brighter on FLAIR than the rest
                    of the brain: z above flair_edema_z_min. Skipped when the
                    prediction has no edema voxels.
  et_t1c            predicted enhancing tumour (label 4) brighter on T1c than
                    the rest of the brain: z above t1c_et_z_min. Skipped when
                    there is no enhancing tumour.
  largest_component largest connected piece of the whole tumour, as a share of
                    the whole tumour, at least largest_component_min.

The z floors are 0: "brighter than the rest of the brain at all". None of the
thresholds were fitted to the cases in this repository; they are floors for
"consistent at all".

largest_component is the criterion expected to misfire on genuinely
multifocal disease (metastases, multifocal glioma), where a correct mask is
several separate pieces. Abstention is the chosen safe direction, and it is
the first criterion to loosen if it fires on real data. See
docs/HOW-IT-WORKS.md.

Prediction labels are the pipeline's label map: 1 necrotic core, 2 edema,
4 enhancing tumour.
"""
from __future__ import annotations

from typing import Any

import numpy as np

FAILED_MESSAGE = "Segmentation could not be automatically verified"


def _z(values: np.ndarray, ref: np.ndarray) -> float:
    sd = float(ref.std())
    return float((values.mean() - ref.mean()) / sd) if sd > 0 else 0.0


def check(prediction: np.ndarray, t1c: np.ndarray, flair: np.ndarray,
          limits: dict[str, float]) -> dict[str, Any]:
    """-> {"passed": bool, "failed": [names], "criteria": {name: {...}}}.

    Every criterion is computed and reported even after one fails, so the audit
    trail shows the whole picture.
    """
    from scipy import ndimage

    pred = np.asarray(prediction)
    wt = pred > 0
    brain = np.asarray(t1c) > 0
    n = int(wt.sum())
    crit: dict[str, dict[str, Any]] = {}
    if n == 0:
        return {"passed": False, "failed": ["empty"],
                "criteria": {"empty": {"value": 0, "limit": 1, "passed": False}}}

    inside = float((wt & brain).sum() / n)
    crit["inside_brain"] = {"value": round(inside, 4), "limit": limits["inside_brain_min"],
                            "passed": inside >= limits["inside_brain_min"]}

    rest = brain & ~wt
    fl, tc = np.asarray(flair, np.float32), np.asarray(t1c, np.float32)
    edema, et = pred == 2, pred == 4
    if edema.any() and rest.any():
        z = _z(fl[edema], fl[rest])
        crit["edema_flair"] = {"value": round(z, 3), "limit": limits["flair_edema_z_min"],
                               "passed": z > limits["flair_edema_z_min"]}
    if et.any() and rest.any():
        z = _z(tc[et], tc[rest])
        crit["et_t1c"] = {"value": round(z, 3), "limit": limits["t1c_et_z_min"],
                          "passed": z > limits["t1c_et_z_min"]}

    labels, count = ndimage.label(wt)
    sizes = np.bincount(labels.ravel())[1:]
    share = float(sizes.max() / n)
    crit["largest_component"] = {"value": round(share, 4), "components": int(count),
                                 "limit": limits["largest_component_min"],
                                 "passed": share >= limits["largest_component_min"]}

    failed = [k for k, v in crit.items() if not v["passed"]]
    return {"passed": not failed, "failed": failed, "criteria": crit}


def reason(result: dict[str, Any]) -> str:
    """The abstention reason shown on screen and in the audit trail."""
    return f"{FAILED_MESSAGE} (failed: {', '.join(result['failed'])})"
