"""De-identification tests. No Docker, no AWS -- run these first.

    python -m pytest test_deid.py -v
    python test_deid.py              # same checks, plain output

These are the checks that decide whether the privacy claim on the slide is
true. If any of them fail, nothing downstream matters.
"""
import json
import os
import sys
import tempfile

import numpy as np
import pydicom

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deid          # noqa: E402
import identity      # noqa: E402

STUDIES = os.environ.get("SIM_STUDIES", "../data/studies")

# Attributes that must not survive with their original value. Split by the
# PS3.15 action that applies, because "gone" means different things:
#   blanked  -> present but empty (required attributes)
#   removed  -> absent entirely
#   replaced -> present, but a pseudonym, never the original
MUST_BE_BLANK = ["PatientBirthDate", "ReferringPhysicianName", "StudyID"]
MUST_BE_ABSENT = ["InstitutionName", "StationName", "PatientComments",
                  "DerivationDescription", "ManufacturerModelName"]
MUST_BE_REPLACED = ["PatientName", "PatientID", "AccessionNumber"]


def _load_manifest():
    with open(os.path.join(STUDIES, "manifest.json")) as f:
        return json.load(f)


def _fresh_map():
    path = os.path.join(tempfile.mkdtemp(), "identity.db")
    return identity.IdentityMap(path)


def _ocr_text(pixels):
    import pytesseract
    from PIL import Image
    strip = pixels[: pixels.shape[0] // 4, :]
    if strip.dtype != np.uint8:
        strip = (strip.astype(np.float32) / max(float(strip.max()), 1)
                 * 255).astype(np.uint8)
    return pytesseract.image_to_string(Image.fromarray(strip)).upper()


# --------------------------------------------------------------------------

def test_metadata_is_stripped():
    """No original identifier survives in the header."""
    imap = _fresh_map()
    for m in _load_manifest():
        ds = pydicom.dcmread(os.path.join(STUDIES, m["path"]))
        deid.deidentify(ds, imap)

        for kw in MUST_BE_BLANK:
            v = getattr(ds, kw, "")
            assert not str(v), f"{kw} should be zero-length, got {v!r}"
        for kw in MUST_BE_ABSENT:
            assert kw not in ds, f"{kw} should have been removed"
        assert str(ds.PatientName) != m["patient_name"]
        assert str(ds.PatientID) != m["patient_id"]
        assert str(ds.AccessionNumber) != m["accession"]
        # Replaced, not emptied -- a worklist row needs something to show.
        assert str(ds.AccessionNumber), "accession must carry a pseudonym"
        assert ds.PatientIdentityRemoved == "YES"


def test_uids_are_remapped_and_consistent():
    """Study structure survives: same original UID always yields the same new one."""
    imap = _fresh_map()
    seen = {}
    for m in _load_manifest():
        ds = pydicom.dcmread(os.path.join(STUDIES, m["path"]))
        deid.deidentify(ds, imap)
        assert ds.StudyInstanceUID != m["study_uid"]
        assert ds.SeriesInstanceUID != m["series_uid"]
        assert ds.SOPInstanceUID != m["sop_uid"]
        # file_meta must agree with the dataset or the object is invalid
        assert ds.file_meta.MediaStorageSOPInstanceUID == ds.SOPInstanceUID
        seen[m["study_uid"]] = ds.StudyInstanceUID

    # Re-running must produce identical mappings, not fresh ones.
    for m in _load_manifest():
        ds = pydicom.dcmread(os.path.join(STUDIES, m["path"]))
        deid.deidentify(ds, imap)
        assert ds.StudyInstanceUID == seen[m["study_uid"]], \
            "UID mapping is not stable -- a study would split downstream"


def test_burned_in_text_is_masked():
    """Identifiers rendered into the pixels are gone from the pixels."""
    imap = _fresh_map()
    checked = 0
    for m in _load_manifest():
        if not m["burned_in"]:
            continue
        ds = pydicom.dcmread(os.path.join(STUDIES, m["path"]))
        before = ds.pixel_array.copy()
        report = deid.deidentify(ds, imap)
        after = ds.pixel_array

        assert report["text_regions_masked"] > 0, "no text regions detected"
        assert (before != after).any(), "pixels unchanged despite masking"

        text = _ocr_text(after)
        assert "SIM" not in text and "SIMID" not in text, \
            f"burned-in identifier survived masking: {text[:80]!r}"
        checked += 1
    assert checked, "manifest contained no burned-in studies to check"


def test_clean_images_are_not_damaged():
    """Masking must not touch images that carry no text."""
    imap = _fresh_map()
    for m in _load_manifest():
        if m["burned_in"]:
            continue
        ds = pydicom.dcmread(os.path.join(STUDIES, m["path"]))
        before = ds.pixel_array.copy()
        deid.deidentify(ds, imap)
        changed = int((before != ds.pixel_array).sum())
        # A few stray OCR hits on noise are tolerable; wholesale damage is not.
        assert changed < before.size * 0.02, \
            f"{changed} pixels altered on a clean image -- masking is too eager"


def test_identity_is_resolvable_locally():
    """A pseudonym resolves back to the original, in-hospital only."""
    imap = _fresh_map()
    m = _load_manifest()[0]
    ds = pydicom.dcmread(os.path.join(STUDIES, m["path"]))
    report = deid.deidentify(ds, imap)

    resolved = imap.resolve_study(report["pseudo_study_uid"])
    assert resolved is not None
    assert resolved["patient_name"] == m["patient_name"]
    assert resolved["patient_id"] == m["patient_id"]
    assert resolved["accession"] == m["accession"]

    assert imap.resolve_study("1.2.3.4.not.a.real.uid") is None


def test_private_and_overlay_tags_are_removed():
    """Vendors put anything in private tags, including names."""
    imap = _fresh_map()
    m = _load_manifest()[0]
    ds = pydicom.dcmread(os.path.join(STUDIES, m["path"]))
    block = ds.private_block(0x000B, "ACME SECRET", create=True)
    block.add_new(0x01, "LO", "SMITH^JOHN")
    ds.add_new(0x60003000, "OW", b"\x00" * 16)      # overlay data

    deid.deidentify(ds, imap)

    assert not any(e.tag.is_private for e in ds), "private tags survived"
    assert 0x60003000 not in ds, "overlay data survived"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_"):
            continue
        try:
            fn()
            print(f"PASS  {name}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL  {name}\n      {e}")
        except Exception as e:
            failures += 1
            print(f"ERROR {name}\n      {type(e).__name__}: {e}")
    print()
    print("ALL PASS" if not failures else f"{failures} FAILED")
    sys.exit(1 if failures else 0)
