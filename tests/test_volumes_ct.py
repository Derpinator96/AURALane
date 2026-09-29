"""Head CT -> NIfTI for the 3D viewer (core/volumes.ct_volume_bytes)."""
import gzip
import io
from pathlib import Path

import nibabel as nib
import numpy as np
import pydicom
import pytest

from core.volumes import ct_volume_bytes

POOL = Path(__file__).resolve().parents[1] / "data" / "pool" / "ct"


def _study():
    dirs = sorted(POOL.iterdir()) if POOL.is_dir() else []
    if not dirs:
        pytest.skip("no staged CT study (scripts/stage_pool.py --local)")
    return [pydicom.dcmread(p) for p in sorted(dirs[0].rglob("*.dcm"))]


def test_ct_volume_has_one_voxel_layer_per_slice_in_hounsfield_units():
    ds = _study()
    raw = ct_volume_bytes(ds)
    assert raw[:2] == b"\x1f\x8b"                         # gzip, as the viewer loads it
    img = nib.Nifti1Image.from_bytes(gzip.decompress(raw))
    n = len({str(d.SeriesInstanceUID) for d in ds if hasattr(d, "ImagePositionPatient")})
    assert img.shape[2] >= 1 and img.shape[:2] == (ds[0].Columns, ds[0].Rows)
    data = np.asarray(img.dataobj)
    assert data.min() >= -1024 and data.max() <= 3071 and data.max() > 0
    assert n >= 1


def test_ct_volume_refuses_images_with_no_position():
    ds = _study()[0]
    del ds.ImagePositionPatient
    with pytest.raises(ValueError):
        ct_volume_bytes([ds])
