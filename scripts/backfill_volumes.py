"""Give brain MR studies ingested before volumes were kept a 3D view.

    python scripts/backfill_volumes.py --stack Auralane        # AWS
    python scripts/backfill_volumes.py                          # local runtime

For each MR worklist row with no stored volumes, reads its four series back
from the datastore (HealthImaging frames decode losslessly; see
core/providers/aws/healthimaging.py), rebuilds each channel as NIfTI with the
same builder the pipeline uses (core/volumes.series_to_nifti), writes them to
evidence/<study>/<channel>.nii.gz and adds them to the row. On AWS, for a
study that scored (not abstained), the model's own prediction is copied from
inference/<study>/*/out/prediction.nii.gz when it is still there, so the mask
shows too. An abstained study's mask failed its check and is never shown.
Audited as volume_backfill.

NON-DIAGNOSTIC; DECISION SUPPORT ONLY.
"""
from __future__ import annotations

import argparse
import datetime
import gzip
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pydicom

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _prediction(blob, study: str) -> str | None:
    """Copy the brain endpoint's stored prediction to evidence/, if it exists."""
    s3, bucket = getattr(blob, "s3", None), getattr(blob, "bucket", None)
    if s3 is None:
        return None
    keys = [o["Key"] for page in s3.get_paginator("list_objects_v2").paginate(
                Bucket=bucket, Prefix=f"inference/{study}/")
            for o in page.get("Contents", []) if o["Key"].endswith("/out/prediction.nii.gz")]
    if not keys:
        return None
    key = f"evidence/{study}/segmentation.nii.gz"
    s3.copy_object(Bucket=bucket, Key=key, CopySource={"Bucket": bucket, "Key": sorted(keys)[-1]})
    return key


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stack", help="CloudFormation stack (aws runtime)")
    ap.add_argument("--study", help="only this study")
    args = ap.parse_args()

    from core.run import load_stack, providers
    if args.stack:
        load_stack(args.stack)
    from core.registry import Registry
    from core.types import AuditEvent, StudyRef
    from core.volumes import series_to_nifti
    p, registry = providers(), Registry()
    ds_port, table, blob = p["datastore"], p["table"], p["blob"]

    rows = [r for r in table.scan("worklist") if r.get("modality") == "MR"
            and r.get("datastore_id") and (not args.study or r["study"] == args.study)
            and (not (r.get("evidence") or {}).get("volumes")
                 or (r.get("findings") and not (r.get("evidence") or {}).get("segmentation")))]
    print(f"{len(rows)} MR studies without volumes")
    for row in rows:
        start = time.perf_counter()
        ref = StudyRef(row["study"], row["datastore_id"])
        entry = registry.entries.get(row.get("model_id") or "") or registry.for_modality("MR")
        meta = ds_port.get_metadata(ref)
        try:
            channels = registry.adapter(entry).resolve_channels(meta.series, entry)
        except ValueError as e:
            print(f"  {row['study']}: skipped, {e}")
            continue
        volumes = dict((row.get("evidence") or {}).get("volumes") or {})
        for channel, series in channels.items():
            if channel in volumes:
                continue
            items = ds_port.series_metadata(ref, series.series_uid)
            headers = [pydicom.Dataset.from_json(i) for i in items]
            with ThreadPoolExecutor(16) as pool:
                frames = dict(zip((str(h.SOPInstanceUID) for h in headers), pool.map(
                    lambda h: ds_port.frame_pixels(ref, series.series_uid, str(h.SOPInstanceUID)),
                    headers)))
            img = series_to_nifti(headers, pixels=lambda h: frames[str(h.SOPInstanceUID)])
            volumes[channel] = blob.put(f"evidence/{row['study']}/{channel.lower()}.nii.gz",
                                        gzip.compress(img.to_bytes()))
            print(f"  {row['study'][-12:]} {channel}: {len(headers)} slices")
        seg = _prediction(blob, row["study"]) if row.get("findings") else None
        row = table.get_item("worklist", {"study": row["study"]})
        row["evidence"] = {**(row.get("evidence") or {}), "volumes": volumes}
        if seg:
            row["evidence"]["segmentation"] = seg
            print(f"  {row['study'][-12:]} segmentation from the model's stored prediction")
        table.put_item("worklist", row)
        table.append_audit(AuditEvent(
            actor="backfill", action="volume_backfill", study=row["study"],
            at=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            outcome="ok", duration_ms=round((time.perf_counter() - start) * 1000, 3),
            detail={"channels": sorted(volumes), "segmentation": bool(seg)}))
    _backfill_ct(args, table, ds_port, blob)
    return 0


def _backfill_ct(args, table, ds_port, blob) -> None:
    """Head CT rows ingested before the 3D view: the series with the most
    slices, read back from the datastore, as evidence/<study>/ct.nii.gz."""
    from core.types import AuditEvent, StudyRef
    from core.volumes import ct_volume_bytes
    rows = [r for r in table.scan("worklist") if r.get("modality") == "CT"
            and r.get("datastore_id") and (not args.study or r["study"] == args.study)
            and not ((r.get("evidence") or {}).get("volumes") or {}).get("CT")]
    print(f"{len(rows)} CT studies without a volume")
    for row in rows:
        start = time.perf_counter()
        ref = StudyRef(row["study"], row["datastore_id"])
        series = max(ds_port.get_metadata(ref).series, key=lambda s: s.instance_count)
        headers = [pydicom.Dataset.from_json(i)
                   for i in ds_port.series_metadata(ref, series.series_uid)]
        with ThreadPoolExecutor(16) as pool:
            frames = dict(zip((str(h.SOPInstanceUID) for h in headers), pool.map(
                lambda h: ds_port.frame_pixels(ref, series.series_uid, str(h.SOPInstanceUID)),
                headers)))
        key = blob.put(f"evidence/{row['study']}/ct.nii.gz", ct_volume_bytes(
            headers, pixels=lambda h: frames[str(h.SOPInstanceUID)]))
        row = table.get_item("worklist", {"study": row["study"]})
        row["evidence"] = {**(row.get("evidence") or {}),
                           "volumes": {**((row.get("evidence") or {}).get("volumes") or {}),
                                       "CT": key}}
        table.put_item("worklist", row)
        table.append_audit(AuditEvent(
            actor="backfill", action="volume_backfill", study=row["study"],
            at=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            outcome="ok", duration_ms=round((time.perf_counter() - start) * 1000, 3),
            detail={"channels": ["CT"], "slices": len(headers)}))
        print(f"  {row['study'][-12:]} CT: {len(headers)} slices")


if __name__ == "__main__":
    sys.exit(main())
