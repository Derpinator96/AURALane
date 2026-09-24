"""Chest multilabel adapter: 18 raw sigmoids -> per-finding signals.

The existing behaviour, moved behind the adapter interface: each finding is
z-scored against its own reference distribution (reference.json), then mapped
to [0, 1] between the registry entry's z_anchor floor and ceiling. Identical to
triage._signal with Z_FLOOR, Z_CEIL = 0.5, 2.5; tests/test_triage_regression.py
proves the outputs match exactly.

Calibrated confidence (temperature scaling) and the raw outputs travel in meta
for display. They do not affect the sort.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import triage
from core.types import Findings

ROOT = Path(__file__).resolve().parents[1]


def _reference(entry: dict) -> dict:
    return json.loads((ROOT / entry["reference"]).read_text())


def finding_names(entry: dict) -> list[str]:
    return list(_reference(entry))


def adapt(model_output: dict[str, float], context: dict[str, Any]) -> Findings:
    entry = context["entry"]
    ref = context.get("reference") or _reference(entry)
    floor, ceil = entry["z_anchor"]

    signals = {}
    for name, p in model_output.items():          # preds order, as triage iterates
        if name not in ref:
            continue
        z = (p - ref[name]["mean"]) / max(ref[name]["sd"], 1e-6)
        signals[name] = max(0.0, min(1.0, (z - floor) / (ceil - floor)))

    return Findings(
        findings=signals,
        evidence={},        # Grad-CAM is detail view only, off by default
        meta={"model_id": entry["id"],
              "raw": dict(model_output),
              "confidence": {k: triage.calibrate(v) for k, v in model_output.items()},
              "temperature": triage.TEMPERATURE})
