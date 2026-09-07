"""AURALane triage logic — the part the demo is actually about.

Four steps, in this order:

  1. temperature scaling    raw sigmoid output -> calibrated confidence, the
                            number a clinician is shown
  2. per-finding operating  TorchXRayVision's 18 heads sit at very different
     point                  points (Nodule never drops below ~0.36, Edema
                            averages ~0.21). A flat 0.5 threshold makes one
                            head dominate every study, so each finding is
                            scored against its own reference distribution.
  3. clinical weighting     a confidence is not an urgency. Pneumothorax at
                            0.6 outranks cardiomegaly at 0.9.
  4. abstention             if the driving finding is elevated but not clearly,
                            refuse to assign a lane and send it to a human.

Shared by the live server and the offline fixture, so the demo shows the same
numbers whichever way it runs.

NOT A DIAGNOSTIC DEVICE. This orders a reading queue. It does not read a study.
"""
import json
import math
import os

# One scalar, applied in logit space. T > 1 softens overconfident outputs.
# Fitted on a held-out split in the real system; fixed here so the demo is
# reproducible, and stated as such on screen.
TEMPERATURE = 1.6

# How fast a finding needs a human — not how sure the model is.
# Chest X-ray only; this is the first lane in the roadmap.
URGENCY = {
    "Pneumothorax": 1.00,          # can be minutes
    "Edema": 0.85,
    "Consolidation": 0.78,
    "Pneumonia": 0.75,
    "Effusion": 0.66,
    "Mass": 0.58,
    "Lung Opacity": 0.52,
    "Infiltration": 0.46,
    "Nodule": 0.44,
    "Fracture": 0.42,
    "Atelectasis": 0.30,
    "Lung Lesion": 0.30,
    "Enlarged Cardiomediastinum": 0.26,
    "Cardiomegaly": 0.24,
    "Pleural_Thickening": 0.20,
    "Emphysema": 0.18,
    "Fibrosis": 0.16,
    "Hernia": 0.12,
}

# acuity floor, label shown, SLA in minutes
# Thresholds are an operating point, not a law of nature. They were set from the
# acuity percentiles of a 100-study NIH ChestX-ray14 sample so the critical lane
# holds roughly the top 7% — about what one reader can actually absorb. Re-tune
# them against your own corpus; that is a capacity decision, not a modelling one.
LANES = [("CRITICAL", 78, "< 15 min", 15),
         ("URGENT", 52, "< 1 hr", 60),
         ("EXPEDITED", 22, "< 4 hr", 240),
         ("ROUTINE", 0, "scheduled", 1440)]

# The driving finding is elevated, but not clearly enough to own a lane.
ABSTAIN_LO, ABSTAIN_HI = 0.35, 0.60

# A finding contributes nothing until it is at least Z_FLOOR standard deviations
# above its own baseline, and saturates at Z_CEIL. Without a floor, taking a max
# over 18 heads means almost every study has *something* mildly elevated and the
# whole corpus scores high.
Z_FLOOR, Z_CEIL = 0.5, 2.5

_REF_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reference.json")
_reference = None


def load_reference(path=None):
    """Per-pathology {mean, sd} the operating points are measured against."""
    global _reference
    if _reference is None:
        with open(path or _REF_PATH) as f:
            _reference = json.load(f)
    return _reference


def _logit(p):
    p = min(max(float(p), 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def calibrate(p):
    """Temperature scaling, applied in logit space."""
    return 1 / (1 + math.exp(-_logit(p) / TEMPERATURE))


def _phi(z):
    """Standard normal CDF, stdlib only."""
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def _signal(p, ref):
    """How far above this finding's own baseline the output sits.

    0.0 means 'typical for this finding across the reference set' — which is
    the whole point, because typical is not a reason to jump the queue.
    """
    z = (p - ref["mean"]) / max(ref["sd"], 1e-6)
    return max(0.0, min(1.0, (z - Z_FLOOR) / (Z_CEIL - Z_FLOOR)))


def score(preds, reference=None):
    """preds: {pathology: raw sigmoid output} -> triage decision."""
    ref = reference or load_reference()
    cal = {k: calibrate(v) for k, v in preds.items()}
    sig = {k: _signal(v, ref[k]) for k, v in preds.items() if k in ref}
    weighted = {k: sig[k] * URGENCY.get(k, 0.15) for k in sig}

    driver = max(weighted, key=weighted.get)
    acuity = round(weighted[driver] * 100, 1)
    s = sig[driver]
    abstained = ABSTAIN_LO <= s <= ABSTAIN_HI

    lane, sla, minutes = "ABSTAIN", "a human picks the lane", None
    if not abstained:
        for name, floor, label, mins in LANES:
            if acuity >= floor:
                lane, sla, minutes = name, label, mins
                break

    top = sorted(weighted, key=weighted.get, reverse=True)[:3]
    return {
        "acuity": acuity,
        "lane": lane,
        "sla": sla,
        "sla_minutes": minutes,
        "abstained": abstained,
        "driver": driver,
        "confidence": round(cal[driver], 3),
        "signal": round(s, 3),
        "raw": round(float(preds[driver]), 3),
        "top_findings": [
            {"name": k,
             "confidence": round(cal[k], 3),
             "signal": round(sig[k], 3),
             "urgency": URGENCY.get(k, 0.15)}
            for k in top
        ],
    }


def build_reference(all_preds):
    """Fit per-pathology mean/sd from a corpus of raw model outputs."""
    keys = list(all_preds[0].keys())
    ref = {}
    for k in keys:
        vals = [p[k] for p in all_preds]
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / max(len(vals) - 1, 1)
        ref[k] = {"mean": round(mean, 5), "sd": round(math.sqrt(var), 5)}
    return ref
