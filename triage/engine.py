"""Triage engine — orchestrates calibration → signal → urgency → acuity → abstention → lanes.

This is the single entry point for every modality. It accepts raw model
predictions and a modality identifier, then runs the full triage pipeline
using modality-specific configuration.

For CXR, the output is byte-identical to the original triage.py score().
"""
import json
import math
import os

from triage.calibration import calibrate
from triage.signal import signal as compute_signal
from triage.urgency import get_weights, get_default
from triage.acuity import compute_acuity
from triage.abstention import should_abstain
from triage.lanes import assign_lane

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── Configuration loading ────────────────────────────────────────────

_calibration_cache = None
_reference_cache = {}


def _load_calibration():
    global _calibration_cache
    if _calibration_cache is None:
        path = os.path.join(_HERE, "config", "calibration.json")
        with open(path) as f:
            _calibration_cache = json.load(f)
    return _calibration_cache


def load_reference(path=None, modality="CXR"):
    """Load per-pathology {mean, sd} baseline statistics.

    Falls back to the root reference.json for backward compatibility.
    """
    if modality not in _reference_cache:
        if path:
            with open(path) as f:
                _reference_cache[modality] = json.load(f)
        else:
            # Try modality-specific config first, then root fallback
            modality_path = os.path.join(
                _HERE, "config", f"reference_{modality.lower()}.json"
            )
            if os.path.exists(modality_path):
                with open(modality_path) as f:
                    _reference_cache[modality] = json.load(f)
            else:
                root_path = os.path.join(_HERE, "reference.json")
                with open(root_path) as f:
                    _reference_cache[modality] = json.load(f)
    return _reference_cache[modality]


def _get_modality_params(modality: str) -> dict:
    """Get calibration/abstention parameters for a modality."""
    cal = _load_calibration()
    return cal.get(modality, cal.get("CXR"))  # fallback to CXR defaults


# ── Backward-compatible constants (used by prepare.py, old triage.py shim) ──

TEMPERATURE = 1.6
URGENCY = {
    "Pneumothorax": 1.00, "Edema": 0.85, "Consolidation": 0.78,
    "Pneumonia": 0.75, "Effusion": 0.66, "Mass": 0.58,
    "Lung Opacity": 0.52, "Infiltration": 0.46, "Nodule": 0.44,
    "Fracture": 0.42, "Atelectasis": 0.30, "Lung Lesion": 0.30,
    "Enlarged Cardiomediastinum": 0.26, "Cardiomegaly": 0.24,
    "Pleural_Thickening": 0.20, "Emphysema": 0.18, "Fibrosis": 0.16,
    "Hernia": 0.12,
}
LANES_CONST = [(78, "< 15 min", 15), (52, "< 1 hr", 60),
               (22, "< 4 hr", 240), (0, "scheduled", 1440)]
ABSTAIN_LO, ABSTAIN_HI = 0.35, 0.60
Z_FLOOR, Z_CEIL = 0.5, 2.5


# ── Core scoring function ────────────────────────────────────────────

