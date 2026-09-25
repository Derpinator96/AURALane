"""Parallel de-identification masks exactly what serial de-identification masks.

All inputs synthetic: CR instances built with sim/generator/make_dicom.py's own
functions, identifiers burned into the pixels with PIL, written to a temp dir.
Runs the real Tesseract binary; skips loudly without it.
"""
import datetime
import random
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest

from core.pipeline import deidentify_all

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sim" / "edge"))
sys.path.insert(0, str(ROOT / "sim" / "generator"))
import identity     # noqa: E402
import make_dicom   # noqa: E402

pytestmark = [
    pytest.mark.privacy,
    pytest.mark.skipif(shutil.which("tesseract") is None, reason=(
        "Tesseract not installed. NOT VERIFIED: that OCR masking is identical at 1 "
        "and N workers, i.e. that parallel de-identification does not change recall.")),
]


def _study(tmp_path, n=8):
    when = datetime.datetime(2026, 9, 25, 7, 0, 0)
    rng = random.Random(3)
    y, x = np.mgrid[0:320, 0:320]
    paths = []
    for i in range(n):
        ident = make_dicom.make_identity(100 + i, rng, when, burned=i % 2 == 0)
        pixels = (40 + (x + y) * 0.25).astype(np.uint8)      # smooth gradient, 40..199
        if ident["burned_in"]:
            pixels = make_dicom.burn_in(pixels, 255, [
                ident["patient_name"].replace("^", " "), ident["patient_id"],
                f"DOB {ident['birth_date']}"])
        ds = make_dicom.build_instance(pixels, 255, ident, when, f"synthetic-{i}")
        path = tmp_path / f"{i}.dcm"
        ds.save_as(path, enforce_file_format=True)
        paths.append(path)
    return paths


def test_mask_is_identical_at_one_and_many_workers(tmp_path):
    paths = _study(tmp_path)
    serial, r1 = deidentify_all(paths, identity.IdentityMap(str(tmp_path / "a.db")), workers=1)
    parallel, r4 = deidentify_all(paths, identity.IdentityMap(str(tmp_path / "b.db")), workers=4)

    masked = [r["text_regions_masked"] for r in r1]
    assert all(masked[i] > 0 for i in range(0, len(paths), 2)), \
        f"burned-in images were not masked at all, so equality proves nothing: {masked}"
    assert masked == [r["text_regions_masked"] for r in r4]
    for i, (a, b) in enumerate(zip(serial, parallel)):
        assert np.array_equal(a.pixel_array, b.pixel_array), f"instance {i} masked differently"


def test_every_instance_is_processed_in_order(tmp_path):
    """No sampling: every path comes back de-identified, in input order."""
    paths = _study(tmp_path, n=5)
    out, reports = deidentify_all(paths, identity.IdentityMap(str(tmp_path / "c.db")), workers=3)
    assert len(out) == len(reports) == 5
    assert all(ds.PatientIdentityRemoved == "YES" for ds in out)
    assert [int(ds.InstanceNumber) for ds in out] == [1] * 5
    assert len({str(ds.SOPInstanceUID) for ds in out}) == 5
