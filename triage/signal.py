"""Baseline signal extraction — how far above normal is this finding?

Extracted from the original triage.py _signal() function. Logic identical:

    z = (p - mean) / sd
    signal = clamp((z - z_floor) / (z_ceil - z_floor), 0, 1)

A finding contributes nothing until it is at least z_floor standard deviations
above its own baseline. Without that floor, taking a max over many heads means
almost every study has *something* mildly elevated.
"""


def signal(p: float, ref: dict, z_floor: float = 0.5, z_ceil: float = 2.5) -> float:
    """How far above this finding's own baseline the output sits.

    0.0 means 'typical for this finding across the reference set'.
    """
    z = (p - ref["mean"]) / max(ref["sd"], 1e-6)
    return max(0.0, min(1.0, (z - z_floor) / (z_ceil - z_floor)))
