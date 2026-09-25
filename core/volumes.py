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


def series_to_nifti(datasets) -> nib.Nifti1Image:
    """datasets: every instance of one axial series, any order."""
    if not datasets:
        raise ValueError("empty series")
    iop = np.array(datasets[0].ImageOrientationPatient, dtype=float)
    row_dir, col_dir = iop[:3], iop[3:]
    normal = np.cross(row_dir, col_dir)

    slices = sorted(datasets, key=lambda d: float(np.dot(normal, d.ImagePositionPatient)))
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

    vol = np.stack([apply_modality_lut(d.pixel_array, d) for d in slices], axis=-1)
    vol = np.round(vol).astype(np.int16).transpose(1, 0, 2)  # (rows, cols, k) -> (i, j, k)
    return nib.Nifti1Image(vol, LPS_TO_RAS @ lps)
