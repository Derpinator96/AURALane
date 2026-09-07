"""AURALane triage package — modality-agnostic triage engine.

Refactored from the original triage.py into composable stages:

    calibration  →  signal  →  urgency  →  acuity  →  abstention  →  lanes

Each module is independently testable. The engine.py orchestrator composes
them into the same score() function the rest of the codebase expects.

This __init__.py re-exports everything that prepare.py, server.py, and
queue_builder.py previously imported from the root-level triage.py,
so ``import triage; triage.score(...)`` continues to work unchanged.
"""

# Re-export the public API that callers expect from ``import triage``
from triage.engine import (
    score,
    load_reference,
    build_reference,
    TEMPERATURE,
    URGENCY,
    ABSTAIN_LO,
    ABSTAIN_HI,
    Z_FLOOR,
    Z_CEIL,
)
from triage.calibration import calibrate
