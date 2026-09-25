"""Tests for nifti_to_dicom.py.

    pytest data/brain/test_nifti_to_dicom.py -v

The two real BraTS cases are int16 with a minimum of 0, 1 mm isotropic, with
empty free-text fields. So every branch the spec requires but the real data
never reaches (negative minimums, non-empty descrip, 4D input, non-1 mm
spacing) is exercised here with synthetic volumes instead.
"""
import datetime
import importlib.util
import logging
import random
from pathlib import Path

import nibabel as nib
import numpy as np
import pydicom
import pytest
from pydicom.pixels import apply_modality_lut

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("nifti_to_dicom", HERE / "nifti_to_dicom.py")
n2d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(n2d)


def _save(tmp_path, name, data, affine=None, **header):
    img = nib.Nifti1Image(data, np.diag([-1.0, -1.0, 1.0, 1.0]) if affine is None else affine)
    for k, v in header.items():
        img.header[k] = v
    path = tmp_path / name
    nib.save(img, str(path))
    return path


def test_4d_volume_is_rejected(tmp_path):
    path = _save(tmp_path, "x_t1.nii.gz", np.zeros((4, 4, 4, 2), dtype=np.int16))
    with pytest.raises(ValueError, match="expected a 3D volume, got 4D"):
        n2d.load_volume(path)


def test_free_text_is_logged_then_cleared(tmp_path, caplog):
    path = _save(tmp_path, "x_t1.nii.gz", np.zeros((4, 4, 4), dtype=np.int16),
                 descrip=b"converted by Dr SIM for SIM HOSPITAL", aux_file=b"scan-0042")
    _, img = n2d.load_volume(path)
    with caplog.at_level(logging.WARNING, logger="nifti_to_dicom"):
        found = n2d.clear_free_text(img, "case")
    assert found == {"descrip": "converted by Dr SIM for SIM HOSPITAL", "aux_file": "scan-0042"}
    assert "converted by Dr SIM" in caplog.text and "scan-0042" in caplog.text
    assert img.header["descrip"].tobytes().strip(b"\x00") == b""
    assert img.header["aux_file"].tobytes().strip(b"\x00") == b""


def test_empty_free_text_logs_nothing(tmp_path, caplog):
    _, img = n2d.load_volume(_save(tmp_path, "x_t1.nii.gz", np.zeros((4, 4, 4), np.int16)))
    with caplog.at_level(logging.WARNING, logger="nifti_to_dicom"):
        assert n2d.clear_free_text(img, "case") == {}
    assert caplog.text == ""


def test_negative_minimum_uses_intercept_without_clipping():
    data = np.array([[[-1024, -1], [0, 32767]]], dtype=np.int16)
    stored, intercept = n2d.to_uint16(data)
    assert stored.dtype == np.uint16
    assert intercept == -1024
    assert np.array_equal(stored.astype(np.int64) + intercept, data.astype(np.int64))
    assert stored.min() == 0 and stored.max() == 32767 + 1024      # shifted, not clipped


def test_nonnegative_volume_gets_zero_intercept():
    stored, intercept = n2d.to_uint16(np.array([[[0, 5, 12299]]], dtype=np.int16))
    assert intercept == 0 and stored.tolist() == [[[0, 5, 12299]]]


def test_full_int16_range_round_trips():
    data = np.array([[[-32768, 32767]]], dtype=np.int16)
    stored, intercept = n2d.to_uint16(data)
    assert np.array_equal(stored.astype(np.int64) + intercept, data.astype(np.int64))


def test_float_volume_fails_loudly():
    with pytest.raises(NotImplementedError):
        n2d.to_uint16(np.zeros((2, 2, 2), dtype=np.float32))


