"""Chest inference on AWS Lambda (container image). Built by infra/, invoked by
core/providers/aws/inference.py.

Event: {"bucket", "input_key" (PNG at native bit depth), "study_uid", "model_id"}.
Returns what InProcessInference returns for the chest model:
{"preds": {pathology: raw sigmoid}, "evidence": {...}}, with the Grad-CAM
overlays written to the same bucket through S3Blob. One code path: this is the
local InProcessInference, given an S3Blob instead of a FileBlob.

The DenseNet weights are baked into the image at build time under /opt/xrv;
torchxrayvision looks for them under $HOME, so HOME is pinned here before it is
imported. Nothing is downloaded at run time.
"""
import io
import os

os.environ["HOME"] = "/opt/xrv"

import numpy as np                                   # noqa: E402
from PIL import Image                                # noqa: E402

from core.providers.aws.s3 import S3Blob              # noqa: E402
from core.providers.local.inference import InProcessInference   # noqa: E402
from core.registry import Registry                   # noqa: E402
from core.types import StudyRef                      # noqa: E402

_REGISTRY = Registry()
_MODELS: dict[str, InProcessInference] = {}          # one per bucket, kept warm between calls


def handler(event, context):
    bucket = event["bucket"]
    blob = S3Blob(bucket)
    infer = _MODELS.setdefault(bucket, InProcessInference(blob=blob))
    pixels = np.asarray(Image.open(io.BytesIO(blob.get(event["input_key"]))))
    entry = _REGISTRY.get(event["model_id"])
    return infer.score(StudyRef(event["study_uid"], ""), entry, pixels=pixels)
