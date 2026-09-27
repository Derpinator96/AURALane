"""Brain inference container for a SageMaker asynchronous endpoint.

SageMaker's container contract: GET /ping answers 200 when ready, POST
/invocations does the work, both on port 8080. For an asynchronous endpoint
the request body is the object at the InputLocation the caller gave, and the
response body is written to the endpoint's S3 output path.

Request (JSON, written by core/providers/aws/inference.py):
    {"inputs": {"T1c": "s3://...", "T1": ..., "T2": ..., "FLAIR": ...},
     "output_prefix": "s3://bucket/inference/<study>/<run>/out/"}
Response: Shaurya's metrics.json, as InProcessInference returns it, with
"_prediction_s3" naming the predicted label map it uploaded.

This runs the local InProcessInference brain path unchanged: the monai
precondition, then _external/brainmri's MRIPipeline. The image must be built on
a machine where that repository's Git LFS weights have been pulled.
"""
import json
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

import boto3

from core.providers.local.inference import InProcessInference
from core.registry import Registry
from core.types import StudyRef

ENTRY = Registry().get("brain-brats-monai-v0.5.4")
INFER = InProcessInference()
S3 = boto3.client("s3")


def _split(uri):
    u = urlparse(uri)
    return u.netloc, u.path.lstrip("/")


def run(request: dict) -> dict:
    work = Path(tempfile.mkdtemp(prefix="auralane-brain-"))
    nifti = {}
    for channel, uri in request["inputs"].items():
        bucket, key = _split(uri)
        local = work / Path(key).name
        S3.download_file(bucket, key, str(local))
        nifti[channel] = local
    metrics = INFER.score(StudyRef("", ""), ENTRY, nifti=nifti)
    bucket, prefix = _split(request["output_prefix"])
    key = f"{prefix.rstrip('/')}/prediction.nii.gz"
    S3.upload_file(metrics.pop("_prediction_path"), bucket, key)
    metrics["_prediction_s3"] = f"s3://{bucket}/{key}"
    return metrics


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body=b"", ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send(200 if self.path == "/ping" else 404)

    def do_POST(self):
        if self.path != "/invocations":
            return self._send(404)
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            self._send(200, json.dumps(run(json.loads(body))).encode())
        except Exception as e:                   # the caller reads this from FailureLocation
            self._send(500, json.dumps({"error": f"{type(e).__name__}: {e}"}).encode())


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
