"""HealthImagingDatastore: DatastorePort on AWS HealthImaging.

Reuses the existing datastore 293abea3292b4e888cbdf60e3a9ff283 (created by hand
for the smoke test). This provider never creates or deletes a datastore.

Write path. HealthImaging does not accept C-STORE. import_study stages the
study's DICOM files in S3 under import/<id>/in/, starts StartDICOMImportJob
with the import role, waits for it to finish, then finds the image set with
SearchImageSets by StudyInstanceUID. The staged files are deleted afterwards
(the stack also expires the import/ prefix after one day).

Read path. The cloud-native actions (SearchImageSets, GetImageSetMetadata,
GetImageFrame) through boto3. Pixels come back HTJ2K lossless; the smoke test
decoded a frame pixel-identical to its source (max absolute difference 0) at
56% of the uncompressed size. The contract test decodes frames by what they
are, not by who sent them.

Frames for the browser: the thin signing endpoint. The API's existing
/frame-url route calls frame_url, which returns a short-lived SigV4 presigned
URL for HealthImaging's DICOMweb GetDICOMInstanceFrames. The browser fetches the
frame from HealthImaging with it; our API never reads or proxies pixel data.
Derived evidence PNGs are different: they are S3 objects served by S3Blob's
presigned URLs (core/providers/aws/s3.py).

UNVERIFIED against the live service, and marked so here and in the report:
  - that DICOMweb accepts query-string (presigned) SigV4, and that it answers a
    browser on another origin with CORS headers. The CLAUDE.md smoke test only
    showed a header-signed QIDO-RS returning 200.
  - GetDICOMSeriesMetadata (series_metadata below) is taken from the
    HealthImaging developer guide's DICOMweb retrieve table; it has not been
    called on this account.
Bearer-token access is also untested until the Cognito pool exists.
HealthImaging supports OIDC for DICOMweb through a Lambda authorizer; if a
Cognito token works there from the browser, the signing endpoint can be
deleted and frame_url can return the plain DICOMweb URL.
"""
from __future__ import annotations

import gzip
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote, urlencode

import boto3
import httpx
import pydicom
from botocore.auth import SigV4Auth, SigV4QueryAuth
from botocore.awsrequest import AWSRequest

from core.ports import DatastorePort
from core.providers.aws.config import EXISTING_DATASTORE_ID, REGION
from core.types import SeriesMeta, StudyMeta, StudyRef

SIGNING_NAME = "medical-imaging"      # botocore service model metadata, signingName
FILTERS = {"modality", "study_date", "study_uid"}


def _dicomweb_host(region: str) -> str:
    # The DICOMweb endpoint, per the HealthImaging endpoints page. The SDK does
    # not model it; runtime-medical-imaging answers 404 for DICOMweb paths.
    return f"https://dicom-medical-imaging.{region}.amazonaws.com"


def _instance_number(item: dict) -> int:
    v = item.get("00200013", {}).get("Value")
    return int(v[0]) if v else 0


