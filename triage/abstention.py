"""Abstention evaluator.

If the driving finding is elevated but not clearly enough to own a lane,
refuse to assign one and send the study to a human. This is the fail-open
path — the thing no competitor shows.

Extracted from the original triage.py ABSTAIN_LO / ABSTAIN_HI logic.
"""


def should_abstain(driver_signal: float,
                   abstain_lo: float = 0.35,
                   abstain_hi: float = 0.60) -> bool:
    """Return True if the driver signal sits in the uncertain band."""
    return abstain_lo <= driver_signal <= abstain_hi
