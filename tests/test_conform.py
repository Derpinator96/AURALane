"""Real DICOM sources leave things out that STOW-RS wants. core.pipeline._conform fills in what the file
itself already says."""
import datetime
import random

import numpy as np
import pydicom

from core.pipeline import _conform
from sim.generator import make_dicom as md


def _ct_file(tmp_path):
    when = datetime.datetime(2026, 1, 1)
    ds = md.build_instance(np.full((8, 8), 7, np.uint8), 255,
                           md.make_identity(1, random.Random(1), when, False), when, "a test")
    ds.Modality = "CT"
    path = tmp_path / "ct.dcm"
    ds.save_as(path, enforce_file_format=True)
    return path


def test_a_file_with_the_sop_class_only_in_its_meta_gets_it_in_the_dataset(tmp_path):
    """The RSNA head CTs: Orthanc's STOW-RS rejects an instance without SOPClassUID in the dataset."""
    path = _ct_file(tmp_path)
    ds = pydicom.dcmread(path)
    want = str(ds.SOPClassUID)
    del ds.SOPClassUID
    assert "SOPClassUID" not in ds and str(ds.file_meta.MediaStorageSOPClassUID) == want
    _conform(ds)
    assert str(ds.SOPClassUID) == want
    other = pydicom.dcmread(path)
    other.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    _conform(other)                                   # one already there is left alone
    assert str(other.SOPClassUID) == "1.2.840.10008.5.1.4.1.1.2"
