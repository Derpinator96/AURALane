"""PNG -> DICOM. The simulated imaging source.

The challenge brief permits "publicly available or simulated DICOM imaging
datasets". NIH ChestX-ray14 ships as PNG, so this wraps those pixels in valid
Computed Radiography DICOM objects with a proper patient/study/series/instance
hierarchy.

Two things here are deliberate and matter for the demo:

  1. Identifiers are POPULATED. PatientName, PatientID, birth date, accession,
     referring physician, institution. You cannot demonstrate stripping
     something that was never present. These are the tags the edge agent's
     de-identification removes, and verify.py asserts they are gone downstream.

  2. Some studies get the patient name BURNED INTO THE PIXELS. That is a real
     failure mode in medical imaging -- ultrasound and secondary captures
     routinely carry identifiers rendered into the image itself, where tag
     stripping does nothing. It is what the OCR masking step exists for.

Every identifier is unmistakably synthetic (SIM^PATIENT^0042). This project
claims "no real patient data" on the slide and in the brief. Keep it obviously
true rather than merely true.

    python make_dicom.py --src ../../images --out ../data/studies --count 40

NOT A DIAGNOSTIC DEVICE.
"""
import argparse
import datetime
import json
import os
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import (ComputedRadiographyImageStorage, ExplicitVRLittleEndian,
                         generate_uid)

CRImageStorage = ComputedRadiographyImageStorage

# Private UID root for this project. Real deployments register their own with
# a national body; for a simulation any well-formed private root is correct.
UID_ROOT = "1.2.826.0.1.3680043.10.1421."

INSTITUTION = "SIMULATED GENERAL HOSPITAL"
STATION = "CR_ROOM2"
MANUFACTURER = "AURALANE SIM"

_MAXVAL = {np.dtype("uint8"): 255, np.dtype("uint16"): 65535}


def read_grayscale(path):
    """Single-channel pixels plus the maximum value the dtype can hold.

    Mirrors imaging.read_grayscale in the main project, including the two
    faults that were fixed there: alpha channels must be dropped BEFORE
    averaging (a constant 255 alpha folded into a mean brightens the image),
    and bit depth must come from the dtype rather than being assumed to be 8.
    """
    img = np.asarray(Image.open(path))
    if img.ndim == 3:
        if img.shape[2] == 4:
            img = img[..., :3]
        img = img.mean(2)
    maxval = _MAXVAL.get(np.dtype(img.dtype))
    if maxval is None:
        top = float(np.nanmax(img))
        maxval = 255 if top <= 255 else 65535
        img = img.astype(np.uint16 if maxval == 65535 else np.uint8)
    return img, maxval