def score(preds: dict, reference=None, modality: str = "CXR") -> dict:
    """Score a study's raw predictions through the full triage pipeline.

    preds     : {pathology_name: raw_sigmoid_output}
    reference : optional pre-loaded {pathology: {mean, sd}} dict
    modality  : "CXR" | "CT" | "MRI"

    Returns the same dict shape as the original triage.py score():
        acuity, lane, sla, sla_minutes, abstained,
        driver, confidence, signal, raw,
        top_findings
    """
    params = _get_modality_params(modality)
    temperature = params["temperature"]
    z_floor = params["z_floor"]
    z_ceil = params["z_ceil"]
    abstain_lo = params["abstain_lo"]
    abstain_hi = params["abstain_hi"]

    ref = reference or load_reference(modality=modality)
    urgency_weights = get_weights(modality)
    default_weight = get_default()

    # Step 1: Calibrate all predictions
    cal = {k: calibrate(v, temperature) for k, v in preds.items()}

    # Step 2: Compute baseline signal for findings that have a reference
    sig = {
        k: compute_signal(v, ref[k], z_floor, z_ceil)
        for k, v in preds.items()
        if k in ref
    }

    # Step 3 + 4: Compute acuity (urgency weighting + driver selection)
    driver, acuity, driver_signal = compute_acuity(sig, urgency_weights, default_weight)

    # Step 5: Abstention check
    abstained = should_abstain(driver_signal, abstain_lo, abstain_hi)

    # Step 6: Lane assignment
    lane, sla, sla_minutes = assign_lane(acuity, abstained)

    # Compute weighted priority for all findings that have signal
    weighted = {k: sig[k] * urgency_weights.get(k, default_weight) for k in sig}

    # All findings sorted by weighted priority descending
    all_findings_list = []
    for k in sorted(preds.keys(), key=lambda x: weighted.get(x, 0.0), reverse=True):
        b_mean = ref[k]["mean"] if k in ref else 0.0
        b_sd = ref[k]["sd"] if k in ref else 1.0
        c_val = cal.get(k, 0.0)
        s_val = sig.get(k, 0.0)
        u_wt = urgency_weights.get(k, default_weight)
        w_pri = weighted.get(k, 0.0)
        all_findings_list.append({
            "name": k,
            "raw": round(float(preds[k]), 4),
            "confidence": round(float(c_val), 4),
            "baseline_mean": round(float(b_mean), 4),
            "baseline_sd": round(float(b_sd), 4),
            "signal": round(float(s_val), 4),
            "urgency": round(float(u_wt), 4),
            "weighted_priority": round(float(w_pri), 4),
            "is_driver": (k == driver)
        })

    # 12-step decision trace
    decision_trace = [
        {"stage": "MODEL INFERENCE", "label": f"{modality} Model Output", "detail": f"{len(preds)} findings predicted"},
        {"stage": "RAW CONFIDENCE", "label": f"Driver ({driver.replace('_', ' ')}) Raw", "detail": f"{float(preds[driver]):.1%}"},
        {"stage": "CALIBRATION", "label": f"Temperature Scaling (T={temperature})", "detail": f"{cal[driver]:.1%}"},
        {"stage": "BASELINE COMPARISON", "label": "Population Reference", "detail": f"mean={ref.get(driver, {}).get('mean', 0):.3f}, sd={ref.get(driver, {}).get('sd', 0):.3f}"},
        {"stage": "SIGNAL", "label": "Normalized Z-Score Signal", "detail": f"{driver_signal:.1%}"},
        {"stage": "CLINICAL URGENCY WEIGHT", "label": "Severity Weight", "detail": f"{urgency_weights.get(driver, default_weight):.2f}"},
        {"stage": "WEIGHTED PRIORITY", "label": "Weighted Signal", "detail": f"{weighted.get(driver, 0.0):.3f}"},
        {"stage": "DRIVER FINDING", "label": "Dominant Finding", "detail": driver.replace("_", " ")},
        {"stage": "ACUITY SCORE", "label": "Acuity Score", "detail": f"{acuity:.1f} / 100"},
        {"stage": "ABSTENTION CHECK", "label": f"Uncertainty Band [{abstain_lo}, {abstain_hi}]", "detail": "ABSTAINED (Human review required)" if abstained else "PASSED (Auto lane)"},
        {"stage": "SLA LANE", "label": "Target Window", "detail": f"{lane} ({sla})"},
        {"stage": "WORKLIST PRIORITY", "label": "Worklist Queue", "detail": f"Lane {lane}"}
    ]

    # Generate human-readable AI priority reason
    if abstained:
        reason = f"Uncertainty flag: confidence for {driver.replace('_', ' ')} triggers ABSTAIN for mandatory human review."
    elif lane == "CRITICAL":
        reason = f"High-acuity {driver.replace('_', ' ')} finding contributed to a CRITICAL priority recommendation."
    elif lane == "URGENT":
        reason = f"Elevated-acuity {driver.replace('_', ' ')} finding contributed to an URGENT priority recommendation."
    elif lane == "EXPEDITED":
        reason = f"Moderate {driver.replace('_', ' ')} finding contributed to an EXPEDITED priority recommendation."
    else:
        reason = f"Low signal across findings; assigned ROUTINE priority."

    # Top 3 findings for top_findings backwards-compatible list
    top = sorted(weighted, key=weighted.get, reverse=True)[:3]

    return {
        "acuity": acuity,
        "lane": lane,
        "sla": sla,
        "sla_minutes": sla_minutes,
        "abstained": abstained,
        "driver": driver,
        "confidence": round(cal[driver], 3),
        "signal": round(driver_signal, 3),
        "raw": round(float(preds[driver]), 3),
        "priority_reason": reason,
        "top_findings": [
            {
                "name": k,
                "confidence": round(cal[k], 3),
                "signal": round(sig[k], 3),
                "urgency": urgency_weights.get(k, default_weight),
            }
            for k in top
        ],
        "all_findings": all_findings_list,
        "decision_trace": decision_trace,
    }


def build_reference(all_preds: list[dict]) -> dict:
    """Fit per-pathology mean/sd from a corpus of raw model outputs.

    Identical to the original triage.py build_reference().
    """
    keys = list(all_preds[0].keys())
    ref = {}
    for k in keys:
        vals = [p[k] for p in all_preds]
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / max(len(vals) - 1, 1)
        ref[k] = {"mean": round(mean, 5), "sd": round(math.sqrt(var), 5)}
    return ref
