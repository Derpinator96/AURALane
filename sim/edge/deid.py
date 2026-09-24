"""On-premise de-identification. Runs before anything leaves the hospital.

Two separate problems with one name.

METADATA. DICOM carries identity in header attributes. DICOM PS3.15 Annex E
defines the Basic Application Level Confidentiality Profile: a table of
attributes with an action for each. The actions are

    X  remove the attribute entirely
    Z  replace with a zero-length value (the attribute is required to exist,
       so deleting it would produce invalid DICOM)
    D  replace with a non-zero dummy value
    U  replace with a new UID, consistently

That last distinction is why this is not a delete-these-tags loop. Drop a
required Type 1 attribute and viewers reject the object; remap UIDs
inconsistently and a study's instances scatter into separate studies.

PIXELS. Some images carry the patient's name rendered INTO the picture --
ultrasound, secondary captures, scanned film, screenshots from old
workstations. Stripping tags does nothing to those pixels. DICOM has a tag,
BurnedInAnnotation, that is supposed to declare it, and it is frequently
absent or wrong, so we never trust it and OCR every image.

Be honest about the limit: OCR-based masking is high-recall, not perfect, and
the failure mode is a name surviving into a de-identified store. This is why
chest X-ray -- which almost never carries burned-in identifiers -- is the
first modality, and why a modality-by-modality rollout with human review
sampling is the right deployment posture.

NOT A DIAGNOSTIC DEVICE.
"""
import datetime
import logging

import numpy as np
from PIL import Image

log = logging.getLogger("deid")

# -- PS3.15 Annex E actions -------------------------------------------------
#
# A working subset of the confidentiality profile covering the attributes that
# actually appear in CR/CT/MR objects from real modalities. Not the complete
# table -- the full one runs to several hundred rows including retired
# attributes -- but every attribute below carries its standard action, and
# anything not listed is handled by the sweep rules further down.

REMOVE = "X"       # delete the attribute
BLANK = "Z"        # zero-length value, attribute must remain present
DUMMY = "D"        # replaced with a non-zero dummy
REMAP_UID = "U"    # new UID, consistent across the whole study

