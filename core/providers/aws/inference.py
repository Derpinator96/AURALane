"""LambdaSageMakerInference: InferencePort on AWS Lambda (chest) and SageMaker
asynchronous endpoints (brain MR, head CT), chosen by the registry entry's
runtime and, for sagemaker-async, its output_type.

Both return exactly what InProcessInference returns, so the adapters and the
pipeline do not know which ran:

  lambda           {"preds": {pathology: raw sigmoid}, "evidence": {...}}
                   The pixels go to S3 as a PNG at native bit depth; the
                   function (infra/lambda/chest/app.py) runs the same
                   InProcessInference code, Grad-CAM included, writes the
                   overlays to S3 through S3Blob and returns the dict.
  sagemaker-async  metrics.json as a dict, with _prediction_path set to a local
                   copy of the predicted label map, as the brain adapter expects.
                   A 620-instance study takes tens of seconds and arrives as a
                   job, so the request is a JSON file in S3 naming the four
                   NIfTI inputs; the endpoint writes its answer to S3 and this
                   provider polls for it.
  ct-hemorrhage    triagelane-ct's study result as a dict (see
                   InProcessInference._ct_hemorrhage). The slices go to S3 as
                   one compressed .npz (pixels, slopes, intercepts); the
                   endpoint (infra/containers/ct/serve.py) returns the result.

Cold start, stated and not solved: the chest function is a container image
carrying torch, so an invocation after idle pays tens of seconds of image load,
imports and weight load before the first prediction. docs/AWS-COSTS.md gives the
estimate, how it was reasoned, and what provisioned concurrency would cost. The
brain endpoint scales to zero, so its first job after idle waits for an instance
to start. Neither has been measured: nothing has been deployed.
"""
from __future__ import annotations

import io
import sys
import json
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import boto3
import numpy as np
from botocore.config import Config
from botocore.exceptions import ClientError

from core.ports import InferencePort
from core.providers.aws.config import REGION
from core.types import StudyRef


def _png(pixels: np.ndarray) -> bytes:
    from PIL import Image
    if pixels.dtype not in (np.uint8, np.uint16):
        raise ValueError(f"expected uint8 or uint16 pixels, got {pixels.dtype}")
    buf = io.BytesIO()
    Image.fromarray(pixels).save(buf, format="PNG")
    return buf.getvalue()


def _split(uri: str) -> tuple[str, str]:
    u = urlparse(uri)
    if u.scheme != "s3":
        raise ValueError(f"not an s3:// URI: {uri!r}")
    return u.netloc, u.path.lstrip("/")


