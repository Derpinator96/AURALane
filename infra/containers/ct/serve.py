"""Head CT inference container for a SageMaker asynchronous endpoint.

Request (JSON, written by core/providers/aws/inference.py):
    {"slices": "s3://bucket/inference/<study>/<run>/slices.npz"}
    the npz holds pixels (N, rows, cols), slopes (N,), intercepts (N,), in
    position order.
    plus "study" and "bucket": Grad-CAM evidence for that study is written to
    s3://bucket/evidence/<study>/ (core/ct_gradcam.py).
Response: triagelane-ct's study result, exactly what
InProcessInference._ct_hemorrhage returns locally. One code path.

The ViT weights are baked into the image at build time from Hugging Face
(HF_HOME=/opt/hf); HF_HUB_OFFLINE=1 means nothing is downloaded at run time.
"""
import io

import boto3
import numpy as np

from core.providers.aws.s3 import S3Blob
from core.providers.local.inference import InProcessInference
from core.registry import Registry
from core.types import StudyRef
from sagemaker_http import serve, split_s3

ENTRY = Registry().get("ct-ich-vit-v1")
INFER = InProcessInference()
S3 = boto3.client("s3")


def run(request: dict) -> dict:
    bucket, key = split_s3(request["slices"])
    npz = np.load(io.BytesIO(S3.get_object(Bucket=bucket, Key=key)["Body"].read()))
    slices = list(zip(npz["pixels"], npz["slopes"].tolist(), npz["intercepts"].tolist()))
    INFER.blob = S3Blob(request.get("bucket") or bucket, client=S3)
    return INFER.score(StudyRef(request.get("study", ""), ""), ENTRY, slices=slices)


if __name__ == "__main__":
    serve(run)