ACTIONS = {
    # --- direct identifiers ---
    "PatientName": DUMMY,
    "PatientID": DUMMY,
    "OtherPatientIDs": REMOVE,
    "OtherPatientNames": REMOVE,
    "OtherPatientIDsSequence": REMOVE,
    "PatientBirthName": REMOVE,
    "PatientMotherBirthName": REMOVE,
    "PatientBirthDate": BLANK,
    "PatientBirthTime": REMOVE,
    "PatientAddress": REMOVE,
    "PatientTelephoneNumbers": REMOVE,
    "PatientTelecomInformation": REMOVE,
    "PatientReligiousPreference": REMOVE,
    "PatientInsurancePlanCodeSequence": REMOVE,
    "MilitaryRank": REMOVE,
    "BranchOfService": REMOVE,
    "MedicalRecordLocator": REMOVE,
    "CountryOfResidence": REMOVE,
    "RegionOfResidence": REMOVE,
    "EthnicGroup": REMOVE,
    "Occupation": REMOVE,
    "PatientComments": REMOVE,

    # --- care team ---
    "ReferringPhysicianName": BLANK,
    "ReferringPhysicianAddress": REMOVE,
    "ReferringPhysicianTelephoneNumbers": REMOVE,
    "ReferringPhysicianIdentificationSequence": REMOVE,
    "PerformingPhysicianName": REMOVE,
    "PerformingPhysicianIdentificationSequence": REMOVE,
    "PhysiciansOfRecord": REMOVE,
    "PhysiciansOfRecordIdentificationSequence": REMOVE,
    "NameOfPhysiciansReadingStudy": REMOVE,
    "PhysiciansReadingStudyIdentificationSequence": REMOVE,
    "RequestingPhysician": REMOVE,
    "OperatorsName": REMOVE,
    "OperatorIdentificationSequence": REMOVE,
    "ResponsiblePerson": REMOVE,
    "ResponsibleOrganization": REMOVE,

    # --- institution / equipment ---
    "InstitutionName": REMOVE,
    "InstitutionAddress": REMOVE,
    "InstitutionalDepartmentName": REMOVE,
    "InstitutionCodeSequence": REMOVE,
    # Device identity. PS3.15 defines a "Retain Device Identity Option"
    # (113109) that keeps these, because vendor and model genuinely affect
    # image characteristics. We do NOT enable it: a station name is often the
    # room, the room is often the department, and that narrows a patient
    # population fast. Removed by default; enable the option deliberately if a
    # study needs it.
    "StationName": REMOVE,
    "Manufacturer": REMOVE,
    "ManufacturerModelName": REMOVE,
    "SoftwareVersions": REMOVE,
    "DeviceSerialNumber": REMOVE,
    "DeviceUID": REMOVE,
    "PlateID": REMOVE,
    "GantryID": REMOVE,
    "DetectorID": REMOVE,

    # --- order / accession ---
    "AccessionNumber": DUMMY,
    "StudyID": BLANK,
    "RequestAttributesSequence": REMOVE,
    "RequestedProcedureID": REMOVE,
    "RequestedProcedureDescription": REMOVE,
    "PerformedProcedureStepID": REMOVE,
    "PerformedProcedureStepDescription": REMOVE,
    "ScheduledProcedureStepID": REMOVE,
    "ScheduledProcedureStepDescription": REMOVE,
    "FillerOrderNumberImagingServiceRequest": REMOVE,
    "PlacerOrderNumberImagingServiceRequest": REMOVE,
    "IssuerOfPatientID": REMOVE,
    "IssuerOfAccessionNumberSequence": REMOVE,
    "AdmissionID": REMOVE,
    "IssuerOfAdmissionID": REMOVE,
    "CurrentPatientLocation": REMOVE,

    # --- free text that routinely leaks identity ---
    "StudyDescription": DUMMY,
    "SeriesDescription": DUMMY,
    "ImageComments": REMOVE,
    "AdditionalPatientHistory": REMOVE,
    "PatientState": REMOVE,
    "AdmittingDiagnosesDescription": REMOVE,
    "AdmittingDiagnosesCodeSequence": REMOVE,
    "DerivationDescription": REMOVE,
    "ContentSequence": REMOVE,
    "TextComments": REMOVE,

    # --- UIDs: remapped, never deleted ---
    "StudyInstanceUID": REMAP_UID,
    "SeriesInstanceUID": REMAP_UID,
    "SOPInstanceUID": REMAP_UID,
    "MediaStorageSOPInstanceUID": REMAP_UID,
    "FrameOfReferenceUID": REMAP_UID,
    "SynchronizationFrameOfReferenceUID": REMAP_UID,
    "IrradiationEventUID": REMAP_UID,
    "ConcatenationUID": REMAP_UID,
    "StorageMediaFileSetUID": REMAP_UID,
    "ReferencedSOPInstanceUID": REMAP_UID,
    "SourceImageSequence": REMAP_UID,
    "ReferencedImageSequence": REMAP_UID,
    "ReferencedStudySequence": REMOVE,
    "ReferencedPatientSequence": REMOVE,
}

# Kept deliberately. These are clinical, not identifying, and removing them
# would make the study useless for triage.
KEEP = {
    "Modality", "BodyPartExamined", "ViewPosition", "PatientOrientation",
    "PatientSex", "PatientAge", "Rows", "Columns", "BitsAllocated",
    "BitsStored", "HighBit", "PixelRepresentation", "PhotometricInterpretation",
    "SamplesPerPixel", "PixelData", "WindowCenter", "WindowWidth",
    "RescaleIntercept", "RescaleSlope", "PixelSpacing", "ImagerPixelSpacing",
    "SOPClassUID", "TransferSyntaxUID", "SeriesNumber", "InstanceNumber",
    "ImageType", "KVP", "Exposure", "XRayTubeCurrent",
}

DUMMY_VALUES = {
    "PatientName": "ANONYMIZED",
    "PatientID": "ANONYMIZED",
    "AccessionNumber": "ANONYMIZED",
    "StudyDescription": "TRIAGE STUDY",
    "SeriesDescription": "TRIAGE SERIES",
}

# PS3.15 CID 7050 codes describing what was applied. A de-identified object is
# required to say how it was de-identified -- a receiving system needs to know
# whether it can trust the result.
DEID_METHODS = [
    "113100",  # Basic Application Confidentiality Profile
    "113101",  # Clean Pixel Data Option
    "113105",  # Clean Descriptors Option
    "113107",  # Retain Longitudinal Temporal Information Modified Dates
]


# -- pixel masking ----------------------------------------------------------

