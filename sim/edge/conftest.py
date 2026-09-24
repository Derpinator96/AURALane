"""Point the privacy suite at the chest corpus when run from anywhere.

test_deid.py reads SIM_STUDIES at import time and otherwise falls back to
../data/studies relative to the working directory, which from the repo root is
outside the repo. pytest imports this file first, so a default set here takes
effect without touching the test module. An explicit SIM_STUDIES still wins.
"""
import os
from pathlib import Path

os.environ.setdefault(
    "SIM_STUDIES",
    str(Path(__file__).resolve().parents[2] / "data" / "chest" / "studies"))
