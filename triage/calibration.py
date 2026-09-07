"""Temperature scaling — calibrate raw sigmoid outputs.

Extracted directly from the original triage.py. The maths is identical:

    logit(p) = ln(p / (1 - p))
    calibrated = σ(logit(p) / T)

T > 1 softens overconfident outputs. The original CXR value is T = 1.6.
"""
import math


def _logit(p: float) -> float:
    p = min(max(float(p), 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def calibrate(p: float, temperature: float = 1.6) -> float:
    """Temperature scaling, applied in logit space."""
    return 1 / (1 + math.exp(-_logit(p) / temperature))