class LambdaSageMakerInference(InferencePort):
    def __init__(self, bucket: str, chest_function: str, brain_endpoint: str | None,
                 region: str = REGION, lambda_client=None, sagemaker_runtime=None, s3=None,
                 poll_seconds: float = 5.0, brain_timeout: float = 1800.0,
                 ct_endpoint: str | None = None):
        self.bucket, self.chest_function, self.brain_endpoint = bucket, chest_function, brain_endpoint
        self.ct_endpoint = ct_endpoint
        # Wait longer than the function may run (300 s, infra/auralane_stack.py)
        # and never retry an invoke: botocore's default 60 s read timeout re-invoked
        # a cold chest function twice, three model runs for one study.
        self.lam = lambda_client or boto3.client(
            "lambda", region_name=region,
            config=Config(read_timeout=330, retries={"total_max_attempts": 1}))
        self.smr = sagemaker_runtime or boto3.client("sagemaker-runtime", region_name=region)
        self.s3 = s3 or boto3.client("s3", region_name=region)
        self.poll_seconds, self.brain_timeout = poll_seconds, brain_timeout

    def score(self, ref: StudyRef, model_cfg: dict[str, Any], **inputs) -> Any:
        runtime = model_cfg["runtime"]
        if runtime == "lambda":
            return self._chest(ref, model_cfg, **inputs)
        if runtime == "sagemaker-async" and model_cfg.get("output_type") == "ct-hemorrhage":
            return self._ct(ref, model_cfg, **inputs)
        if runtime == "sagemaker-async":
            return self._brain(ref, model_cfg, **inputs)
        raise ValueError(f"no AWS handler for runtime {runtime!r}")

    # -- chest: Lambda, synchronous -------------------------------------------
    def _chest(self, ref, model_cfg, *, pixels: np.ndarray, **_) -> dict[str, Any]:
        key = f"inference/{ref.study_uid}/{uuid.uuid4().hex}/input.png"
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=_png(pixels))
        try:
            r = self.lam.invoke(FunctionName=self.chest_function,
                                InvocationType="RequestResponse",
                                Payload=json.dumps({"bucket": self.bucket, "input_key": key,
                                                    "study_uid": ref.study_uid,
                                                    "model_id": model_cfg["id"]}).encode())
            body = r["Payload"].read()
            if r.get("FunctionError"):
                raise RuntimeError(f"chest function {self.chest_function} failed "
                                   f"({r['FunctionError']}): {body[:500]!r}")
            out = json.loads(body)
        finally:
            self.s3.delete_object(Bucket=self.bucket, Key=key)
        if not isinstance(out, dict) or "preds" not in out:
            raise RuntimeError(f"chest function returned no preds: {str(out)[:200]}")
        return out

    # -- brain: SageMaker asynchronous endpoint -------------------------------
    def _brain(self, ref, model_cfg, *, nifti: dict[str, Path], **_) -> dict[str, Any]:
        if not self.brain_endpoint:
            raise RuntimeError("AURALANE_BRAIN_ENDPOINT is not set: the stack was deployed "
                               "with -c brain=false, or its outputs were not copied")
        prefix = f"inference/{ref.study_uid}/{uuid.uuid4().hex}"
        request = {"inputs": {}, "output_prefix": f"s3://{self.bucket}/{prefix}/out/"}
        for channel, path in nifti.items():
            key = f"{prefix}/{channel}{''.join(Path(path).suffixes)}"
            self.s3.put_object(Bucket=self.bucket, Key=key, Body=Path(path).read_bytes())
            request["inputs"][channel] = f"s3://{self.bucket}/{key}"
        self.s3.put_object(Bucket=self.bucket, Key=f"{prefix}/request.json",
                           Body=json.dumps(request).encode())
        r = self.smr.invoke_endpoint_async(
            EndpointName=self.brain_endpoint, ContentType="application/json",
            InputLocation=f"s3://{self.bucket}/{prefix}/request.json",
            InvocationTimeoutSeconds=900)
        metrics = json.loads(self._await(r["OutputLocation"], r.get("FailureLocation")))
        pred_bucket, pred_key = _split(metrics["_prediction_s3"])
        local = Path(tempfile.mkdtemp(prefix="auralane-seg-")) / "prediction.nii.gz"
        local.write_bytes(self.s3.get_object(Bucket=pred_bucket, Key=pred_key)["Body"].read())
        metrics["_prediction_path"] = str(local)
        return metrics

    # -- head CT: SageMaker asynchronous endpoint -----------------------------
    def _ct(self, ref, model_cfg, *, slices: list, **_) -> dict[str, Any]:
        if not self.ct_endpoint:
            raise RuntimeError("AURALANE_CT_ENDPOINT is not set: the stack was deployed "
                               "with -c ct=false, or its outputs were not copied")
        prefix = f"inference/{ref.study_uid}/{uuid.uuid4().hex}"
        buf = io.BytesIO()
        np.savez_compressed(buf, pixels=np.stack([px for px, _, _ in slices]),
                            slopes=np.array([s for _, s, _ in slices], dtype=np.float64),
                            intercepts=np.array([i for _, _, i in slices], dtype=np.float64))
        self.s3.put_object(Bucket=self.bucket, Key=f"{prefix}/slices.npz", Body=buf.getvalue())
        self.s3.put_object(Bucket=self.bucket, Key=f"{prefix}/request.json",
                           Body=json.dumps({"slices": f"s3://{self.bucket}/{prefix}/slices.npz"}).encode())
        r = self.smr.invoke_endpoint_async(
            EndpointName=self.ct_endpoint, ContentType="application/json",
            InputLocation=f"s3://{self.bucket}/{prefix}/request.json",
            InvocationTimeoutSeconds=900)
        return json.loads(self._await(r["OutputLocation"], r.get("FailureLocation"),
                                      self.ct_endpoint))

    def _exists(self, uri: str) -> bool:
        b, k = _split(uri)
        try:
            self.s3.head_object(Bucket=b, Key=k)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def _read(self, uri: str) -> bytes:
        b, k = _split(uri)
        return self.s3.get_object(Bucket=b, Key=k)["Body"].read()

    def _await(self, output: str, failure: str | None, endpoint: str | None = None) -> bytes:
        endpoint = endpoint or self.brain_endpoint
        start = time.monotonic()
        deadline = start + self.brain_timeout
        said = 0
        while True:
            if self._exists(output):
                return self._read(output)
            waited = int(time.monotonic() - start)
            if waited // 60 > said:             # a line a minute, so a long wait never looks hung
                said = waited // 60
                print(f"  waiting for {endpoint}: {waited} s (from zero instances, "
                      f"starting one takes several minutes)", file=sys.stderr, flush=True)
            if failure and self._exists(failure):
                raise RuntimeError(f"endpoint {endpoint} failed: "
                                   f"{self._read(failure)[:500]!r}")
            if time.monotonic() > deadline:
                raise TimeoutError(f"no answer from {endpoint} after "
                                   f"{self.brain_timeout:.0f} s (an endpoint scaled to zero "
                                   f"first has to start an instance)")
            time.sleep(self.poll_seconds)
