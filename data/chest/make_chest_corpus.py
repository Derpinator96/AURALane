"""Build the chest DICOM corpus, then check it. Safe to re-run.

    python data/chest/make_chest_corpus.py            # 40 studies
    python data/chest/make_chest_corpus.py --count 80

Writes data/chest/studies/{StudyInstanceUID}/{SOPInstanceUID}.dcm plus
manifest.json by running sim/generator/make_dicom.py unmodified.

Why the output folder is wiped first: make_dicom.py mints UIDs with
pydicom.uid.generate_uid(), which is random, so every run produces a fresh set
of study folders. Re-running into the same folder would leave the previous
run's studies on disk, unlisted in the manifest, and they would be uploaded
and counted as if they belonged.

Checks, all of which must pass for exit code 0:
  1. every study folder on disk is in the manifest, and the reverse
  2. every file reloads in pydicom and its pixel array matches Rows x Columns
  3. OCR finds the synthetic identifier on exactly the studies the manifest
     flags as burned-in, and on none of the others

Check 3 needs the tesseract binary. Without it the script says so and exits 3,
because an unrun check is not a passed one.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "chest" / "studies"
GENERATOR = ROOT / "sim" / "generator" / "make_dicom.py"
SOURCE_PNGS = ROOT / "images"

# Tokens that only exist in the text make_dicom.py burns in. Searching for these,
# rather than for "any text", matters: NIH source images already carry burned-in
# laterality markers and technician labels, which are not identifiers.
ID_TOKENS = ("SIMID", "SIM PATIENT", "DOB ")


def generate(count, seed):
    if OUT.exists():
        if OUT.parent != ROOT / "data" / "chest":      # never rmtree anything else
            raise SystemExit(f"refusing to delete unexpected path {OUT}")
        shutil.rmtree(OUT)
    subprocess.run([sys.executable, str(GENERATOR), "--src", str(SOURCE_PNGS),
                    "--out", str(OUT), "--count", str(count), "--seed", str(seed)],
                   check=True)
    return json.loads((OUT / "manifest.json").read_text())


def check_layout(manifest):
    on_disk = {p.name for p in OUT.iterdir() if p.is_dir()}
    listed = {m["study_uid"] for m in manifest}
    problems = []
    if on_disk - listed:
        problems.append(f"{len(on_disk - listed)} study folders not in the manifest")
    if listed - on_disk:
        problems.append(f"{len(listed - on_disk)} manifest studies missing on disk")
    return problems


def check_reload(manifest):
    import pydicom
    problems = []
    for m in manifest:
        path = OUT / m["path"]
        try:
            ds = pydicom.dcmread(path)
            arr = ds.pixel_array
        except Exception as e:
            problems.append(f"{m['path']}: does not reload ({type(e).__name__}: {e})")
            continue
        if arr.shape != (ds.Rows, ds.Columns):
            problems.append(f"{m['path']}: pixel array {arr.shape} vs Rows x Columns "
                            f"{(ds.Rows, ds.Columns)}")
        if ds.StudyInstanceUID != m["study_uid"] or ds.SOPInstanceUID != m["sop_uid"]:
            problems.append(f"{m['path']}: UIDs disagree with the manifest")
    return problems


def ocr_text(ds):
    """Text from both OCR passes deid.find_text_regions runs: the image as-is, and
    near-maximum pixels only, inverted. The threshold is read from deid.py so this
    check and the production masker cannot drift apart."""
    import numpy as np
    import pytesseract
    from PIL import Image
    sys.path.insert(0, str(ROOT / "sim" / "edge"))
    import deid
    arr = ds.pixel_array
    if arr.dtype != np.uint8:
        arr = (arr.astype(np.float32) / max(float(arr.max()), 1.0) * 255).astype(np.uint8)
    bright = np.where(arr >= deid.BRIGHT_TEXT_THRESHOLD, 0, 255).astype(np.uint8)
    return " ".join(pytesseract.image_to_string(Image.fromarray(a)).upper()
                    for a in (arr, bright))


def check_ocr(manifest):
    """-> (problems, ran). ran is False when tesseract is unavailable."""
    import shutil as _sh
    if _sh.which("tesseract") is None:
        return [], False
    import pydicom
    problems = []
    for m in manifest:
        text = ocr_text(pydicom.dcmread(OUT / m["path"]))
        found = any(tok in text for tok in ID_TOKENS)
        if m["burned_in"] and not found:
            problems.append(f"{m['patient_id']}: flagged burned-in, OCR found no identifier")
        if not m["burned_in"] and found:
            problems.append(f"{m['patient_id']}: not flagged, but OCR found an identifier")
    return problems, True


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", type=int, default=40)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    manifest = generate(args.count, args.seed)
    burned = sum(m["burned_in"] for m in manifest)
    print(f"generated {len(manifest)} studies, {burned} with burned-in identifiers")

    failed = False
    for name, problems in (("layout", check_layout(manifest)),
                           ("reload", check_reload(manifest))):
        print(f"  {name:<7} {'ok' if not problems else 'FAIL'}")
        for p in problems:
            print(f"          {p}")
        failed |= bool(problems)

    problems, ran = check_ocr(manifest)
    if not ran:
        print("  ocr     NOT RUN: tesseract is not on PATH (docs/MANUAL-STEPS.md step 7)")
    else:
        print(f"  ocr     {'ok' if not problems else 'FAIL'}")
        for p in problems:
            print(f"          {p}")
        failed |= bool(problems)

    if failed:
        return 1
    return 0 if ran else 3


if __name__ == "__main__":
    sys.exit(main())