# Second detection pass. Tesseract's layout analysis fails when burned-in text
# overlaps existing bright markers (a circled laterality "R", lead wires) and
# returns zero regions for the entire image. Isolating near-maximum pixels and
# inverting gives it clean black-on-white glyphs with the anatomy removed.
#
# Tuned to text burned at or near maximum intensity, which is what our generator
# produces and what most modality overlays produce. Real burned-in text can be
# anti-aliased below this. That is why OCR masking is high-recall rather than
# complete, and why modality-by-modality rollout with human review sampling is
# the deployment posture.
BRIGHT_TEXT_THRESHOLD = 250

# The default pass keeps a 45 floor: it sees full anatomy and a low-confidence
# hit there is usually texture.
# The bright pass has already filtered to near-maximum pixels, so anything
# Tesseract reads there is a bright glyph. Measured across 40 studies: a floor
# of 30 or lower leaves 0 of 6 identifiers readable. SIMID-000033 read at
# confidence 36 because the circled laterality "R" overlaps the line. That was
# with anti-aliased glyphs; make_dicom.burn_in now draws hard edges and the same
# line reads at 89, so test_deid.py guards this floor with a controlled OCR
# result as well as the corpus.
# -1 is the sentinel for non-word rows, so the floor is 0 rather than absent.
BRIGHT_PASS_MIN_CONFIDENCE = 0


class OCRUnavailable(RuntimeError):
    """Tesseract (the binary or the pytesseract package) is not usable.

    Raised rather than logged. Returning no regions here would let every study
    through with burned-in identifiers intact, which is the one failure this
    module exists to prevent. A study that cannot be masked is not
    de-identified.
    """


def find_text_regions(pixels, min_confidence=45):
    """Locate burned-in text. Returns boxes as (x, y, w, h).

    We OCR every image regardless of what BurnedInAnnotation claims, because
    that tag is unreliable in the field.
    """
    try:
        import pytesseract
    except ImportError as e:
        raise OCRUnavailable(f"pytesseract package not installed: {e}") from e

    arr = pixels
    if arr.dtype != np.uint8:
        top = float(arr.max()) or 1.0
        arr = (arr.astype(np.float32) / top * 255).astype(np.uint8)

    # Must threshold `arr` here, AFTER the normalisation above, never the raw
    # pixels: against raw 16-bit data, >= 250 would select almost the whole
    # frame. test_deid.py feeds a 16-bit image to hold this in place.
    bright = np.where(arr >= BRIGHT_TEXT_THRESHOLD, 0, 255).astype(np.uint8)

    # Union of both passes. A region found twice is padded twice when masked,
    # which is harmless, so no merge step.
    boxes = []
    for image, floor in ((arr, min_confidence), (bright, BRIGHT_PASS_MIN_CONFIDENCE)):
        try:
            data = pytesseract.image_to_data(
                Image.fromarray(image), output_type=pytesseract.Output.DICT)
        except pytesseract.TesseractNotFoundError as e:
            raise OCRUnavailable(f"tesseract binary not found: {e}") from e
        # Any other OCR error propagates. deidentify refuses to forward on it.

        for i, text in enumerate(data["text"]):
            if not text.strip():
                continue
            try:
                conf = float(data["conf"][i])
            except (TypeError, ValueError):
                continue
            if conf < floor:
                continue
            boxes.append((data["left"][i], data["top"][i],
                          data["width"][i], data["height"][i]))
    return boxes


def mask_pixels(pixels, pad=6):
    """Black out every detected text region. Returns (pixels, n_masked)."""
    boxes = find_text_regions(pixels)
    if not boxes:
        return pixels, 0

    out = pixels.copy()
    h, w = out.shape[:2]
    for (x, y, bw, bh) in boxes:
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(w, x + bw + pad), min(h, y + bh + pad)
        out[y0:y1, x0:x1] = 0
    return out, len(boxes)


# -- metadata ---------------------------------------------------------------

