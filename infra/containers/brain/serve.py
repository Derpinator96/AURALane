"""Brain inference container for a SageMaker asynchronous endpoint.

Request (JSON, written by core/providers/aws/inference.py):
    {"inputs": {"T1c": "s3://...", "T1": ..., "T2": ..., "FLAIR": ...},
     "output_prefix": "s3://bucket/inference/<study>/<run>/out/"}
Response: Shaurya's metrics.json, as InProcessInference returns it, with
"_prediction_s3" naming the predicted label map it uploaded.

This runs the local InProcessInference brain path unchanged: the monai
precondition, then _external/brainmri's MRIPipeline. The image must be built on
a machine where that repository's Git LFS weights have been pulled.
"""
import tempfile
from pathlib import Path

import boto3

from core.providers.local.inference import InProcessInference
from core.registry import Registry
from core.types import StudyRef
from sagemaker_http import serve, split_s3

ENTRY = Registry().get("brain-brats-monai-v0.5.4")
INFER = InProcessInference()
S3 = boto3.client("s3")


def run(request: dict) -> dict:
    work = Path(tempfile.mkdtemp(prefix="auralane-brain-"))
    nifti = {}
    for channel, uri in request["inputs"].items():
        bucket, key = split_s3(uri)
        local = work / Path(key).name
        S3.download_file(bucket, key, str(local))
        nifti[channel] = local
    metrics = INFER.score(StudyRef("", ""), ENTRY, nifti=nifti)
    bucket, prefix = split_s3(request["output_prefix"])
    key = f"{prefix.rstrip('/')}/prediction.nii.gz"
    S3.upload_file(metrics.pop("_prediction_path"), bucket, key)
    metrics["_prediction_s3"] = f"s3://{bucket}/{key}"
    return metrics


if __name__ == "__main__":
    serve(run)
