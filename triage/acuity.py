"""Acuity scoring — the weighted urgency of the dominant finding.

    weighted[k] = signal[k] * urgency_weight[k]
    driver      = argmax(weighted)
    acuity      = round(weighted[driver] * 100, 1)

Extracted from the original triage.py score() function.
"""


def compute_acuity(signals: dict[str, float],
                   urgency_weights: dict[str, float],
                   default_weight: float = 0.15) -> tuple[str, float, float]:
    """Return (driver_finding, acuity_score, driver_signal).

    driver_finding : name of the finding that dominates the acuity
    acuity_score   : 0–100 acuity value
    driver_signal  : raw signal value of the driver (for abstention check)
    """
    weighted = {
        k: signals[k] * urgency_weights.get(k, default_weight)
        for k in signals
    }
    driver = max(weighted, key=weighted.get)
    acuity = round(weighted[driver] * 100, 1)
    return driver, acuity, signals[driver]
