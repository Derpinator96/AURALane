"""The edge's only job in the cloud path: put a study's files in S3.

    upload/<batch>/<item>/00000.dcm ...   the study's files, as received
    upload/<batch>/<item>/_ready.json     written last: its arrival starts the
                                          ingest task (EventBridge rule on the
                                          suffix), so a half-uploaded study is
                                          never picked up

Everything after that runs in AWS (core/cloud_ingest.py): de-identification,
HealthImaging, the models, the worklist. The upload/ prefix is private,
encrypted, expires after one day, is deleted by the task once processed, and
the API's policy can write to it but never read from it. Nothing there is
indexed or searchable.

The demo corpus lives in S3 too (corpus/<modality>/<study>/), so the hosted
site's simulated intake can start arrivals by server-side copy, with nothing
downloaded.
"""
from __future__ import annotations

import datetime
import json
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

UPLOAD, CORPUS, RESULTS = "upload/", "corpus/", "intake/"
MANIFEST = "_ready.json"
MODALITIES = ("CR", "MR", "CT")


def new_batch() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + \
        secrets.token_hex(3)


def _manifest(s3, bucket: str, batch: str, item: str, keys: list[str],
              site_state: str | None, modality: str | None, **extra) -> str:
    key = f"{UPLOAD}{batch}/{item}/{MANIFEST}"
    body = {"batch": batch, "item": item, "keys": keys, "site_state": site_state,
            "modality": modality, "uploaded_at": datetime.datetime.now(
                datetime.timezone.utc).isoformat(timespec="seconds"), **extra}
    s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(body).encode(),
                  ContentType="application/json")
    return key


def upload_study(s3, bucket: str, files: list[Path], batch: str, item: str,
                 site_state: str | None = None, modality: str | None = None) -> str:
    """Local files -> upload/, 16 at a time, then the manifest. -> manifest key."""
    keys = [f"{UPLOAD}{batch}/{item}/{i:05d}.dcm" for i in range(len(files))]
    with ThreadPoolExecutor(16) as pool:
        list(pool.map(lambda kf: s3.put_object(Bucket=bucket, Key=kf[0], Body=kf[1].read_bytes()),
                      zip(keys, files)))
    return _manifest(s3, bucket, batch, item, keys, site_state, modality)


def copy_study(s3, bucket: str, source_prefix: str, batch: str, item: str,
               site_state: str | None = None, modality: str | None = None) -> str:
    """A corpus study -> upload/, server-side, then the manifest. -> manifest key."""
    src = [o["Key"] for page in s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix=source_prefix) for o in page.get("Contents", [])
        if o["Key"].endswith(".dcm")]
    keys = [f"{UPLOAD}{batch}/{item}/{i:05d}.dcm" for i in range(len(src))]
    with ThreadPoolExecutor(16) as pool:
        list(pool.map(lambda ks: s3.copy_object(Bucket=bucket, Key=ks[0],
                                                CopySource={"Bucket": bucket, "Key": ks[1]}),
                      zip(keys, src)))
    return _manifest(s3, bucket, batch, item, keys, site_state, modality)


def copy_pool_study(s3, bucket: str, pool_prefix: str, batch: str, item: str, *,
                    model_id: str, run_id: str, site_state: str | None = None,
                    modality: str | None = None) -> tuple[str, int]:
    """A staged, already de-identified pool study (stage_pool.py) -> upload/,
    server-side, with its edge report, then the manifest. The manifest marks it
    predeidentified: the ingest task checks the marks and does not clean it
    again. -> (manifest key, instances)."""
    src = [o["Key"] for page in s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix=pool_prefix) for o in page.get("Contents", [])]
    dcm = [k for k in src if k.endswith(".dcm")]
    report = next((k for k in src if k.endswith("/deid_report.json")), None)
    keys = [f"{UPLOAD}{batch}/{item}/{i:05d}.dcm" for i in range(len(dcm))]
    pairs = list(zip(keys, dcm))
    report_key = f"{UPLOAD}{batch}/{item}/deid_report.json" if report else None
    if report:
        pairs.append((report_key, report))
    with ThreadPoolExecutor(16) as pool:
        list(pool.map(lambda ks: s3.copy_object(Bucket=bucket, Key=ks[0],
                                                CopySource={"Bucket": bucket, "Key": ks[1]}),
                      pairs))
    return _manifest(s3, bucket, batch, item, keys, site_state, modality,
                     predeidentified=True, model_id=model_id, run_id=run_id,
                     report_key=report_key), len(dcm)


def wait_result(s3, bucket: str, key: str, timeout_s: float, poll_s: float) -> dict:
    """The result an ingest task writes (intake/<batch>/<item>.json), polled for until it is there.
    Raises TimeoutError, with the place to look, if it never arrives."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            return json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
        except s3.exceptions.NoSuchKey:
            time.sleep(poll_s)
    raise TimeoutError(f"the ingest task wrote no result in {int(timeout_s // 60)} min "
                       f"(see the IngestTask log group in CloudWatch)")


def corpus_catalogue(s3, bucket: str) -> dict[str, list[str]]:
    """{modality: [corpus/<modality>/<study>/ prefixes]} in S3."""
    out = {}
    for m in MODALITIES:
        prefixes = [p["Prefix"] for page in s3.get_paginator("list_objects_v2").paginate(
            Bucket=bucket, Prefix=f"{CORPUS}{m}/", Delimiter="/")
            for p in page.get("CommonPrefixes", [])]
        out[m] = sorted(prefixes)
    return out


def upload_corpus(s3, bucket: str, local: dict[str, list[Path]]) -> dict[str, int]:
    """This machine's corpus -> corpus/<modality>/<nn>/, once. Studies already
    there with the same file count are skipped. -> studies uploaded per modality."""
    have = corpus_catalogue(s3, bucket)
    counts = {}
    for m, dirs in local.items():
        counts[m] = 0
        for n, d in enumerate(dirs):
            prefix = f"{CORPUS}{m}/{n:03d}/"
            files = sorted(d.rglob("*.dcm"))
            if prefix in have.get(m, []):
                present = sum(1 for page in s3.get_paginator("list_objects_v2").paginate(
                    Bucket=bucket, Prefix=prefix) for _ in page.get("Contents", []))
                if present == len(files):
                    continue
            with ThreadPoolExecutor(16) as pool:
                list(pool.map(lambda iv: s3.put_object(
                    Bucket=bucket, Key=f"{prefix}{iv[0]:05d}.dcm", Body=iv[1].read_bytes()),
                    enumerate(files)))
            counts[m] += 1
    return counts
