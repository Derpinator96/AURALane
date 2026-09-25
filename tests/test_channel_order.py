"""Brain channel order cannot be silently wrong. All inputs synthetic.

Four tiny MR series (2x2 pixels, 2 slices) are built with pydicom in a temp
directory, de-identified with deid.deidentify, and resolved by
adapters.brats.resolve_channels through core.pipeline._model_inputs. Each
sequence carries a distinct constant pixel value, so the NIfTI handed to the
model shows which series landed in which channel.

deidentify runs with mask_burned_in=False here: these tests cover the metadata
path (SeriesDescription). Pixel masking is covered by sim/edge/test_deid.py.
"""
import sys
from pathlib import Path

import nibabel as nib
import numpy as np
import pydicom
import pytest
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import (ComputedRadiographyImageStorage as CRImageStorage,
                         ExplicitVRLittleEndian, MRImageStorage, generate_uid)

from adapters import brats
from core.pipeline import _model_inputs
from core.registry import Registry
from core.types import SeriesMeta, StudyMeta, StudyRef

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sim" / "edge"))
import deid       # noqa: E402
import identity   # noqa: E402

pytestmark = pytest.mark.privacy
ENTRY = Registry().get("brain-brats-monai-v0.5.4")
VALUE = {"T1c": 100, "T1": 200, "T2": 300, "FLAIR": 400}


def _instance(study_uid, series_uid, number, description, value, k, modality="MR"):
    meta = FileMetaDataset()
    sop = generate_uid()
    meta.MediaStorageSOPClassUID = MRImageStorage if modality == "MR" else CRImageStorage
    meta.MediaStorageSOPInstanceUID = sop
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = Dataset()
    ds.file_meta = meta
    ds.SOPClassUID = meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = sop
    ds.StudyInstanceUID, ds.SeriesInstanceUID = study_uid, series_uid
    ds.PatientName, ds.PatientID = "SIM^PATIENT^0042", "SIMID-000042"
    ds.Modality, ds.SeriesNumber, ds.InstanceNumber = modality, number, k + 1
    ds.SeriesDescription = description
    ds.StudyDate, ds.StudyTime = "20260925", "070000"
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    ds.ImagePositionPatient = [0, 0, float(k)]
    ds.PixelSpacing, ds.SliceThickness = [1, 1], 1
    ds.Rows = ds.Columns = 2
    ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, "MONOCHROME2"
    ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 16, 15, 0
    ds.PixelData = np.full((2, 2), value, np.uint16).tobytes()
    return ds


def _study(series_spec, tmp_path, modality="MR"):
    """series_spec: [(SeriesNumber, SeriesDescription, pixel value)] -> de-identified datasets."""
    imap = identity.IdentityMap(str(tmp_path / "identity.db"))
    study = generate_uid()
    cleaned = []
    for number, description, value in series_spec:
        series = generate_uid()
        for k in range(2):
            ds = _instance(study, series, number, description, value, k, modality)
            deid.deidentify(ds, imap, mask_burned_in=False)
            cleaned.append(ds)
    return cleaned


def _meta(cleaned):
    """StudyMeta as a datastore would return it after import."""
    by_series = {}
    for ds in cleaned:
        by_series.setdefault(str(ds.SeriesInstanceUID), []).append(ds)
    series = sorted((SeriesMeta(uid, int(d[0].SeriesNumber), str(d[0].SeriesDescription),
                                len(d), tuple(str(x.SOPInstanceUID) for x in d))
                     for uid, d in by_series.items()), key=lambda s: s.number)
    uid = str(cleaned[0].StudyInstanceUID)
    return StudyMeta(StudyRef(uid, "synthetic"), "MR", "20260925", "070000",
                     tuple(series), str(cleaned[0].PatientID))


def test_shuffled_series_numbers_still_resolve_by_sequence(tmp_path):
    """Acquisition order 3,1,4,2 and variant spellings: each channel gets its own series."""
    cleaned = _study([(3, "t1 ce", VALUE["T1c"]), (1, "T1", VALUE["T1"]),
                      (4, "T2-W", VALUE["T2"]), (2, "T2 FLAIR", VALUE["FLAIR"])], tmp_path)
    inputs = _model_inputs(ENTRY, brats, cleaned, _meta(cleaned), tmp_path)

    assert list(inputs["nifti"]) == ["T1c", "T1", "T2", "FLAIR"]
    for channel, path in inputs["nifti"].items():
        data = np.asarray(nib.load(path).dataobj)
        assert data.shape == (2, 2, 2)
        assert (data == VALUE[channel]).all(), f"{channel} got pixels {np.unique(data)}"


def test_unrecognised_descriptions_raise_naming_what_is_unresolved(tmp_path):
    cleaned = _study([(1, "Ax T1 MPRAGE +C", 1), (2, "AX T1", 2),
                      (3, "T2 TSE", 3), (4, "FLAIR", 4)], tmp_path)
    with pytest.raises(ValueError) as e:
        _model_inputs(ENTRY, brats, cleaned, _meta(cleaned), tmp_path)
    msg = str(e.value)
    assert "no series identified as T1c, T1, T2" in msg
    assert "unrecognised series: 1 'TRIAGE SERIES', 2 'TRIAGE SERIES', 3 'TRIAGE SERIES'" in msg
    assert "Refusing to guess" in msg


def test_two_series_claiming_one_channel_raise(tmp_path):
    cleaned = _study([(1, "T1", 1), (2, "T1W", 2), (3, "T2", 3), (4, "FLAIR", 4)], tmp_path)
    with pytest.raises(ValueError, match=r"no series identified as T1c.*more than one series "
                                         r"for T1 \(series \[1, 2\]\)"):
        _model_inputs(ENTRY, brats, cleaned, _meta(cleaned), tmp_path)


@pytest.mark.parametrize("description", ["SMITH T1", "T1 SMITH", "T1^SMITH^JOHN", "T1 (J. Smith)"])
def test_description_containing_a_name_is_dummied(tmp_path, description):
    ds = _study([(1, description, 1)], tmp_path)[0]
    assert ds.SeriesDescription == deid.DUMMY_VALUES["SeriesDescription"]
    assert not any("SMITH" in str(e.value).upper() for e in ds.iterall()
                   if isinstance(e.value, (str, pydicom.valuerep.PersonName)))


@pytest.mark.parametrize("description, token", [
    ("T1", "T1"), ("t1-ce", "T1C"), ("T1 Gd", "T1C"), ("T2", "T2"),
    ("t2 flair", "FLAIR"), ("T2F", "FLAIR"), ("FLAIR", "FLAIR"), ("T1N", "T1")])
def test_known_sequence_names_become_canonical_tokens(tmp_path, description, token):
    assert _study([(1, description, 1)], tmp_path)[0].SeriesDescription == token


def test_cr_study_is_not_touched_by_the_mr_vocabulary(tmp_path):
    ds = _study([(1, "T1", 1)], tmp_path, modality="CR")[0]
    assert ds.SeriesDescription == deid.DUMMY_VALUES["SeriesDescription"]
    assert deid.mr_sequence_token(ds) is None
