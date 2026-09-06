"""Score every image in images/ with TorchXRayVision and write scores.json.

Run this once, offline, before the demo:

    python prepare.py

It does two things:

  1. fits the per-finding reference distribution (reference.json) if there are
     enough images to fit one honestly — otherwise it keeps the shipped
     reference and says so
  2. writes scores.json, which the page can run from with no server at all

Drop NIH ChestX-ray14 files into images/ and re-run; nothing else changes.
"""
import argparse
import json
import os
import random
import sys

import torchxrayvision as xrv

import imaging
import triage

IMG_DIR = "images"
MIN_FOR_REFIT = 50          # below this, a fitted reference is noise
EXTS = (".png", ".jpg", ".jpeg")


def main():
    ap = argparse.ArgumentParser(description="Score images/ with TorchXRayVision.")
    ap.add_argument("--limit", type=int, default=300,
                    help="max images to score (default 300; NIH's sample set is 5,606 "
                         "and you do not need them all)")
    ap.add_argument("--seed", type=int, default=7, help="sampling seed")
    ap.add_argument("--no-refit", action="store_true",
                    help="score against the existing reference.json instead of refitting "
                         "it. Use this when the LANES thresholds in triage.py are already "
                         "tuned to that reference — refitting moves every acuity value.")
    args = ap.parse_args()

    files = sorted(f for f in os.listdir(IMG_DIR) if f.lower().endswith(EXTS))
    if not files:
        sys.exit(f"No images in {IMG_DIR}/ — drop some chest X-rays in there first.")
    if len(files) > args.limit:
        random.Random(args.seed).shuffle(files)
        files = sorted(files[:args.limit])
        print(f"Sampling {len(files)} of the images present (--limit to change).")

    print(f"Loading densenet121-res224-all ...")
    model = xrv.models.DenseNet(weights="densenet121-res224-all")
    model.eval()

    records, failed = [], []
    for i, fn in enumerate(files, 1):
        try:
            preds = imaging.predict(model, os.path.join(IMG_DIR, fn))
        except Exception as e:
            failed.append((fn, str(e)))
            continue
        records.append({"filename": fn,
                        "preds": {k: round(v, 5) for k, v in preds.items()}})
        print(f"  [{i}/{len(files)}] {fn}")

    if not records:
        sys.exit("Nothing scored. Are these readable chest X-ray images?")

    all_preds = [r["preds"] for r in records]
    if args.no_refit:
        ref = triage.load_reference()
        try:                               # carry the existing reference's provenance forward
            refitted = json.load(open("scores.json"))["reference_fitted"]
        except Exception:
            refitted = False
        print(f"\nKept the existing reference.json (--no-refit) — operating points and "
              f"the acuity scale are unchanged.")
    elif len(records) >= MIN_FOR_REFIT:
        ref = triage.build_reference(all_preds)
        json.dump(ref, open("reference.json", "w"), indent=1)
        refitted = True
        print(f"\nFitted reference from {len(records)} studies -> reference.json")
    else:
        ref = triage.load_reference()
        refitted = False
        print(f"\nOnly {len(records)} studies (< {MIN_FOR_REFIT}); kept the shipped "
              f"reference. Operating points are borrowed, not fitted — say so if asked.")

    studies = []
    for n, r in enumerate(records, 1):
        d = triage.score(r["preds"], ref)
        d.update({"id": f"ST-{n:03d}",
                  "filename": r["filename"],
                  "image": f"images/{r['filename']}"})
        studies.append(d)

    json.dump({"reference_fitted": refitted,
               "n_studies": len(studies),
               "model": "densenet121-res224-all",
               "temperature": triage.TEMPERATURE,
               "studies": studies},
              open("scores.json", "w"), indent=1)

    from collections import Counter
    print(f"\nWrote scores.json — {len(studies)} studies")
    for lane, n in Counter(s["lane"] for s in studies).most_common():
        print(f"  {lane:<10} {n}")
    if failed:
        print(f"\n{len(failed)} could not be read:")
        for fn, e in failed[:5]:
            print(f"  {fn}: {e[:70]}")


if __name__ == "__main__":
    main()
