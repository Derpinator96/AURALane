"""Convert new BraTS cases to DICOM without touching the ones already converted.

    python scripts/convert_brain.py                 # every new case in data/brain/raw/
    python scripts/convert_brain.py --slices 2      # every 2nd axial slice instead

Put BraTS 2021 cases in data/brain/raw/<case>/ (t1, t1ce, t2, flair and seg
NIfTI). Cases already listed in data/brain/dicom/manifest.json are skipped;
each new one is written by data/brain/nifti_to_dicom.py's own convert_case,
appended to the manifest and read back value for value, as that script does.
Unlike running nifti_to_dicom.py itself, nothing already converted is deleted,
so its UIDs, and any pool entry staged from it, stay valid.

Then stage the new studies: python scripts/stage_pool.py --local (or --stack).

No download code: getting the cases is up to you.
"""
from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _converter():
    spec = importlib.util.spec_from_file_location(
        "nifti_to_dicom", ROOT / "data" / "brain" / "nifti_to_dicom.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slices", type=int, default=1, help="keep every Nth axial slice (1 = all)")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    n2d = _converter()

    manifest_path = n2d.OUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else []
    converted = {e["case"] for e in manifest}
    new = [d for d in n2d.complete_cases() if d.name not in converted]
    if not new:
        print(f"nothing to convert: {len(converted)} case(s) already in {manifest_path}")
        return 0

    n2d.OUT.mkdir(parents=True, exist_ok=True)
    gen = n2d._load_generator()
    # Identities continue after the ones in use, so no two cases share a PatientID.
    used = {int(e["patient_id"].split("-")[-1]) for e in manifest}
    next_id = max(used, default=n2d.IDENTITY_OFFSET - 1) + 1
    rng = random.Random(args.seed + next_id)
    start = datetime.datetime.now().replace(hour=7, minute=0, second=0, microsecond=0)
    added = []
    for i, case_dir in enumerate(new):
        when = start + datetime.timedelta(minutes=(len(converted) + i) * 20)
        ident = gen.make_identity(next_id + i, rng, when, False)
        entries = n2d.convert_case(case_dir, n2d.OUT, args.slices, ident, when, gen)
        added.extend(entries)
        print(f"{case_dir.name} -> study {ident['study_uid']}, {ident['patient_id']}, "
              f"{len(entries)} instances")

    problems = n2d.verify(added, n2d.OUT)
    manifest_path.write_text(json.dumps(manifest + added, indent=2))
    print(f"added {len(new)} case(s); round trip "
          f"{'ok, every value recovered' if not problems else 'FAIL'}")
    for p in problems[:10]:
        print(f"  {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
