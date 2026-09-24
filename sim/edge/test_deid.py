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



def _ocr_both_passes(pixels):
    """Everything OCR can read, using both passes deid.find_text_regions runs."""
    import pytesseract
    from PIL import Image
    arr = pixels
    if arr.dtype != np.uint8:
        arr = (arr.astype(np.float32) / max(float(arr.max()), 1) * 255).astype(np.uint8)
    bright = np.where(arr >= deid.BRIGHT_TEXT_THRESHOLD, 0, 255).astype(np.uint8)
    return " ".join(pytesseract.image_to_string(Image.fromarray(a)).upper()
                    for a in (arr, bright))


def test_burned_in_survives_overlapping_marker():
    """Regression, pinned to the study that exposed it.

    SIMID-000033 wraps NIH image 00000181_017.png. Its burned-in identifiers
    overlap a circled laterality "R" already in the source image, and lead wires.
    Tesseract's layout analysis returned zero regions for the entire image, so a
    legible name passed through de-identification. BRIGHT_TEXT_THRESHOLD's second
    pass exists for this image. If a re-tune loses it, this fails by name rather
    than the suite quietly dropping back to 5 of 6.

    Pinned by PatientID and source PNG, never by UID: make_dicom.py mints random
    UIDs, so a UID pin would silently stop matching after the next rebuild.
    """
    by_id = {m["patient_id"]: m for m in _load_manifest()}
    m = by_id.get("SIMID-000033")
    assert m is not None, ("corpus has no SIMID-000033; rebuild it with "
                           "data/chest/make_chest_corpus.py (count 40, seed 7)")
    assert m["source_png"] == "00000181_017.png", (
        f"SIMID-000033 now wraps {m['source_png']}; the pin no longer tests this case")
    assert m["burned_in"], "SIMID-000033 is no longer burned in; the pin tests nothing"

    ds = pydicom.dcmread(os.path.join(STUDIES, m["path"]))
    report = deid.deidentify(ds, _fresh_map())
    assert report["text_regions_masked"] > 0, "no text regions detected"

    text = _ocr_both_passes(ds.pixel_array)
    for token in ("SIMID", "PATIENT", "DOB", "0033"):
        assert token not in text, f"{token!r} still readable after masking: {text[:120]!r}"


def test_16bit_second_pass_thresholds_normalised_pixels(monkeypatch):
    """The bright pass must threshold after the uint8 normalisation.

    Raw 16-bit anatomy sits far above 250, so thresholding raw pixels would
    select almost the whole frame. This frame is a 16-bit gradient (2000 to
    32000, all above 250 raw) with text burned in at 65535 by the generator
    itself. Correct normalisation selects only the glyphs.
    """
    import pytesseract
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "generator"))
    import make_dicom

    h = w = 1024
    y, x = np.mgrid[0:h, 0:w]
    frame = (2000 + 30000 * (x + y) / (h + w)).astype(np.uint16)
    frame = make_dicom.burn_in(frame, 65535,
                               ["SIM PATIENT 9999", "SIMID-009999", "DOB 19700101"])

    seen = []
    real = pytesseract.image_to_data
    def spy(image, *a, **k):
        seen.append(np.asarray(image))
        return real(image, *a, **k)
    monkeypatch.setattr(pytesseract, "image_to_data", spy)

    masked, n = deid.mask_pixels(frame)

    assert len(seen) == 2, "expected exactly two OCR passes"
    selected = float((seen[1] == 0).mean())      # black = selected as bright text
    assert 0 < selected < 0.05, (
        f"bright pass selected {selected:.1%} of the frame; raw 16-bit thresholding?")
    changed = float((masked != frame).mean())
    assert n > 0, "burned-in text on a 16-bit frame was not detected"
    assert changed < 0.05, f"masking changed {changed:.1%} of the frame, not bounded"



def test_bright_pass_floor_keeps_low_confidence_words(monkeypatch):
    """Guards BRIGHT_PASS_MIN_CONFIDENCE without depending on the corpus.

    SIMID-000033's PatientID read at confidence 36 when the generator
    anti-aliased its glyphs. The generator now draws hard edges and that line
    reads at 89, so the corpus alone no longer exercises the floor. This feeds
    find_text_regions a controlled OCR result: a real word at confidence 36, and
    a -1 sentinel row whose text is non-empty.
    """
    import pytesseract
    calls = []

    def fake_image_to_data(image, *a, **k):
        calls.append(np.asarray(image))
        return {"level": [4, 5, 5], "text": ["", "SIMID-000033", "NOISE"],
                "conf": [-1, 36, -1], "left": [0, 10, 50], "top": [0, 20, 60],
                "width": [0, 30, 30], "height": [0, 10, 10]}

    monkeypatch.setattr(pytesseract, "image_to_data", fake_image_to_data)
    boxes = deid.find_text_regions(np.zeros((64, 64), dtype=np.uint8))

    assert len(calls) == 2, "expected the default pass and the bright pass"
    # Default pass, floor 45: drops the confidence-36 word. Bright pass, floor 0:
    # keeps it. Both drop the -1 sentinel even though its text is non-empty.
    assert boxes == [(10, 20, 30, 10)], boxes

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
