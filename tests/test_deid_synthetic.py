"""The metadata half of the privacy suite, on synthetic instances.

sim/edge/test_deid.py checks these properties against the 40-study NIH corpus,
which is not in git and skips without it. These build CR instances with
sim/generator/make_dicom.py's own functions in a temp directory, so the header
claims are verified on every run. Pixel masking stays with the corpus tests and
tests/test_parallel_ocr.py; here deidentify runs with mask_burned_in=False.
"""
import datetime
import random
import sys
from pathlib import Path

import numpy as np
import pydicom
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sim" / "edge"))
sys.path.insert(0, str(ROOT / "sim" / "generator"))
import deid         # noqa: E402
import identity     # noqa: E402
import make_dicom   # noqa: E402

pytestmark = pytest.mark.privacy


def _instances(n=3, same_study=False):
    when = datetime.datetime(2026, 9, 25, 7, 0, 0)
    rng = random.Random(11)
    first = None
    out = []
    for i in range(n):
        ident = make_dicom.make_identity(200 + i, rng, when, False)
        if same_study and first:
            ident["study_uid"], ident["patient_id"] = first["study_uid"], first["patient_id"]
            ident["patient_name"] = first["patient_name"]
        first = first or ident
        ds = make_dicom.build_instance(np.full((4, 4), 60, np.uint8), 255, ident, when, "synthetic")
        ds.OtherPatientIDs = "OTHER-ID-9"
        out.append((ds, ident))
    return out


def test_header_identifiers_do_not_survive(tmp_path):
    imap = identity.IdentityMap(str(tmp_path / "i.db"))
    for ds, ident in _instances():
        deid.deidentify(ds, imap, mask_burned_in=False)
        for kw in ("PatientBirthDate", "ReferringPhysicianName", "StudyID"):
            assert not str(getattr(ds, kw, "")), kw
        for kw in ("InstitutionName", "StationName", "PatientComments",
                   "DerivationDescription", "ManufacturerModelName", "OtherPatientIDs"):
            assert kw not in ds, kw
        assert str(ds.PatientName) != ident["patient_name"]
        assert str(ds.PatientID) != ident["patient_id"]
        assert str(ds.AccessionNumber) not in ("", ident["accession"])
        values = " ".join(str(e.value) for e in ds.iterall() if e.VR in ("PN", "LO", "SH"))
        assert ident["patient_id"] not in values and "SIM^PATIENT" not in values
        assert ds.PatientIdentityRemoved == "YES"


def test_uids_remap_consistently_so_a_study_stays_one_study(tmp_path):
    imap = identity.IdentityMap(str(tmp_path / "i.db"))
    batch = _instances(n=3, same_study=True)
    originals = {str(ds.StudyInstanceUID) for ds, _ in batch}
    for ds, _ in batch:
        deid.deidentify(ds, imap, mask_burned_in=False)
    remapped = {str(ds.StudyInstanceUID) for ds, _ in batch}
    assert len(originals) == len(remapped) == 1 and remapped != originals

    again = _instances(n=1, same_study=False)[0][0]
    again.StudyInstanceUID = originals.pop()
    deid.deidentify(again, imap, mask_burned_in=False)
    assert str(again.StudyInstanceUID) == remapped.pop(), "same original, different pseudonym"


def test_pseudonym_resolves_back_only_through_the_local_map(tmp_path):
    imap = identity.IdentityMap(str(tmp_path / "i.db"))
    ds, ident = _instances(n=1)[0]
    deid.deidentify(ds, imap, mask_burned_in=False)
    resolved = imap.resolve_study(str(ds.StudyInstanceUID))
    assert resolved is not None
    assert ident["patient_id"] in str(resolved.values())


def test_private_and_overlay_tags_are_removed(tmp_path):
    ds, _ = _instances(n=1)[0]
    block = ds.private_block(0x000B, "ACME SECRET", create=True)
    block.add_new(0x01, "LO", "SMITH^JOHN")
    ds.add_new(0x60003000, "OW", b"\x00" * 16)
    deid.deidentify(ds, identity.IdentityMap(str(tmp_path / "i.db")), mask_burned_in=False)
    assert not any(e.tag.is_private for e in ds)
    assert 0x60003000 not in ds
    path = tmp_path / "out.dcm"
    ds.save_as(path, enforce_file_format=True)
    assert "SMITH" not in path.read_bytes().decode("latin-1")
