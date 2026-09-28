"""Regional prior: a bounded nudge from the site's state, chest only.

    adjusted signal = signal x clamp((p_state(d) / p_national(d)) ^ w, 0.8, 1.25)

p is GBD 2023 prevalence (models/regional_priors.json) for the cause behind
finding d; the national baseline is GBD's own India row, w = 0.5. So regional
context moves a finding at most 25% up or 20% down, and never overrides the
image: a signal of 0 stays 0. A finding with no prior keeps its signal. The
result is clamped to [0, 1], the signal's range.

Applied after the adapter's z-score and before triage. The reference
distribution is never refitted on regional data: that would make a locally
common finding less unusual and sort it down (CLAUDE.md, "Geographic
prevalence must not touch the reference distribution").

The region is the SITE's state, set per deployment or edge agent
(AURALANE_SITE_STATE, or ingest --state), never read from DICOM:
de-identification removes location anyway. AURALANE_REGIONAL_PRIOR=off turns
the step off, for side-by-side comparison.

Replaces the original scorer's posterior (likelihood x max(prior, 0.025), with
a 0.95 override), which multiplied a probability by a prevalence the model had
already seen in training.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PRIORS_PATH = Path(__file__).resolve().parents[1] / "models" / "regional_priors.json"


@dataclass(frozen=True)
class RegionalSetting:
    state: str | None
    enabled: bool


def load(path: Path = PRIORS_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def states(priors: dict | None = None) -> list[str]:
    priors = priors or load()
    return sorted(s for s in priors["prevalence"] if s != priors["national"])


def setting(state_override: str | None = None) -> RegionalSetting:
    """The site's state and whether the step runs, from the environment and an
    optional per-ingest override. An unknown state is an error, not a no-op."""
    enabled = os.environ.get("AURALANE_REGIONAL_PRIOR", "on").strip().lower() != "off"
    state = (state_override or os.environ.get("AURALANE_SITE_STATE") or "").strip() or None
    if state is not None and state not in states():
        raise ValueError(f"unknown state {state!r}; one of: {', '.join(states())}")
    return RegionalSetting(state=state, enabled=enabled)


def factor_for(finding: str, state: str, priors: dict) -> dict[str, float] | None:
    """{"prior", "national", "ratio", "factor"} for one finding, or None when no
    GBD cause backs it."""
    cause = next((c for c, fs in priors["causes"].items() if finding in fs), None)
    if cause is None:
        return None
    p_state = priors["prevalence"][state][cause]
    p_nat = priors["prevalence"][priors["national"]][cause]
    ratio = p_state / p_nat
    lo, hi = priors["bounds"]
    factor = min(hi, max(lo, ratio ** priors["weight"]))
    return {"cause": cause, "prior": p_state, "national": p_nat,
            "ratio": round(ratio, 4), "factor": round(factor, 4)}


def apply(signals: dict[str, float], state: str,
          priors: dict | None = None) -> tuple[dict[str, float], dict[str, Any]]:
    """-> (adjusted signals, evidence). Evidence records every applied factor
    and the signal before it, so the rationale panel can show what moved."""
    priors = priors or load()
    adjusted, applied = {}, {}
    for name, s in signals.items():
        f = factor_for(name, state, priors)
        if f is None:
            adjusted[name] = s
            continue
        adjusted[name] = max(0.0, min(1.0, s * f["factor"]))
        applied[name] = {**f, "signal_before": round(s, 4)}
    return adjusted, {"state": state, "national": priors["national"],
                      "weight": priors["weight"], "bounds": priors["bounds"],
                      "factors": applied}
