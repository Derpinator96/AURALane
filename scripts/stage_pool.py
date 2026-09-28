"""Stage the simulated-ingest pool. Run once, on the edge machine (your laptop).

    python scripts/stage_pool.py --local              # data/pool/<type>/<study>/
    python scripts/stage_pool.py --stack Auralane     # s3://<bucket>/pool/<type>/<study>/
    python scripts/stage_pool.py --stack Auralane --types brain --force

Each study in the local corpora (data/chest/studies, data/brain/dicom, data/ct/raw)
is de-identified here with the edge de-identifier (sim/edge/deid.py through
core.pipeline.deidentify_all: PS3.15 tag rules and both OCR passes on every
image), and only the cleaned instances are written or uploaded. This is the one
place de-identification happens for simulated ingest: the API later checks the
marks on every instance and refuses a study without them. Nothing identifiable
leaves this machine.

The folder name is the pseudonymous StudyInstanceUID, so the worklist row and
the pool entry share a name. deid_report.json beside the instances records how
many text regions were blanked per instance, for the brain mask check's reason.

Already-staged sources are skipped (data/pool/staged.json remembers them per
target) unless --force. Brain MR takes minutes per study: two OCR passes on
each of 620 slices.

NON-DIAGNOSTIC; DECISION SUPPORT ONLY.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.intake import CORPUS  # noqa: E402

TYPES = {"chest": "CR", "brain": "MR", "ct": "CT"}
LOCAL_POOL = ROOT / "data" / "pool"
STAGED = LOCAL_POOL / "staged.json"


def sources(kind: str) -> list[Path]:
    root = CORPUS[TYPES[kind]]
    if not root.is_dir():
        return []
    return sorted(d for d in root.iterdir() if d.is_dir() and any(d.rglob("*.dcm")))


def clean(study_dir: Path, identity, workers: int | None):
    from core.pipeline import deidentify_all
    paths = sorted(study_dir.rglob("*.dcm"))
    cleaned, reports = deidentify_all(paths, identity, workers)
    uids = {str(ds.StudyInstanceUID) for ds in cleaned}
    if len(uids) != 1:
        raise ValueError(f"{study_dir.name}: files span {len(uids)} studies")
    files = {}
    for ds in cleaned:
        buf = io.BytesIO()
        ds.save_as(buf, enforce_file_format=True)
        files[f"{ds.SOPInstanceUID}.dcm"] = buf.getvalue()
    report = {str(ds.SOPInstanceUID): int(r["text_regions_masked"])
              for ds, r in zip(cleaned, reports)}
    files["deid_report.json"] = json.dumps(report).encode()
    return uids.pop(), files, sum(report.values())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    where = ap.add_mutually_exclusive_group(required=True)
    where.add_argument("--local", action="store_true", help="write to data/pool/")
    where.add_argument("--stack", help="CloudFormation stack name; uploads to its bucket")
    ap.add_argument("--types", default="chest,brain,ct")
    ap.add_argument("--limit", type=int, default=0, help="at most this many per type")
    ap.add_argument("--force", action="store_true", help="re-stage sources already staged")
    ap.add_argument("--ocr-workers", type=int, default=None)
    args = ap.parse_args()

    from core.run import _identity, load_stack
    s3 = bucket = None
    if args.stack:
        import os

        import boto3
        load_stack(args.stack)
        bucket = os.environ["AURALANE_BUCKET"]
        s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    target = f"s3://{bucket}/pool/" if bucket else str(LOCAL_POOL)
    staged = json.loads(STAGED.read_text()) if STAGED.exists() else {}
    done = staged.setdefault(target, {})
    identity = _identity()

    print("NON-DIAGNOSTIC; DECISION SUPPORT ONLY")
    print(f"staging into {target}")
    for kind in [t.strip() for t in args.types.split(",") if t.strip()]:
        if kind not in TYPES:
            ap.error(f"unknown type {kind!r}; one of {', '.join(TYPES)}")
        todo = sources(kind)
        if args.limit:
            todo = todo[:args.limit]
        if not todo:
            print(f"  {kind}: no studies under {CORPUS[TYPES[kind]]}")
            continue
        for src in todo:
            key = str(src.relative_to(ROOT))
            if key in done and not args.force:
                print(f"  {kind}: {src.name} already staged as {done[key]}")
                continue
            uid, files, masked = clean(src, identity, args.ocr_workers)
            if bucket:
                prefix = f"pool/{kind}/{uid}/"
                with ThreadPoolExecutor(16) as pool:
                    list(pool.map(lambda kv: s3.put_object(Bucket=bucket, Key=prefix + kv[0],
                                                           Body=kv[1]), files.items()))
            else:
                out = LOCAL_POOL / kind / uid
                out.mkdir(parents=True, exist_ok=True)
                for name, data in files.items():
                    (out / name).write_bytes(data)
            done[key] = uid
            STAGED.parent.mkdir(parents=True, exist_ok=True)
            STAGED.write_text(json.dumps(staged, indent=1))
            print(f"  {kind}: {src.name} -> {uid} ({len(files) - 1} instances, "
                  f"{masked} text regions masked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
