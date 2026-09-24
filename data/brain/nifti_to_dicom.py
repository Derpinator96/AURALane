"""BraTS NIfTI to DICOM. One study per case, four MR series, one instance per slice.

    python data/brain/nifti_to_dicom.py              # every 2nd axial slice
    python data/brain/nifti_to_dicom.py --slices 1   # full set, 620 instances per case

Reads every complete case in data/brain/raw/ and writes
data/brain/dicom/{StudyInstanceUID}/{SOPInstanceUID}.dcm plus manifest.json
(one entry per instance, same keys as the chest manifest, plus brain-specific
ones). The folder is wiped first: UIDs are random, so re-running into it would
leave the previous run's studies behind, unlisted.

Series order is the model's channel order, not an aesthetic choice. The MONAI
bundle in _external/brainmri/brats_mri_segmentation/configs/metadata.json
declares its input channel_def as 0 = T1c, 1 = T1, 2 = T2, 3 = FLAIR (checked
against that file, bundle version 0.5.4). SeriesNumber 1..4 follows it exactly,
so reassembling the 4-channel tensor from DICOM is unambiguous. A scrambled
order would still produce a plausible-looking mask, which is why it matters.

The _seg volume is ground truth, not an image series. It is copied beside the
study as ground_truth_seg.nii.gz, with its free-text header fields cleared, and
is never converted.

Every written instance is read back from disk and compared, value for value,
with the source slice. The script exits non-zero if any comparison fails.

NOT A DIAGNOSTIC DEVICE.
"""
import argparse
import datetime
import importlib.util
import json
import logging
import random
import shutil
import sys
from pathlib import Path

import nibabel as nib
import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.pixels import apply_modality_lut
from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage, generate_uid

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "brain" / "raw"
OUT = ROOT / "data" / "brain" / "dicom"

log = logging.getLogger("nifti_to_dicom")

# (file suffix, SeriesDescription). SeriesNumber is position + 1. This order is
# the bundle's channel_def; see the module docstring before changing it.
SERIES = [("t1ce", "T1C"), ("t1", "T1"), ("t2", "T2"), ("flair", "FLAIR")]

# Brain patients start here so they never share a PatientID with a chest study.
# identity.py keys patients on PatientID; a shared ID would merge two people.
IDENTITY_OFFSET = 9000

STATION = "MR_ROOM1"

# NIfTI world space is RAS+, DICOM patient space is LPS+. Flip x and y.
RAS_TO_LPS = np.diag([-1.0, -1.0, 1.0, 1.0])