class HealthImagingDatastore(DatastorePort):
    def __init__(self, bucket: str, import_role_arn: str,
                 datastore_id: str = EXISTING_DATASTORE_ID, region: str = REGION,
                 client=None, s3=None, session=None, dicomweb: str | None = None,
                 http: httpx.Client | None = None, poll_seconds: float = 5.0,
                 import_timeout: float = 1800.0):
        self.bucket, self.role, self.datastore_id, self.region = (
            bucket, import_role_arn, datastore_id, region)
        self.session = session or boto3.Session(region_name=region)
        self.mi = client or self.session.client("medical-imaging", region_name=region)
        self.s3 = s3 or self.session.client("s3", region_name=region)
        self.dicomweb = (dicomweb or _dicomweb_host(region)).rstrip("/")
        self.http = http or httpx.Client(timeout=60)
        self.poll_seconds, self.import_timeout = poll_seconds, import_timeout

    # -- write ---------------------------------------------------------------
    def import_study(self, dicom_paths: list[Path]) -> StudyRef:
        paths = [Path(p) for p in dicom_paths]
        uids = {str(pydicom.dcmread(p, stop_before_pixels=True).StudyInstanceUID)
                for p in paths}
        if len(uids) != 1:
            raise ValueError(f"import_study takes one study, got {len(uids)} StudyInstanceUIDs")
        study_uid = uids.pop()

        run = uuid.uuid4().hex
        prefix = f"import/{run}"
        keys = [f"{prefix}/in/{i:05d}.dcm" for i in range(len(paths))]
        # Staged 16 at a time: a 620-slice MR is 620 round trips to us-east-1,
        # minutes when done one by one.
        with ThreadPoolExecutor(16) as pool:
            list(pool.map(lambda kp: self.s3.put_object(Bucket=self.bucket, Key=kp[0],
                                                        Body=kp[1].read_bytes()),
                          zip(keys, paths)))
        try:
            job = self.mi.start_dicom_import_job(
                jobName=f"auralane-{run[:12]}", dataAccessRoleArn=self.role, clientToken=run,
                datastoreId=self.datastore_id,
                inputS3Uri=f"s3://{self.bucket}/{prefix}/in/",
                outputS3Uri=f"s3://{self.bucket}/{prefix}/out/")
            self._wait(job["jobId"])
        finally:
            with ThreadPoolExecutor(16) as pool:
                list(pool.map(lambda k: self.s3.delete_object(Bucket=self.bucket, Key=k), keys))
        return StudyRef(study_uid=study_uid, datastore_id=self._image_set(study_uid))

    def _wait(self, job_id: str) -> None:
        deadline = time.monotonic() + self.import_timeout
        while True:
            props = self.mi.get_dicom_import_job(
                datastoreId=self.datastore_id, jobId=job_id)["jobProperties"]
            status = props["jobStatus"]
            if status == "COMPLETED":
                return
            if status == "FAILED":
                raise RuntimeError(f"HealthImaging import job {job_id} failed: "
                                   f"{props.get('message', 'no message')}")
            if time.monotonic() > deadline:
                raise TimeoutError(f"HealthImaging import job {job_id} still {status} after "
                                   f"{self.import_timeout:.0f} s")
            time.sleep(self.poll_seconds)

    def _image_set(self, study_uid: str) -> str:
        hits = [s for s in self._summaries(study_uid=study_uid)]
        if len(hits) != 1:
            raise LookupError(f"expected one primary image set for study {study_uid}, found "
                              f"{[s['imageSetId'] for s in hits]}")
        return hits[0]["imageSetId"]

    # -- read ----------------------------------------------------------------
    def _summaries(self, **filters) -> list[dict]:
        api = []
        if "study_uid" in filters:
            api.append({"operator": "EQUAL",
                        "values": [{"DICOMStudyInstanceUID": filters["study_uid"]}]})
        if "study_date" in filters:
            api.append({"operator": "EQUAL", "values": [
                {"DICOMStudyDateAndTime": {"DICOMStudyDate": filters["study_date"]}}]})
        kwargs = {"datastoreId": self.datastore_id}
        if api:
            kwargs["searchCriteria"] = {"filters": api}
        out = []
        for page in self.mi.get_paginator("search_image_sets").paginate(**kwargs):
            out += [s for s in page["imageSetsMetadataSummaries"] if s.get("isPrimary", True)]
        return out

    def search(self, **filters) -> list[StudyMeta]:
        unknown = set(filters) - FILTERS
        if unknown:
            raise ValueError(f"unsupported search filters: {sorted(unknown)}")
        out = []
        for s in self._summaries(**filters):
            uid = s["DICOMTags"]["DICOMStudyInstanceUID"]
            meta = self.get_metadata(StudyRef(uid, s["imageSetId"]))
            # SearchImageSets has no modality filter; apply it to the metadata.
            if "modality" not in filters or meta.modality == filters["modality"]:
                out.append(meta)
        return out

    def _document(self, image_set_id: str) -> dict:
        r = self.mi.get_image_set_metadata(datastoreId=self.datastore_id,
                                           imageSetId=image_set_id)
        raw = r["imageSetMetadataBlob"].read()
        if raw[:2] == b"\x1f\x8b":             # gzip, as documented; not assumed decoded
            raw = gzip.decompress(raw)
        return json.loads(raw)

    def get_metadata(self, ref: StudyRef) -> StudyMeta:
        doc = self._document(ref.datastore_id)
        study = doc["Study"]["DICOM"]
        if study.get("StudyInstanceUID") not in (None, ref.study_uid):
            raise LookupError(f"image set {ref.datastore_id} holds study "
                              f"{study.get('StudyInstanceUID')}, not {ref.study_uid}")
        series, modalities = [], set()
        for s_uid, s in doc["Study"]["Series"].items():
            d = s.get("DICOM", {})
            modalities.add(d.get("Modality"))
            inst = sorted(s.get("Instances", {}).items(),
                          key=lambda kv: int(kv[1].get("DICOM", {}).get("InstanceNumber") or 0))
            no = d.get("SeriesNumber")
            series.append(SeriesMeta(
                series_uid=s_uid, number=int(no) if no not in (None, "") else None,
                description=d.get("SeriesDescription") or "", instance_count=len(inst),
                instance_uids=tuple(uid for uid, _ in inst)))
        series.sort(key=lambda s: (s.number is None, s.number))
        if len(modalities) != 1:
            raise ValueError(f"study {ref.study_uid} mixes modalities {sorted(map(str, modalities))}")
        return StudyMeta(ref=ref, modality=modalities.pop(),
                         study_date=study.get("StudyDate") or "",
                         study_time=study.get("StudyTime") or "",
                         series=tuple(series),
                         patient_id=doc.get("Patient", {}).get("DICOM", {}).get("PatientID") or "")

    def get_frame(self, ref, series_uid, instance_uid, frame=1) -> bytes:
        """The stored frame (HTJ2K) via GetImageFrame. For server-side use; the
        browser uses frame_url."""
        inst = self._document(ref.datastore_id)["Study"]["Series"][series_uid]["Instances"][instance_uid]
        frame_id = inst["ImageFrames"][frame - 1]["ID"]
        r = self.mi.get_image_frame(datastoreId=self.datastore_id, imageSetId=ref.datastore_id,
                                    imageFrameInformation={"imageFrameId": frame_id})
        return r["imageFrameBlob"].read()

    def frame_pixels(self, ref, series_uid, instance_uid, frame=1):
        """The frame decoded to its stored pixel values, for the API's streaming
        route (AURALANE_FRAME_MODE=proxy). HTJ2K decodes losslessly with
        OpenJPEG: the smoke test measured max absolute difference 0 against
        the source."""
        from openjpeg import decode       # pylibjpeg-openjpeg
        return decode(self.get_frame(ref, series_uid, instance_uid, frame))

    def _wado(self, ref, path: str) -> str:
        return (f"{self.dicomweb}/datastore/{self.datastore_id}/studies/{quote(ref.study_uid)}"
                f"{path}?{urlencode({'imageSetId': ref.datastore_id})}")

    def frame_url(self, ref, series_uid, instance_uid, frame=1, ttl=300) -> str:
        """A presigned GetDICOMInstanceFrames URL, valid for ttl seconds. Signing
        is local: no request is made. See the module docstring for what is
        unverified about using it from a browser."""
        url = self._wado(ref, f"/series/{quote(series_uid)}/instances/{quote(instance_uid)}"
                              f"/frames/{int(frame)}")
        req = AWSRequest(method="GET", url=url)
        SigV4QueryAuth(self.session.get_credentials(), SIGNING_NAME, self.region,
                       expires=ttl).add_auth(req)
        return req.url

    def series_metadata(self, ref, series_uid) -> list[dict]:
        """DICOM JSON for the series via DICOMweb GetDICOMSeriesMetadata, signed
        server side. Headers only: any element carried as bulk data is dropped,
        as the Orthanc provider does."""
        url = self._wado(ref, f"/series/{quote(series_uid)}/metadata")
        req = AWSRequest(method="GET", url=url, headers={"Accept": "application/dicom+json"})
        SigV4Auth(self.session.get_credentials(), SIGNING_NAME, self.region).add_auth(req)
        r = self.http.get(url, headers=dict(req.headers))
        r.raise_for_status()
        items = r.json()
        for item in items:
            for tag in [t for t, v in item.items()
                        if "BulkDataURI" in v or "InlineBinary" in v or t == "7FE00010"]:
                del item[tag]
        items.sort(key=_instance_number)
        return items
