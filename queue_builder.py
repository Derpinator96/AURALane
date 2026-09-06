"""Serve the scored pool the demo draws its intake from.

This used to hand-pick nine studies and bury the critical one eighth. It no
longer does: the page draws a random intake from the whole pool on every run,
so nothing about which studies appear is chosen by us.

Two things are still simulated, and both are stated on screen:

  1. arrival order   real studies arrive when scanners produce them. Here they
                     arrive in random order, one every ARRIVAL_GAP_MINUTES of
                     simulated time.
  2. read cadence    one radiologist clearing one study every READ_MINUTES.

The acuity scores, lanes and abstentions are NOT simulated. They come from
TorchXRayVision output through triage.py.
"""
import json
from collections import Counter

READ_MINUTES = 6               # one radiologist, one study every 6 minutes
ARRIVAL_GAP_MINUTES = 4        # a study lands every 4 minutes


def build(scores_path="scores.json"):
    """Return the whole scored pool. The page samples from it."""
    data = json.load(open(scores_path))
    studies = data["studies"]
    return {
        "read_minutes": READ_MINUTES,
        "arrival_gap_minutes": ARRIVAL_GAP_MINUTES,
        "model": data.get("model"),
        "temperature": data.get("temperature"),
        "reference_fitted": data.get("reference_fitted", False),
        "pool_size": len(studies),
        "lane_mix": Counter(s["lane"] for s in studies),
        "studies": studies,
    }


if __name__ == "__main__":
    q = build()
    print(f"pool: {q['pool_size']} studies")
    for lane, n in q["lane_mix"].most_common():
        print(f"  {lane:<10} {n:>4}  {100*n/q['pool_size']:.1f}%")
