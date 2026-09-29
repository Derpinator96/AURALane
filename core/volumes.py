"""DICOM MR series -> NIfTI volume, the inverse of data/brain/nifti_to_dicom.py.

The brain model reads NIfTI. The datastore holds DICOM. This rebuilds each
series as a volume on the original grid:

    pixel (row r, column c) of axial slice k  ->  voxel (i=c, j=r, k)
    affine from ImageOrientationPatient, PixelSpacing and the slice positions,
    in DICOM LPS+, flipped to NIfTI RAS+
    values through the modality LUT (stored + RescaleIntercept)

tests/test_volumes.py checks values and affine against the source NIfTI.
"""
from __future__ import annotations

import numpy as np
import nibabel as nib
from pydicom.pixels import apply_modality_lut

LPS_TO_RAS = np.diag([-1.0, -1.0, 1.0, 1.0])


def sort_slices(datasets) -> list:
    """Instances of one axial series in voxel k order: position along the slice normal."""
    iop = np.array(datasets[0].ImageOrientationPatient, dtype=float)
    normal = np.cross(iop[:3], iop[3:])
    return sorted(datasets, key=lambda d: float(np.dot(normal, d.ImagePositionPatient)))


def series_to_nifti(datasets, pixels=None) -> nib.Nifti1Image:
    """datasets: every instance of one axial series, any order. pixels(ds), when
    given, supplies each instance's stored pixel values (headers read from a
    datastore carry no pixel data)."""
    if not datasets:
        raise ValueError("empty series")
    iop = np.array(datasets[0].ImageOrientationPatient, dtype=float)
    row_dir, col_dir = iop[:3], iop[3:]
    normal = np.cross(row_dir, col_dir)

    slices = sort_slices(datasets)
    pos = np.array([d.ImagePositionPatient for d in slices], dtype=float)
    if len(slices) > 1:
        steps = np.diff(pos, axis=0)
        if not np.allclose(steps, steps[0], atol=1e-3):
            raise ValueError("slice positions are not evenly spaced")
        step = steps[0]
        thickness = float(slices[0].SliceThickness)
        if not np.isclose(np.linalg.norm(step), thickness, atol=1e-3):
            raise ValueError(f"slices are {np.linalg.norm(step):.3f} mm apart but "
                             f"{thickness} mm thick: the series is subsampled, and the "
                             f"model expects every slice (nifti_to_dicom.py --slices 1)")
    else:
        step = normal * float(slices[0].SliceThickness)

    dr, dc = (float(x) for x in slices[0].PixelSpacing)      # between rows, between columns
    lps = np.eye(4)
    lps[:3, 0] = row_dir * dc          # voxel i runs along a row (column index)
    lps[:3, 1] = col_dir * dr          # voxel j runs down a column (row index)
    lps[:3, 2] = step
    lps[:3, 3] = pos[0]

    vol = np.stack([apply_modality_lut(pixels(d) if pixels else d.pixel_array, d)
                    for d in slices], axis=-1)
    vol = np.round(vol).astype(np.int16).transpose(1, 0, 2)  # (rows, cols, k) -> (i, j, k)
    return nib.Nifti1Image(vol, LPS_TO_RAS @ lps)


def ct_volume_bytes(datasets, pixels=None) -> bytes:
    """A head CT study -> gzip NIfTI (int16 Hounsfield units), for the 3D viewer.

    Takes the axial series with the most slices, sorts by position along the slice
    normal and uses the median spacing, so a slightly uneven series still renders
    (this is for looking at, not measuring: the models read the DICOM, not this).
    pixels(ds), when given, supplies each instance's stored pixels (headers read
    from a datastore carry none).
    """
    import os
    import tempfile
    by_series: dict[str, list] = {}
    for d in datasets:
        if hasattr(d, "ImageOrientationPatient") and hasattr(d, "ImagePositionPatient"):
            by_series.setdefault(str(getattr(d, "SeriesInstanceUID", "")), []).append(d)
    if not by_series:
        raise ValueError("no positioned axial images")
    series = max(by_series.values(), key=len)
    slices = sort_slices(series)
    iop = np.array(slices[0].ImageOrientationPatient, dtype=float)
    row_dir, col_dir = iop[:3], iop[3:]
    normal = np.cross(row_dir, col_dir)
    pos = np.array([d.ImagePositionPatient for d in slices], dtype=float)
    if len(slices) > 1:
        along = pos @ normal
        step = normal * float(np.median(np.diff(along)))
    else:
        step = normal * float(getattr(slices[0], "SliceThickness", 1.0))
    dr, dc = (float(x) for x in slices[0].PixelSpacing)
    lps = np.eye(4)
    lps[:3, 0] = row_dir * dc
    lps[:3, 1] = col_dir * dr
    lps[:3, 2] = step
    lps[:3, 3] = pos[0]
    get = pixels or (lambda d: d.pixel_array)
    shape = get(slices[0]).shape
    vol = np.stack([apply_modality_lut(get(d), d) for d in slices if get(d).shape == shape],
                   axis=-1)
    vol = np.clip(np.round(vol), -1024, 3071).astype(np.int16).transpose(1, 0, 2)
    img = nib.Nifti1Image(vol, LPS_TO_RAS @ lps)
    fd, tmp = tempfile.mkstemp(suffix=".nii.gz")
    os.close(fd)
    try:
        nib.save(img, tmp)
        with open(tmp, "rb") as f:
            return f.read()
    finally:
        os.unlink(tmp)
