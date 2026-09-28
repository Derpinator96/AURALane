"""Head CT hemorrhage adapter: Mehak's triagelane-ct output -> findings.

Her pipeline (preprocessing, ViT model, top-k aggregation) runs unchanged in
core/providers/local/inference.py; her lanes.py is never called. Our triage
assigns every lane, with the same urgency weighting, max-not-sum and
abstention band as chest and brain.

Her scale is converted here, and nowhere else:

  signal  = clamp((likelihood - 0.35) / (0.85 - 0.35), 0, 1)
            likelihood is her study-level hemorrhage likelihood (temperature-
            calibrated, top-k aggregated). Her Expedited floor (0.35) maps to
            signal 0 and her Critical threshold (0.85) to signal 1.
  urgency = her subtype weight / 1.25, so epidural (her 1.25) is 1.0 and
            intraventricular (her 1.00) is 0.80. In models/registry.json.

The finding is the dominant subtype of her highest-scoring slice, as in her
own scoring: her study score is likelihood x the dominant subtype's weight.
The other subtypes' aggregated probabilities travel in evidence for display.

PROVISIONAL: both anchors are her lane thresholds, not a fitted operating
point. Same posture as the brain anchors: they need a real population,
including normals, before they mean more than "consistent with her pipeline".
"""
from __future__ import annotations

from typing import Any

from core.types import Findings

# TODO: wire her Grad-CAM on the top slice (triagelane_ct.gradcam) as the CT rationale image.

SUBTYPES = ("epidural", "subdural", "subarachnoid", "intraparenchymal", "intraventricular")


def finding_names(entry: dict) -> list[str]:
    return [f"{s}_hemorrhage" for s in SUBTYPES]


def adapt(model_output: dict[str, Any], context: dict[str, Any]) -> Findings:
    entry = context["entry"]
    floor, ceil = entry["anchors"]["hemorrhage_likelihood"]
    likelihood = float(model_output["raw_score"])
    signal = max(0.0, min(1.0, (likelihood - floor) / (ceil - floor)))
    name = f"{model_output['dominant_subtype']}_hemorrhage"
    return Findings(
        findings={name: signal},
        evidence={"ct": {k: model_output[k] for k in
                         ("dominant_subtype", "raw_score", "study_score", "k_used",
                          "n_slices", "top_slice_index", "subtype_scores")}},
        meta={"model_id": entry["id"],
              # Her likelihood is already temperature-scaled (T = 1.645), so it is
              # the displayed confidence, as with chest.
              "confidence": {name: likelihood},
              "raw": {name: likelihood},
              "anchors_provisional": True})
