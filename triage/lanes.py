"""SLA lane assignment.

Maps an acuity score to one of four priority lanes, each with a response-time
target. Thresholds are an operating point, not a law of nature — they were set
from the acuity percentiles of a reference sample so the critical lane holds
roughly the top 7%.

Extracted from the original triage.py LANES constant.
"""

# (label, acuity_floor, sla_text, sla_minutes)
LANES = [
    ("CRITICAL",  78, "< 15 min", 15),
    ("URGENT",    52, "< 1 hr",   60),
    ("EXPEDITED", 22, "< 4 hr",  240),
    ("ROUTINE",    0, "scheduled", 1440),
]


def assign_lane(acuity: float, abstained: bool) -> tuple[str, str, int | None]:
    """Return (lane, sla_text, sla_minutes).

    If the study was abstained, no lane is assigned — a human picks.
    """
    if abstained:
        return "ABSTAIN", "a human picks the lane", None

    for name, floor, label, mins in LANES:
        if acuity >= floor:
            return name, label, mins

    # Should not reach here, but ROUTINE catches acuity >= 0
    return "ROUTINE", "scheduled", 1440