def test_geometry_comes_from_the_header_not_a_1mm_assumption():
    affine = np.diag([-0.8, -0.9, 1.5, 1.0])
    affine[:3, 3] = [10.0, 20.0, -30.0]
    geo = n2d.slice_geometry(affine, (0.8, 0.9, 1.5), step=1)
    assert geo["pixel_spacing"] == [0.9, 0.8]            # [between rows, between columns]
    assert geo["slice_thickness"] == 1.5
    assert geo["spacing_between_slices"] == 1.5
    assert geo["iop"] == [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
    # RAS (10, 20, -30) at voxel 0 is LPS (-10, -20, -30); slice 4 is 6 mm superior
    assert geo["position"](0) == [-10.0, -20.0, -30.0]
    assert geo["position"](4) == [-10.0, -20.0, -24.0]


def test_subsampling_widens_spacing_but_not_thickness():
    geo = n2d.slice_geometry(np.diag([-1.0, -1.0, 1.0, 1.0]), (1.0, 1.0, 1.0), step=2)
    assert geo["slice_thickness"] == 1.0
    assert geo["spacing_between_slices"] == 2.0


def test_affine_and_zooms_that_disagree_are_rejected():
    with pytest.raises(ValueError, match="disagree"):
        n2d.slice_geometry(np.diag([-1.0, -1.0, 1.0, 1.0]), (1.0, 1.0, 2.0), step=1)


def test_non_axial_stack_is_rejected():
    sagittal = np.array([[0, 0, 1, 0], [0, 1, 0, 0], [1, 0, 0, 0], [0, 0, 0, 1]], float)
    with pytest.raises(ValueError, match="not axial"):
        n2d.slice_geometry(sagittal, (1.0, 1.0, 1.0), step=1)


def test_series_order_matches_the_model_channel_def():
    """The bundle's channel_def is 0 T1c, 1 T1, 2 T2, 3 FLAIR."""
    assert [desc for _, desc in n2d.SERIES] == ["T1C", "T1", "T2", "FLAIR"]


REAL = sorted(n2d.complete_cases()) if n2d.RAW.is_dir() else []


@pytest.mark.local_data
@pytest.mark.skipif(not REAL, reason=(
    "needs a BraTS case in data/brain/raw (not in git). NOT VERIFIED: that a real case "
    "converts to DICOM and every value round-trips"))
def test_real_case_end_to_end(tmp_path):
    case = REAL[0]
    gen = n2d._load_generator()
    when = datetime.datetime(2026, 1, 1, 7, 0, 0)
    ident = gen.make_identity(n2d.IDENTITY_OFFSET, random.Random(7), when, False)
    entries = n2d.convert_case(case, tmp_path, 2, ident, when, gen)

    series = {}
    for e in entries:
        ds = pydicom.dcmread(tmp_path / e["path"], stop_before_pixels=True)
        assert ds.SOPClassUID == "1.2.840.10008.5.1.4.1.1.4"
        assert ds.Modality == "MR"
        assert ds.StudyInstanceUID == ident["study_uid"]
        assert str(ds.PatientName).startswith("SIM^PATIENT^")
        series.setdefault((ds.SeriesNumber, ds.SeriesDescription), set()).add(
            ds.FrameOfReferenceUID)

    assert sorted(series) == [(1, "T1C"), (2, "T1"), (3, "T2"), (4, "FLAIR")]
    assert len(set().union(*series.values())) == 1          # one shared frame of reference
    assert len(entries) == 4 * len(range(0, 155, 2))        # 78 slices per series
    assert n2d.verify(entries, tmp_path) == []              # every value recovered
    assert (tmp_path / ident["study_uid"] / "ground_truth_seg.nii.gz").exists()
    assert not any(p.suffix == ".dcm" and "seg" in p.name
                   for p in (tmp_path / ident["study_uid"]).iterdir())


@pytest.mark.parametrize("low", [0, -1024])
def test_rescale_tags_only_when_needed_and_values_survive(tmp_path, low):
    """Intercept 0: no rescale tags (the classic MR IOD has no Modality LUT module).
    Negative minimum: tags present, and the saved file still restores every value."""
    gen = n2d._load_generator()
    when = datetime.datetime(2026, 1, 1, 7, 0, 0)
    ident = gen.make_identity(n2d.IDENTITY_OFFSET, random.Random(7), when, False)
    vol = np.arange(low, low + 4 * 4 * 3, dtype=np.int16).reshape(4, 4, 3)
    stored, intercept = n2d.to_uint16(vol)
    geo = n2d.slice_geometry(np.diag([-1.0, -1.0, 1.0, 1.0]), (1.0, 1.0, 1.0), step=1)
    ds = n2d.build_instance(stored[:, :, 1].T, ident, when, "SYNTH", 1, "T1C", "1.2.3.4",
                            "1.2.3.5", "1.2.3.6", 1, geo, 1, intercept,
                            n2d.window(stored, intercept), gen)
    path = tmp_path / "x.dcm"
    ds.save_as(path, enforce_file_format=True)
    back = pydicom.dcmread(path)
    assert ("RescaleIntercept" in back) == (low < 0)
    assert np.array_equal(apply_modality_lut(back.pixel_array, back), vol[:, :, 1].T)
