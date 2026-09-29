"""The ingest task: one study, start to finish, inside AWS.

Runs on Fargate (infra/containers/ingest), started by an EventBridge rule when
an upload's manifest lands (upload/<batch>/<item>/_ready.json, core/upload.py).

    AURALANE_MANIFEST_KEY   the manifest's key, passed in by the rule
    AURALANE_IDENTITY_TABLE the identity map (core/providers/aws/identity.py)
    AURALANE_* the rest     the stack outputs, set on the task definition

Steps: read the manifest, download the raw files to the task's own disk, run
core.pipeline.ingest with the aws providers (de-identification first, then
HealthImaging, the model, the worklist), write the result to
intake/<batch>/<item>.json, delete the raw upload. The result holds only the
pseudonymous study UID, never an original identifier.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import boto3

from core.upload import RESULTS


def main() -> int:
    import core.run as run
    from core.pipeline import ingest
    from core.providers.aws.identity import DynamoIdentityMap
    from core.regional import RegionalSetting, states
    from core.registry import Registry

    bucket = os.environ["AURALANE_BUCKET"]
    manifest_key = os.environ["AURALANE_MANIFEST_KEY"]
    s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    manifest = json.loads(s3.get_object(Bucket=bucket, Key=manifest_key)["Body"].read())
    result_key = f"{RESULTS}{manifest['batch']}/{manifest['item']}.json"
    t0 = time.perf_counter()
    result = {"batch": manifest["batch"], "item": manifest["item"],
              "modality": manifest.get("modality"), "status": "FAILED", "lane": "FAILED"}
    try:
        with tempfile.TemporaryDirectory(prefix="auralane-upload-") as tmp:
            files = [Path(tmp) / f"{i:05d}.dcm" for i in range(len(manifest["keys"]))]
            with ThreadPoolExecutor(16) as pool:
                list(pool.map(lambda kf: s3.download_file(bucket, kf[0], str(kf[1])),
                              zip(manifest["keys"], files)))
            # The edge's site state wins; the task definition's is the default.
            state = manifest.get("site_state") or os.environ.get("AURALANE_SITE_STATE") or None
            regional = RegionalSetting(
                state=state if state in states() else None,
                enabled=os.environ.get("AURALANE_REGIONAL_PRIOR", "on").lower() != "off")
            p = run.providers(for_ingest=True)
            extra = {}
            identity = DynamoIdentityMap(os.environ["AURALANE_IDENTITY_TABLE"])
            if manifest.get("predeidentified"):
                # Staged and de-identified at the edge (scripts/stage_pool.py):
                # checked here, not cleaned again.
                identity, report = None, {}
                if manifest.get("report_key"):
                    report = json.loads(s3.get_object(
                        Bucket=bucket, Key=manifest["report_key"])["Body"].read())
                extra = {"edge_reports": report, "model_id": manifest.get("model_id"),
                         "run_id": manifest.get("run_id")}
            v = ingest(files, blob=p["blob"], datastore=p["datastore"], table=p["table"],
                       inference=p["inference"], registry=Registry(), identity=identity,
                       regional=regional, **extra)
        result.update(status=v.status, lane=v.lane, error=v.error,
                      study=v.ref.study_uid if v.ref else None)
    except Exception as e:                           # recorded, then the task exits non-zero
        result["error"] = f"{type(e).__name__}: {e}"
    finally:
        result["seconds"] = round(time.perf_counter() - t0, 1)
        s3.put_object(Bucket=bucket, Key=result_key, Body=json.dumps(result).encode(),
                      ContentType="application/json")
        # The raw upload is gone once processed; the 1-day lifecycle is the backstop.
        with ThreadPoolExecutor(16) as pool:
            list(pool.map(lambda k: s3.delete_object(Bucket=bucket, Key=k),
                          manifest["keys"] + [manifest_key]
                          + ([manifest["report_key"]] if manifest.get("report_key") else [])))
    print(json.dumps(result), flush=True)
    return 0 if result["status"] == "SCORED" else 1


if __name__ == "__main__":
    sys.exit(main())
