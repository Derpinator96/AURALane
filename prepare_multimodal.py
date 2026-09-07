"""Generate multi-modal scored pool — extends scores.json with CT and MRI fixture entries.

Preserves all existing CXR entries. Appends CT and MRI studies scored through
the common triage engine using the prototype/experimental adapters.

Usage:
    python prepare_multimodal.py
"""
import json
import os
import sys
import random

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.ct_head import HeadCTAdapter
from models.mri_brain import BrainMRIAdapter
import triage

SCORES_PATH = "scores.json"
CT_COUNT = 60       # 60 CT studies
MRI_COUNT = 40      # 40 MRI studies
SEED = 2026


def generate_ct_studies(n, start_id):
    adapter = HeadCTAdapter()
    rng = random.Random(SEED)
    studies = []

    # Distribution: ~10% critical, ~15% urgent, ~20% expedited, ~55% routine
    presets = (
        ["critical"] * max(1, n // 10) +
        ["urgent"] * max(1, n // 7) +
        ["routine"] * (n // 2)
    )
    presets += [None] * (n - len(presets))
    rng.shuffle(presets)

    for i, preset in enumerate(presets):
        seed = SEED + 10000 + i
        result = adapter.infer(preset=preset, seed=seed)
        preds = result.preds_dict
        tri = triage.score(preds, modality="CT")

        study_id = f"CT-{start_id + i:03d}"
        patient_id = f"PID-C{rng.randint(1000, 9999):04X}"

        tri.update({
            "id": study_id,
            "patient_id": patient_id,
            "modality": "CT",
            "body_part": "HEAD",
            "filename": f"ct_head_{i+1:03d}.dcm",
            "image": "",
            "model_status": "PRETRAINED PROTOTYPE",
            "model_name": adapter.model_name,
            "data_source": "DEMO FIXTURE",
            "model_explanation": "Demo fixture — not live model inference.",
        })
        studies.append(tri)

    return studies


def generate_mri_studies(n, start_id):
    adapter = BrainMRIAdapter()
    rng = random.Random(SEED + 5000)
    studies = []

    presets = (
        ["critical"] * max(1, n // 10) +
        ["urgent"] * max(1, n // 7) +
        ["routine"] * (n // 2)
    )
    presets += [None] * (n - len(presets))
    rng.shuffle(presets)

    for i, preset in enumerate(presets):
        seed = SEED + 20000 + i
        result = adapter.infer(preset=preset, seed=seed)
        preds = result.preds_dict
        tri = triage.score(preds, modality="MRI")

        study_id = f"MRI-{start_id + i:03d}"
        patient_id = f"PID-M{rng.randint(1000, 9999):04X}"

        tri.update({
            "id": study_id,
            "patient_id": patient_id,
            "modality": "MRI",
            "body_part": "BRAIN",
            "filename": f"mri_brain_{i+1:03d}.nii",
            "image": "",
            "model_status": "EXPERIMENTAL",
            "model_name": adapter.model_name,
            "data_source": "DEMO FIXTURE",
            "model_explanation": "Demo fixture — not live model inference.",
        })
        studies.append(tri)

    return studies


def main():
    # Load existing scores.json
    with open(SCORES_PATH) as f:
        data = json.load(f)

    existing = data["studies"]

    # Tag existing CXR studies with modality fields if missing
    for s in existing:
        s.setdefault("modality", "CXR")
        s.setdefault("body_part", "CHEST")
        s.setdefault("model_status", "LIVE MODEL")
        s.setdefault("model_name", data.get("model", "densenet121-res224-all"))
        s.setdefault("data_source", "LIVE MODEL INFERENCE")
        s.setdefault("model_explanation", "TorchXRayVision DenseNet121 model inference.")
        s.setdefault("patient_id", f"PID-X{hash(s['id']) % 10000:04X}")
        # Add priority_reason if not already present
        if "priority_reason" not in s:
            d = s.get("driver", "Finding")
            l = s.get("lane", "ROUTINE")
            if s.get("abstained"):
                s["priority_reason"] = f"Uncertainty flag: confidence for {d} triggers ABSTAIN for mandatory human review."
            elif l == "CRITICAL":
                s["priority_reason"] = f"High-acuity {d} finding contributed to a CRITICAL priority recommendation."
            elif l == "URGENT":
                s["priority_reason"] = f"Elevated-acuity {d} finding contributed to an URGENT priority recommendation."
            elif l == "EXPEDITED":
                s["priority_reason"] = f"Moderate {d} finding contributed to an EXPEDITED priority recommendation."
            else:
                s["priority_reason"] = f"Low signal across findings; assigned ROUTINE priority."

    # Generate CT and MRI studies
    ct_studies = generate_ct_studies(CT_COUNT, 1)
    mri_studies = generate_mri_studies(MRI_COUNT, 1)

    all_studies = existing + ct_studies + mri_studies

    # Lane mix summary
    from collections import Counter
    lane_counts = Counter(s["lane"] for s in all_studies)
    modality_counts = Counter(s["modality"] for s in all_studies)

    # Write extended scores.json
    data["studies"] = all_studies
    data["n_studies"] = len(all_studies)
    data["modalities"] = list(modality_counts.keys())

    with open(SCORES_PATH, "w") as f:
        json.dump(data, f, indent=1)

    print(f"Wrote {len(all_studies)} studies to {SCORES_PATH}")
    print(f"\nModality mix:")
    for mod, n in modality_counts.most_common():
        print(f"  {mod:<5} {n:>5}  ({100*n/len(all_studies):.1f}%)")
    print(f"\nLane mix:")
    for lane, n in lane_counts.most_common():
        print(f"  {lane:<10} {n:>5}  ({100*n/len(all_studies):.1f}%)")


if __name__ == "__main__":
    main()
