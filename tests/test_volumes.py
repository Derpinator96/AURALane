"""DICOM series -> NIfTI rebuilds the source volume exactly.

Needs data/brain/raw/<case>/ and the DICOM that nifti_to_dicom.py --slices 1
wrote from it.
"""
import json
from collections import defaultdict
from pathlib import Path

import nibabel as nib
import numpy as np
import pydicom
import pytest

from core.volumes import series_to_nifti

ROOT = Path(__file__).resolve().parents[1]
DICOM = ROOT / "data" / "brain" / "dicom"
RAW = ROOT / "data" / "brain" / "raw"
SUFFIX = {"T1C": "t1ce", "T1": "t1", "T2": "t2", "FLAIR": "flair"}


def test_round_trip_matches_source_nifti():
    manifest = DICOM / "manifest.json"
    if not manifest.exists():
        pytest.fail("build the brain corpus: python data/brain/nifti_to_dicom.py --slices 1")
    entries = json.loads(manifest.read_text())
    study = entries[0]["study_uid"]
    case = entries[0].get("case") or entries[0].get("source_case")
    series = defaultdict(list)
    for e in entries:
        if e["study_uid"] == study:
            series[e["series_description"]].append(pydicom.dcmread(DICOM / e["path"]))

    assert set(series) == set(SUFFIX)
    for desc, datasets in series.items():
        src = nib.load(next((RAW / case).glob(f"*_{SUFFIX[desc]}.nii.gz")))
        got = series_to_nifti(datasets)
        assert got.shape == src.shape, desc
        assert np.array_equal(np.asarray(got.dataobj), np.asarray(src.dataobj)), desc
        assert np.allclose(got.affine, src.affine, atol=1e-3), (desc, got.affine, src.affine)
        assert nib.aff2axcodes(got.affine) == nib.aff2axcodes(src.affine)
