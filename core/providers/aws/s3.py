"""S3Blob: BlobPort on Amazon S3.

Two kinds of image leave this system and they must not be confused:

  - Derived artefacts (Grad-CAM overlays, segmentation outlines) live here, in
    S3. The API hands the browser a presigned GET URL from presigned_url, and
    the browser fetches the PNG from S3. The API never reads the object to
    serve it.
  - DICOM frames live in the datastore (HealthImaging), never in this bucket's
    evidence prefix, and never pass through our API either: the browser fetches
    them with the short-lived signed URL HealthImagingDatastore.frame_url
    returns. See core/providers/aws/healthimaging.py.

The transient study copies the pipeline writes (transient/...) and the files
staged for a HealthImaging import (import/...) also live in this bucket; the
stack gives both prefixes a one-day lifecycle rule.
"""
from __future__ import annotations

import posixpath

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from core.ports import BlobPort
from core.providers.aws import session as shared
from core.providers.aws.config import REGION


def _clean(key: str) -> str:
    """The same refusal FileBlob makes: no key may climb out of the store."""
    norm = posixpath.normpath(key)
    if key.startswith("/") or norm.startswith("..") or norm != key.rstrip("/"):
        raise ValueError(f"blob key escapes the store: {key!r}")
    return key


class S3Blob(BlobPort):
    service = "Amazon S3"
    def __init__(self, bucket: str, client=None, region: str = REGION):
        self.bucket = bucket
        # SigV4 presigned URLs. Without this, botocore can still sign S3 URLs with
        # the deprecated Signature Version 2 (tests/test_aws_providers.py caught it).
        self.s3 = client or shared.client("s3", region, signature_version="s3v4")

    def put(self, key: str, data: bytes) -> str:
        self.s3.put_object(Bucket=self.bucket, Key=_clean(key), Body=data)
        return key

    def get(self, key: str) -> bytes:
        try:
            return self.s3.get_object(Bucket=self.bucket, Key=_clean(key))["Body"].read()
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                raise FileNotFoundError(key) from e
            raise

    def delete(self, key: str) -> None:
        self.s3.delete_object(Bucket=self.bucket, Key=_clean(key))

    def presigned_url(self, key: str, ttl: int = 300, check: bool = True) -> str:
        """A presigned S3 GET. For derived artefacts only (see module docstring).

        Like FileBlob, refuses a key that does not exist rather than signing a
        URL that would 404 in the browser. Signing itself makes no request."""
        if check:
            try:
                self.s3.head_object(Bucket=self.bucket, Key=_clean(key))
            except ClientError as e:
                if e.response["Error"]["Code"] in ("NoSuchKey", "404", "NotFound"):
                    raise FileNotFoundError(key) from e
                raise
        return self.s3.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=ttl)