def _font(size):
    for candidate in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                      "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                      "C:\\Windows\\Fonts\\arialbd.ttf"):
        if os.path.exists(candidate):
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def burn_in(arr, maxval, lines):
    """Render identifiers into the pixel data itself.

    This is the problem OCR masking solves. `BurnedInAnnotation` exists as a
    DICOM tag to declare it, and is frequently absent or wrong -- which is why
    the masking step must never trust it.
    """
    # Text goes into a separate 8-bit mask, composited at the image's own bit
    # depth. The image data is never converted: PIL's "I;16" -> "L" conversion
    # clamps rather than scales, so every value above 255 saturated and the old
    # "* 257" turned any 16-bit frame uniformly white. Non-text pixels are
    # untouched at any bit depth.
    height, width = arr.shape
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    size = max(16, height // 42)
    font = _font(size)
    y = int(size * 0.6)
    for line in lines:
        draw.text((int(size * 0.6), y), line, fill=255, font=font)
        y += int(size * 1.25)
    out = arr.astype(np.uint8 if maxval == 255 else np.uint16)     # a copy
    out[np.asarray(mask) > 0] = maxval
    return out


def build_instance(pixels, maxval, ident, when, source_name):
    """One CR image object, fully populated."""
    rows, cols = pixels.shape

    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = CRImageStorage
    meta.MediaStorageSOPInstanceUID = ident["sop_uid"]
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.ImplementationVersionName = "AURALANE_SIM"

    ds = Dataset()
    ds.file_meta = meta

    # --- Patient ---------------------------------------------------------
    ds.PatientName = ident["patient_name"]
    ds.PatientID = ident["patient_id"]
    ds.PatientBirthDate = ident["birth_date"]
    ds.PatientSex = ident["sex"]

    # --- Study -----------------------------------------------------------
    ds.StudyInstanceUID = ident["study_uid"]
    ds.StudyDate = when.strftime("%Y%m%d")
    ds.StudyTime = when.strftime("%H%M%S")
    ds.AccessionNumber = ident["accession"]
    ds.ReferringPhysicianName = ident["referrer"]
    ds.StudyDescription = "CHEST PA"
    ds.StudyID = ident["study_id"]

    # --- Series ----------------------------------------------------------
    ds.SeriesInstanceUID = ident["series_uid"]
    ds.SeriesNumber = 1
    ds.Modality = "CR"
    ds.SeriesDescription = "PA"
    ds.BodyPartExamined = "CHEST"
    ds.ViewPosition = "PA"      # Type 2, CR Series module. Matches StudyDescription.

    # --- Equipment -------------------------------------------------------
    ds.InstitutionName = INSTITUTION
    ds.StationName = STATION
    ds.Manufacturer = MANUFACTURER
    ds.ManufacturerModelName = "PNG-WRAPPER"

    # --- Instance --------------------------------------------------------
    ds.SOPClassUID = CRImageStorage
    ds.SOPInstanceUID = ident["sop_uid"]
    ds.InstanceNumber = 1
    ds.ImageType = ["DERIVED", "SECONDARY"]

    # --- Image pixels ----------------------------------------------------
    bits = 8 if maxval == 255 else 16
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.Rows = rows
    ds.Columns = cols
    ds.BitsAllocated = bits
    ds.BitsStored = bits
    ds.HighBit = bits - 1
    ds.PixelRepresentation = 0
    ds.RescaleIntercept = 0
    ds.RescaleSlope = 1
    ds.RescaleType = "US"       # Required once RescaleIntercept is present.
    ds.WindowCenter = maxval // 2
    ds.WindowWidth = maxval
    ds.PixelData = pixels.astype(np.uint8 if bits == 8 else np.uint16).tobytes()

    # Honest provenance. A real acquisition would not carry this; a simulated
    # one should say so inside the object, not only in the README.
    ds.BurnedInAnnotation = "YES" if ident["burned_in"] else "NO"
    ds.PatientComments = f"SIMULATED STUDY - source image {source_name}"
    ds.DerivationDescription = (
        "Synthetic DICOM wrapper around a public NIH ChestX-ray14 image. "
        "Identifiers are fabricated. Not real patient data."
    )
    return ds


def make_identity(index, rng, when, burned):
    n = index + 1
    return {
        "patient_name": f"SIM^PATIENT^{n:04d}",
        "patient_id": f"SIMID-{n:06d}",
        "birth_date": (datetime.date(rng.randint(1945, 2005),
                                     rng.randint(1, 12),
                                     rng.randint(1, 28))).strftime("%Y%m%d"),
        "sex": rng.choice(["M", "F"]),
        # VR SH caps at 16 characters -- real accession numbers are short.
        "accession": f"A{when.strftime('%Y%m%d')}{n:04d}",
        "referrer": f"SIM^REFERRER^{rng.choice('ABCDE')}",
        "study_id": f"{n:05d}",
        "study_uid": generate_uid(prefix=UID_ROOT),
        "series_uid": generate_uid(prefix=UID_ROOT),
        "sop_uid": generate_uid(prefix=UID_ROOT),
        "burned_in": burned,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", required=True, help="directory of source PNGs")
    ap.add_argument("--out", required=True, help="output directory for studies")
    ap.add_argument("--count", type=int, default=40)
    ap.add_argument("--burn-in", type=float, default=0.15,
                    help="fraction of studies with identifiers burned into pixels")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    sources = sorted(f for f in os.listdir(args.src)
                     if f.lower().endswith((".png", ".jpg", ".jpeg")))
    if not sources:
        raise SystemExit(f"no images found in {args.src}")
    if len(sources) < args.count:
        print(f"note: only {len(sources)} source images, generating that many")
    sources = sources[:args.count]

    os.makedirs(args.out, exist_ok=True)
    start = datetime.datetime.now().replace(hour=6, minute=0, second=0,
                                            microsecond=0)
    manifest = []

    for i, name in enumerate(sources):
        pixels, maxval = read_grayscale(os.path.join(args.src, name))
        when = start + datetime.timedelta(minutes=i * 7)
        burned = rng.random() < args.burn_in
        ident = make_identity(i, rng, when, burned)

        if burned:
            pixels = burn_in(pixels, maxval,
                             [ident["patient_name"].replace("^", " "),
                              ident["patient_id"],
                              f"DOB {ident['birth_date']}"])

        ds = build_instance(pixels, maxval, ident, when, name)

        study_dir = os.path.join(args.out, ident["study_uid"])
        os.makedirs(study_dir, exist_ok=True)
        path = os.path.join(study_dir, f"{ident['sop_uid']}.dcm")
        ds.save_as(path, enforce_file_format=True)

        manifest.append({
            "source_png": name,
            "path": os.path.relpath(path, args.out),
            "study_uid": ident["study_uid"],
            "series_uid": ident["series_uid"],
            "sop_uid": ident["sop_uid"],
            "patient_name": ident["patient_name"],
            "patient_id": ident["patient_id"],
            "accession": ident["accession"],
            "birth_date": ident["birth_date"],
            "burned_in": burned,
        })

    with open(os.path.join(args.out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    burned_n = sum(1 for m in manifest if m["burned_in"])
    print(f"wrote {len(manifest)} studies to {args.out}")
    print(f"  {burned_n} with identifiers burned into the pixel data")
    print(f"  manifest.json records the originals so verify.py can assert "
          f"they are gone downstream")


if __name__ == "__main__":
    main()