def _walk(ds, identity, removed, remapped):
    """Apply the action table to one dataset, recursing into sequences."""
    for elem in list(ds):
        kw = elem.keyword

        # Private tags are unstandardised by definition -- vendors put
        # anything in them, including identifiers. Remove all of them.
        if elem.tag.is_private:
            removed.append(f"(private {elem.tag})")
            del ds[elem.tag]
            continue

        # Curve and overlay planes can carry rendered annotations, which means
        # they can carry names. Group 0x50xx and 0x60xx go entirely.
        group = elem.tag.group
        if 0x5000 <= group <= 0x50FF or 0x6000 <= group <= 0x60FF:
            removed.append(f"(overlay {elem.tag})")
            del ds[elem.tag]
            continue

        action = ACTIONS.get(kw)

        if elem.VR == "SQ":
            if action == REMOVE:
                removed.append(kw)
                del ds[elem.tag]
            else:
                for item in elem.value:
                    _walk(item, identity, removed, remapped)
            continue

        if elem.VR == "UI" and action == REMAP_UID:
            if elem.value:
                elem.value = identity.map_uid(str(elem.value))
                remapped.append(kw)
            continue

        if action == REMOVE:
            removed.append(kw)
            del ds[elem.tag]
        elif action == BLANK:
            elem.value = ""
            removed.append(kw)
        elif action == DUMMY:
            elem.value = DUMMY_VALUES.get(kw, "ANONYMIZED")
            removed.append(kw)
        elif kw in KEEP or action is None:
            continue


def deidentify(ds, identity, mask_burned_in=True, allow_unmasked: bool = False):
    """De-identify one instance in place. Returns a report dict.

    Order matters: capture the originals for the identity map BEFORE the
    attributes are destroyed.

    Raises OCRUnavailable if burned-in text cannot be searched for. The caller
    must treat the study as not de-identified and stop.

    allow_unmasked=True lets a study continue without pixel masking when OCR is
    unavailable. Only for a caller that has established the modality carries no
    burned-in text. It is logged at ERROR level every time it takes effect.
    """
    original = {
        "patient_id": str(getattr(ds, "PatientID", "") or ""),
        "patient_name": str(getattr(ds, "PatientName", "") or ""),
        "birth_date": str(getattr(ds, "PatientBirthDate", "") or ""),
        "sex": str(getattr(ds, "PatientSex", "") or ""),
        "study_uid": str(getattr(ds, "StudyInstanceUID", "") or ""),
        "accession": str(getattr(ds, "AccessionNumber", "") or ""),
        "study_date": str(getattr(ds, "StudyDate", "") or ""),
    }

    pseudo_patient = identity.map_patient(
        original["patient_id"], original["patient_name"],
        original["birth_date"], original["sex"])
    pseudo_study = identity.map_uid(original["study_uid"])
    pseudo_accession = identity.record_study(
        original["study_uid"], pseudo_study, original["patient_id"],
        original["accession"], original["study_date"])

    # --- pixels first, while the array is still easy to reach -------------
    masked = 0
    if mask_burned_in and "PixelData" in ds:
        try:
            arr = ds.pixel_array
            cleaned, masked = mask_pixels(arr)
            if masked:
                ds.PixelData = cleaned.astype(arr.dtype).tobytes()
        except OCRUnavailable as e:
            if not allow_unmasked:
                raise
            log.error("OCR UNAVAILABLE, PIXELS NOT MASKED (allow_unmasked=True) "
                      "for study %s: %s", original["study_uid"], e)
        except Exception as e:
            # Never let a pixel problem cause identified data to pass through.
            raise RuntimeError(f"pixel masking failed, refusing to forward: {e}")

    # --- metadata ---------------------------------------------------------
    removed, remapped = [], []
    _walk(ds, identity, removed, remapped)

    # Pseudonyms the hospital can resolve locally.
    ds.PatientID = pseudo_patient
    ds.PatientName = pseudo_patient
    ds.AccessionNumber = pseudo_accession

    if ds.file_meta is not None:
        ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID

    # PS3.15 requires a de-identified object to declare itself as one.
    ds.PatientIdentityRemoved = "YES"
    ds.DeidentificationMethod = "AURALANE PS3.15 BASIC + CLEAN PIXEL DATA"
    ds.LongitudinalTemporalInformationModified = "UNMODIFIED"
    ds.BurnedInAnnotation = "NO"
    ds.ImageType = ["DERIVED", "SECONDARY"]

    return {
        "pseudo_patient": pseudo_patient,
        "pseudo_study_uid": pseudo_study,
        "pseudo_accession": pseudo_accession,
        "attributes_removed": len(removed),
        "uids_remapped": len(remapped),
        "text_regions_masked": masked,
        "at": datetime.datetime.utcnow().isoformat() + "Z",
    }