def _load_generator():
    """make_dicom.py is reused, not copied, so both corpora share one identity scheme."""
    path = ROOT / "sim" / "generator" / "make_dicom.py"
    spec = importlib.util.spec_from_file_location("make_dicom", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# -- volumes ----------------------------------------------------------------

def load_volume(path):
    """-> (data, img). Refuses anything that is not a single 3D volume.

    A raise, not an assert: assert statements vanish under python -O, and a 4D
    volume silently treated as 3D is exactly the failure this guards against.
    """
    img = nib.load(str(path))
    if img.ndim != 3:
        raise ValueError(f"{Path(path).name}: expected a 3D volume, got {img.ndim}D "
                         f"shape {img.shape}. BraTS sequences are four separate 3D "
                         f"files, not one 4D series.")
    return np.asanyarray(img.dataobj), img


def clear_free_text(img, label):
    """Log, then blank, the two NIfTI free-text fields. Returns what was in them.

    descrip and aux_file are written by whoever ran the original conversion and
    can carry names, sites or dates. They are empty in the BraTS 2021 cases
    checked so far; this must still work when they are not.
    """
    found = {}
    for field in ("descrip", "aux_file"):
        raw = img.header[field].tobytes().rstrip(b"\x00").strip()
        if raw:
            found[field] = raw.decode("latin-1")
            log.warning("%s: NIfTI %s was %r, cleared", label, field, found[field])
        img.header[field] = b""
    return found


def to_uint16(data):
    """-> (stored uint16 array, RescaleIntercept). Exact, never clipped.

    Negative minimums are shifted up and recorded as an intercept, so
    stored + intercept reproduces every original value. Integer input only:
    these volumes are int16, and a float volume would need a slope as well,
    which is deliberately not guessed at here.
    """
    if not np.issubdtype(data.dtype, np.integer):
        raise NotImplementedError(f"{data.dtype} input: only integer volumes are handled")
    lo, hi = int(data.min()), int(data.max())
    intercept = min(lo, 0)
    if hi - intercept > 65535:
        raise ValueError(f"value range {lo}..{hi} does not fit uint16 even with an intercept")
    stored = (data.astype(np.int64) - intercept).astype(np.uint16)
    if not np.array_equal(stored.astype(np.int64) + intercept, data.astype(np.int64)):
        raise AssertionError("uint16 round trip does not recover the original values")
    return stored, intercept


def slice_geometry(affine, zooms, step):
    """DICOM plane geometry for axial slice k, derived from the header.

    Pixel (row r, column c) of slice k is voxel (i=c, j=r, k). Nothing is
    assumed about spacing: it comes from the affine and is cross-checked
    against the header zooms, and a disagreement between them is an error.
    """
    a = RAS_TO_LPS @ np.asarray(affine, dtype=float)
    cols = [a[:3, n] for n in range(3)]
    norms = [float(np.linalg.norm(c)) for c in cols]
    if not np.allclose(norms, [float(z) for z in zooms[:3]], atol=1e-4):
        raise ValueError(f"affine voxel sizes {norms} disagree with header zooms {zooms[:3]}")
    # Voxel axis 2 must be the head-to-foot axis for "one instance per axial slice".
    if int(np.argmax([abs(c[2]) / n for c, n in zip(cols, norms)])) != 2:
        raise ValueError("voxel axis 2 is not the superior-inferior axis; not axial slices")

    row_dir = cols[0] / norms[0]            # along a row: increasing column index = voxel i
    col_dir = cols[1] / norms[1]            # down a column: increasing row index = voxel j
    normal = np.cross(row_dir, col_dir)

    def position(k):
        return (a @ np.array([0.0, 0.0, float(k), 1.0]))[:3]

    return {
        "iop": [_num(x) for x in (*row_dir, *col_dir)],
        "pixel_spacing": [_num(norms[1]), _num(norms[0])],      # [between rows, between columns]
        "slice_thickness": _num(norms[2]),
        # distance between the slices actually written, so subsampling doubles it
        "spacing_between_slices": _num(norms[2] * step),
        "position": lambda k: [_num(x) for x in position(k)],
        "location": lambda k: _num(float(np.dot(normal, position(k)))),
    }


def _num(x):
    """A DS-safe number: at most 16 characters, and never '-0.0'."""
    return round(float(x), 4) + 0.0


def window(stored, intercept):
    """Display window from the 1st to 99th percentile of non-zero voxels."""
    vals = stored[stored > 0].astype(np.float64) + intercept
    if not vals.size:
        return 0, 1
    lo, hi = np.percentile(vals, [1, 99])
    return _num((lo + hi) / 2), _num(max(hi - lo, 1))


# -- DICOM ------------------------------------------------------------------

def build_instance(pixels, ident, when, case, series_no, series_desc, series_uid,
                   sop_uid, frame_uid, instance_no, geo, k, intercept, win, gen):
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = MRImageStorage
    meta.MediaStorageSOPInstanceUID = sop_uid
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.ImplementationVersionName = "AURALANE_SIM"

    ds = Dataset()
    ds.file_meta = meta

    # Patient: synthetic, from make_dicom.make_identity
    ds.PatientName = ident["patient_name"]
    ds.PatientID = ident["patient_id"]
    ds.PatientBirthDate = ident["birth_date"]
    ds.PatientSex = ident["sex"]

    # Study: shared by all four series of the case
    ds.StudyInstanceUID = ident["study_uid"]
    ds.StudyDate = when.strftime("%Y%m%d")
    ds.StudyTime = when.strftime("%H%M%S")
    ds.AccessionNumber = ident["accession"]
    ds.ReferringPhysicianName = ident["referrer"]
    ds.StudyDescription = "MR BRAIN"
    ds.StudyID = ident["study_id"]

    # Series
    ds.SeriesInstanceUID = series_uid
    ds.SeriesNumber = series_no
    ds.SeriesDescription = series_desc
    ds.Modality = "MR"
    ds.BodyPartExamined = "BRAIN"
    # Type 2C for MR, so it must be present. BraTS does not record it, and IPP/IOP
    # already carry the geometry in patient space, so it is empty, not invented.
    ds.PatientPosition = ""

    # Frame of reference: the four sequences are co-registered, so they share one
    ds.FrameOfReferenceUID = frame_uid
    ds.PositionReferenceIndicator = ""

    # Equipment: the same fabricated identifiers make_dicom.py uses, so deid has
    # something real to strip
    ds.InstitutionName = gen.INSTITUTION
    ds.StationName = STATION
    ds.Manufacturer = gen.MANUFACTURER
    ds.ManufacturerModelName = "NIFTI-WRAPPER"

    # MR Image module. Acquisition parameters are unknown for a resampled,
    # co-registered research volume, so the Type 2 ones are present but empty
    # rather than invented. ScanningSequence is Type 1; "RM" is the DICOM
    # defined term for research mode.
    ds.ImageType = ["DERIVED", "SECONDARY"]
    ds.ScanningSequence = "RM"
    ds.SequenceVariant = "NONE"
    ds.ScanOptions = ""
    ds.MRAcquisitionType = ""
    ds.EchoTime = ""
    ds.RepetitionTime = ""
    ds.EchoTrainLength = ""

    # Instance and plane
    ds.SOPClassUID = MRImageStorage
    ds.SOPInstanceUID = sop_uid
    ds.InstanceNumber = instance_no
    ds.ContentDate = ds.StudyDate
    ds.ContentTime = ds.StudyTime
    ds.ImageOrientationPatient = geo["iop"]
    ds.ImagePositionPatient = geo["position"](k)
    ds.SliceLocation = geo["location"](k)
    ds.PixelSpacing = geo["pixel_spacing"]
    ds.SliceThickness = geo["slice_thickness"]
    ds.SpacingBetweenSlices = geo["spacing_between_slices"]

    # Pixels: uint16. Rescale tags are written only when an intercept is needed
    # (a negative minimum). Checked with dicom-validator against DICOM 2026d: the
    # classic MR Image IOD does not include the Modality LUT module, so Rescale
    # Intercept/Slope are flagged "unexpected" there. Both BraTS 2021 cases have a
    # minimum of 0, so they carry no rescale tags and validate clean. A volume with
    # negative values still round-trips exactly, but that object is non-conformant;
    # storing signed int16 (PixelRepresentation 1) would be the conformant option.
    rows, cols = pixels.shape
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.Rows = rows
    ds.Columns = cols
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    if intercept:
        ds.RescaleIntercept = intercept
        ds.RescaleSlope = 1
    ds.WindowCenter, ds.WindowWidth = win
    ds.PixelData = np.ascontiguousarray(pixels, dtype=np.uint16).tobytes()

    # Honest provenance inside the object. deid.py removes both fields.
    ds.BurnedInAnnotation = "NO"
    ds.PatientComments = f"SIMULATED STUDY - source BraTS 2021 case {case}, {series_desc}"
    ds.DerivationDescription = (
        "Synthetic DICOM wrapper around a public BraTS 2021 volume. "
        "Identifiers are fabricated. Not real patient data.")
    return ds


def complete_cases(raw=RAW):
    need = {s for s, _ in SERIES} | {"seg"}
    cases = []
    for d in sorted(p for p in raw.iterdir() if p.is_dir()):
        have = {f.name[len(d.name) + 1:].split(".nii")[0] for f in d.glob(f"{d.name}_*.nii*")}
        if need <= have:
            cases.append(d)
    return cases


def _nifti(case_dir, part):
    hits = sorted(case_dir.glob(f"{case_dir.name}_{part}.nii*"))
    if len(hits) != 1:
        raise FileNotFoundError(f"{case_dir.name}: expected one _{part} volume, found {len(hits)}")
    return hits[0]


def convert_case(case_dir, out_root, step, ident, when, gen):
    """Write one study. -> list of manifest entries, one per instance."""
    case = case_dir.name
    volumes = {}
    for part, desc in SERIES:
        data, img = load_volume(_nifti(case_dir, part))
        clear_free_text(img, f"{case} {desc}")
        volumes[part] = (data, img)

    # Co-registration is what justifies one shared frame of reference. Check it.
    ref = volumes[SERIES[0][0]][1]
    for part, (data, img) in volumes.items():
        if img.shape != ref.shape or not np.allclose(img.affine, ref.affine, atol=1e-4):
            raise ValueError(f"{case}: {part} is not on the same grid as {SERIES[0][0]}; "
                             f"the four series cannot share a frame of reference")

    geo = slice_geometry(ref.affine, ref.header.get_zooms(), step)
    study_dir = out_root / ident["study_uid"]
    study_dir.mkdir(parents=True)
    frame_uid = generate_uid(prefix=gen.UID_ROOT)
    slices = list(range(0, ref.shape[2], step))
    entries = []

    for series_no, (part, desc) in enumerate(SERIES, start=1):
        data, img = volumes[part]
        stored, intercept = to_uint16(data)
        win = window(stored, intercept)
        series_uid = generate_uid(prefix=gen.UID_ROOT)
        for instance_no, k in enumerate(slices, start=1):
            sop_uid = generate_uid(prefix=gen.UID_ROOT)
            ds = build_instance(stored[:, :, k].T, ident, when, case, series_no, desc,
                                series_uid, sop_uid, frame_uid, instance_no, geo, k,
                                intercept, win, gen)
            path = study_dir / f"{sop_uid}.dcm"
            ds.save_as(path, enforce_file_format=True)
            entries.append({
                "source_nifti": _nifti(case_dir, part).name,
                "path": f"{ident['study_uid']}/{sop_uid}.dcm",
                "study_uid": ident["study_uid"],
                "series_uid": series_uid,
                "sop_uid": sop_uid,
                "patient_name": ident["patient_name"],
                "patient_id": ident["patient_id"],
                "accession": ident["accession"],
                "birth_date": ident["birth_date"],
                "burned_in": False,
                "case": case,
                "series_number": series_no,
                "series_description": desc,
                "slice_index": k,
                "frame_of_reference_uid": frame_uid,
            })

    # Ground truth beside the study, never converted, free text cleared.
    _, seg = load_volume(_nifti(case_dir, "seg"))
    clear_free_text(seg, f"{case} seg")
    nib.save(seg, str(study_dir / "ground_truth_seg.nii.gz"))
    return entries


def verify(entries, out_root, raw=RAW):
    """Read every instance back and compare it to its source slice. -> problems."""
    problems = []
    cache = {}
    for e in entries:
        key = (e["case"], e["source_nifti"])
        if key not in cache:
            cache[key] = load_volume(raw / e["case"] / e["source_nifti"])[0]
        ds = pydicom.dcmread(out_root / e["path"])
        restored = apply_modality_lut(ds.pixel_array, ds)
        original = cache[key][:, :, e["slice_index"]].T
        if not np.array_equal(restored, original):
            problems.append(f"{e['path']}: pixel values differ from {e['source_nifti']} "
                            f"slice {e['slice_index']}")
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slices", type=int, default=2,
                    help="keep every Nth axial slice (default 2; 1 = all 155)")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    if args.slices < 1:
        ap.error("--slices must be >= 1")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    cases = complete_cases()
    if not cases:
        raise SystemExit(f"no complete BraTS cases in {RAW} (need t1, t1ce, t2, flair, seg)")

    if OUT.exists():
        if OUT.parent != ROOT / "data" / "brain":        # never rmtree anything else
            raise SystemExit(f"refusing to delete unexpected path {OUT}")
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    gen = _load_generator()
    rng = random.Random(args.seed)
    start = datetime.datetime.now().replace(hour=7, minute=0, second=0, microsecond=0)
    manifest = []
    for n, case_dir in enumerate(cases):
        when = start + datetime.timedelta(minutes=n * 20)
        ident = gen.make_identity(IDENTITY_OFFSET + n, rng, when, False)
        entries = convert_case(case_dir, OUT, args.slices, ident, when, gen)
        manifest.extend(entries)
        log.info("%s -> study %s, %s, %d instances",
                 case_dir.name, ident["study_uid"], ident["patient_id"], len(entries))

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))

    problems = verify(manifest, OUT)
    studies = len({e["study_uid"] for e in manifest})
    series = len({e["series_uid"] for e in manifest})
    print(f"wrote {studies} studies, {series} series, {len(manifest)} instances to {OUT}")
    print(f"  round trip {'ok, every value recovered' if not problems else 'FAIL'}")
    for p in problems[:10]:
        print(f"    {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
