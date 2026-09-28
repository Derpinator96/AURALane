"""End-to-end check of the cloud path, every step verified from its own evidence.

    python scripts/e2e_aws.py --stack Auralane

For one chest X-ray with burned-in identifiers, one brain MR and one head CT:

  1 upload       the raw files are in S3 upload/ (the edge's only step)
  2 fargate      the ingest task's CloudWatch log shows it ran this study
  3 steps        the audit trail has deidentify, blob_put, import,
                 prepare_inputs, infer, adapt, triage, persist, blob_delete,
                 all ok, for this run
  4 masking      HealthImaging's stored metadata holds none of the original
                 identifiers; for the chest study the stored pixels are OCR'd
                 and the burned-in identifiers are gone (the source pixels are
                 OCR'd too, as the control: they must be readable there)
  5 healthimaging the image set(s) hold every uploaded instance
  6 inference    the model's evidence exists: Grad-CAM PNGs (chest, Lambda),
                 the async request in S3 (brain, CT on SageMaker)
  7 persist      the worklist row matches the task's result
  8 cleanup      transient/<run>/, upload/<batch>/<item>/ and every import
                 staging file are gone

Needs AWS credentials, Tesseract on PATH, the corpora on disk. Costs one
Fargate task and one model call per study, plus endpoint wakes (docs/AWS-COSTS.md).
Exits 0 only if every check passes.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

STEPS = ["deidentify", "blob_put", "import", "prepare_inputs", "infer", "adapt", "triage",
         "persist", "blob_delete"]


class Report:
    def __init__(self):
        self.rows, self.ok = [], True

    def check(self, study: str, step: str, passed: bool, detail: str) -> bool:
        self.rows.append((study, step, passed, detail))
        self.ok &= bool(passed)
        print(f"  [{'PASS' if passed else 'FAIL'}] {step:<14} {detail}", flush=True)
        return passed


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s).upper())


def _ocr(pixels) -> str:
    import numpy as np
    import pytesseract
    from PIL import Image
    a = pixels.astype("float64")
    a = (a - a.min()) / max(float(a.max() - a.min()), 1.0) * 255
    return pytesseract.image_to_string(Image.fromarray(a.astype(np.uint8)))


def _identifiers(files: list[Path]) -> dict[str, str]:
    import pydicom
    ds = pydicom.dcmread(files[0], stop_before_pixels=True)
    return {k: str(ds.get(k)) for k in ("PatientName", "PatientID", "PatientBirthDate",
                                        "StudyInstanceUID", "AccessionNumber") if ds.get(k)}


def run_one(label: str, study_dir: Path, item: str, batch: str, ctx: dict, rep: Report,
            burned_in: dict | None) -> None:
    import pydicom
    from core.types import StudyRef
    from core.upload import RESULTS, upload_study
    s3, bucket = ctx["s3"], ctx["bucket"]
    files = sorted(study_dir.rglob("*.dcm"))
    orig = _identifiers(files)
    print(f"\n{label}: {len(files)} instances from {study_dir.name}", flush=True)

    # 0 control: the burned-in identifiers are readable in the source pixels
    if burned_in:
        src = _norm(_ocr(pydicom.dcmread(files[0]).pixel_array))
        rep.check(label, "control", _norm(burned_in["patient_id"]) in src,
                  f"source pixels: burned-in {burned_in['patient_id']} readable before masking")

    # 1 upload
    t0 = time.time()
    upload_study(s3, bucket, files, batch, item, site_state=ctx["state"], modality=label)
    prefix = f"upload/{batch}/{item}/"
    n = sum(len(p.get("Contents", [])) for p in s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix=prefix))
    rep.check(label, "upload", n == len(files) + 1,
              f"{n - 1} files and the manifest in s3://{bucket}/{prefix}")

    # wait for the task's result
    key = f"{RESULTS}{batch}/{item}.json"
    result = None
    while time.time() - t0 < ctx["timeout"]:
        try:
            result = json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
            break
        except s3.exceptions.NoSuchKey:
            time.sleep(15)
            print(f"    waiting for the ingest task: {int(time.time() - t0)} s", flush=True)
    if not rep.check(label, "result", bool(result) and result.get("status") == "SCORED",
                     f"{result}" if result else f"no result after {ctx['timeout']} s"):
        return
    study = result["study"]

    # 2 fargate: the task's own log names this study
    # Every page: filter_log_events can return an empty first page while it scans.
    hits = [e for page in ctx["logs"].get_paginator("filter_log_events").paginate(
        logGroupName=ctx["log_group"], startTime=int(t0 * 1000) - 60000,
        filterPattern=f'"{study}"') for e in page.get("events", [])]
    rep.check(label, "fargate", bool(hits),
              f"ingest task log in {ctx['log_group']} mentions {study}")

    # 3 every step, from the audit trail
    events = ctx["table"].query("audit", study=study)
    runs = {}
    for e in events:
        rid = (e.get("detail") or {}).get("run_id")
        if rid:
            runs.setdefault(rid, []).append(e)
    run_id = max(runs, key=lambda r: max(e["event_id"] for e in runs[r]))
    got = {e["action"]: e for e in runs[run_id]}
    for step in STEPS:
        e = got.get(step)
        rep.check(label, step, bool(e) and e["outcome"] == "ok",
                  f"{e['outcome']} in {float(e['duration_ms']):,.0f} ms" if e else "missing from the audit")
    row = ctx["table"].get_item("worklist", {"study": study})

    # 4 masking: stored metadata and pixels
    ids = [i for i in row["datastore_id"].split(",") if i]
    doc_text = json.dumps([ctx["datastore"]._document(i) for i in ids])
    leaked = [f"{k}={v}" for k, v in orig.items()
              if k != "StudyInstanceUID" and v and v in doc_text]
    leaked += [f"StudyInstanceUID={orig['StudyInstanceUID']}"] if orig.get(
        "StudyInstanceUID") in doc_text else []
    pn = re.search(r'"PatientName": "([^"]*)"', doc_text)
    rep.check(label, "masking", not leaked and bool(pn) and pn.group(1).startswith("AUR-"),
              f"HealthImaging holds PatientName {pn.group(1) if pn else None!r}; "
              f"original identifiers found: {leaked or 'none'}")
    ref = StudyRef(study, row["datastore_id"])
    meta = ctx["datastore"].get_metadata(ref)
    if burned_in:
        s = meta.series[0]
        stored = _norm(_ocr(ctx["datastore"].frame_pixels(ref, s.series_uid, s.instance_uids[0])))
        found = [v for v in (burned_in["patient_id"], burned_in["patient_name"],
                             burned_in["birth_date"]) if v and _norm(v) in stored]
        rep.check(label, "pixel mask", not found,
                  f"OCR of the frame stored in HealthImaging: burned-in identifiers found: "
                  f"{found or 'none'}")

    # 5 healthimaging holds every instance
    stored_n = sum(s.instance_count for s in meta.series)
    rep.check(label, "healthimaging", stored_n == len(files),
              f"{len(ids)} image set(s), {len(meta.series)} series, {stored_n} of {len(files)} instances")

    # 6 inference evidence
    if label == "chest":
        pngs = [v for k, v in (row.get("evidence") or {}).items()
                if k.endswith("_png") and isinstance(v, str)]
        ok = bool(pngs) and all(s3.head_object(Bucket=bucket, Key=k) for k in pngs)
        rep.check(label, "inference", ok, f"Lambda Grad-CAM evidence in S3: {pngs}")
    else:
        objs = [o["Key"] for p in s3.get_paginator("list_objects_v2").paginate(
            Bucket=bucket, Prefix=f"inference/{study}/") for o in p.get("Contents", [])]
        rep.check(label, "inference", any(k.endswith("request.json") for k in objs),
                  f"SageMaker async request in S3: {len(objs)} objects under inference/{study}/")

    # 7 persist: the row is what the task reported
    rep.check(label, "worklist", row["lane"] == result["lane"] and row.get("model_id"),
              f"DynamoDB row lane {row['lane']}, model {row.get('model_id')}")

    # 8 cleanup
    left = {p: sum(len(pg.get("Contents", [])) for pg in s3.get_paginator(
        "list_objects_v2").paginate(Bucket=bucket, Prefix=p))
        for p in (f"transient/{run_id}/", prefix)}
    # Staging files from this run only: an earlier interrupted run's leftovers
    # expire through the lifecycle and are reported, not blamed on this run.
    staged = [o for pg in s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix="import/") for o in pg.get("Contents", []) if "/in/" in o["Key"]]
    mine = [o for o in staged if o["LastModified"].timestamp() >= t0 - 5]
    rep.check(label, "cleanup", not any(left.values()) and not mine,
              f"left behind: {left}, this run's import staging files: {len(mine)}"
              + (f" (older leftovers awaiting the lifecycle: {len(staged) - len(mine)})"
                 if len(staged) > len(mine) else ""))


def main() -> int:
    import boto3
    ap = argparse.ArgumentParser()
    ap.add_argument("--stack", default="Auralane")
    ap.add_argument("--state", default="Chhattisgarh")
    ap.add_argument("--timeout", type=int, default=2400)
    args = ap.parse_args()
    import core.run as run
    run.load_stack(args.stack)
    from core.upload import new_batch
    p = run.providers()
    cfn = boto3.client("cloudformation", region_name="us-east-1")
    log_group = next(r["PhysicalResourceId"] for r in cfn.list_stack_resources(
        StackName=args.stack)["StackResourceSummaries"]
        if r["ResourceType"] == "AWS::Logs::LogGroup" and r["LogicalResourceId"].startswith("IngestLogs"))
    ctx = {"s3": boto3.client("s3", region_name="us-east-1"), "logs": boto3.client("logs", region_name="us-east-1"),
           "bucket": run.os.environ["AURALANE_BUCKET"], "table": p["table"], "datastore": p["datastore"],
           "log_group": log_group, "state": args.state, "timeout": args.timeout}

    manifest = json.loads((ROOT / "data/chest/studies/manifest.json").read_text())
    chest = next(e for e in manifest if e["burned_in"])
    studies = [("chest", ROOT / "data/chest/studies" / chest["study_uid"], chest),
               ("brain", ROOT / "data/brain/dicom" / "1.2.826.0.1.3680043.10.1421.886290101693970615144718334374426294", None),
               ("ct", next(d for d in sorted((ROOT / "data/ct/raw").iterdir()) if d.is_dir()), None)]
    rep, batch = Report(), new_batch()
    for i, (label, path, burned) in enumerate(studies):
        run_one(label, path, f"{i:03d}", batch, ctx, rep, burned)
    fails = [r for r in rep.rows if not r[2]]
    print(f"\n{len(rep.rows) - len(fails)} of {len(rep.rows)} checks passed")
    for study, step, _, detail in fails:
        print(f"  FAILED {study}/{step}: {detail}")
    return 0 if rep.ok else 1


if __name__ == "__main__":
    sys.exit(main())
