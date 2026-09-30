"""HealthImagingDatastore: DatastorePort on AWS HealthImaging.

Reuses the existing datastore 293abea3292b4e888cbdf60e3a9ff283 (created by hand
for the smoke test). This provider never creates or deletes a datastore.

Write path. HealthImaging does not accept C-STORE. import_study stages the
study's DICOM files in S3 under import/<id>/in/, starts StartDICOMImportJob
with the import role, waits for it to finish, then finds the image set with
SearchImageSets by StudyInstanceUID. The staged files are deleted afterwards
(the stack also expires the import/ prefix after one day).

One study, several image sets. HealthImaging can split a study into more than
one primary image set: on 2026-09-28 a four-series brain MR came back as four,
one per series. A StudyRef's datastore_id therefore carries every primary
image set of the study, comma-separated, and each read finds the image set
that holds the series it asks for. A study in one image set is unchanged.

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
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote, urlencode

import boto3
import httpx
import pydicom
from botocore.auth import SigV4Auth, SigV4QueryAuth
from botocore.awsrequest import AWSRequest

from core.ports import DatastorePort
from core.providers.aws import session as shared
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
    service = "AWS HealthImaging"
    def __init__(self, bucket: str, import_role_arn: str,
                 datastore_id: str = EXISTING_DATASTORE_ID, region: str = REGION,
                 client=None, s3=None, session=None, dicomweb: str | None = None,
                 http: httpx.Client | None = None, poll_seconds: float = 5.0,
                 import_timeout: float = 1800.0):
        self.bucket, self.role, self.datastore_id, self.region = (
            bucket, import_role_arn, datastore_id, region)
        self.session = session or shared.session(region)
        self.mi = client or shared.client("medical-imaging", region)
        self.s3 = s3 or shared.client("s3", region)
        self.dicomweb = (dicomweb or _dicomweb_host(region)).rstrip("/")
        self.http = http or httpx.Client(timeout=60, limits=httpx.Limits(
            max_connections=32, max_keepalive_connections=32))
        self._docs: dict[str, dict] = {}       # image set id -> metadata document
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
        try:
            # Staged 16 at a time: a 620-slice MR is 620 round trips to us-east-1,
            # minutes when done one by one. Inside the try, so a failed or
            # interrupted upload is cleaned up too: one interrupted run on
            # 2026-09-28 left 331 staged files for the lifecycle to expire.
            with ThreadPoolExecutor(16) as pool:
                list(pool.map(lambda kp: self.s3.put_object(Bucket=self.bucket, Key=kp[0],
                                                            Body=kp[1].read_bytes()),
                              zip(keys, paths)))
            job = self.mi.start_dicom_import_job(
                jobName=f"auralane-{run[:12]}", dataAccessRoleArn=self.role, clientToken=run,
                datastoreId=self.datastore_id,
                inputS3Uri=f"s3://{self.bucket}/{prefix}/in/",
                outputS3Uri=f"s3://{self.bucket}/{prefix}/out/")
            self._reject_if_nothing_imported(self._wait(job["jobId"]))
        finally:
            with ThreadPoolExecutor(16) as pool:
                list(pool.map(lambda k: self.s3.delete_object(Bucket=self.bucket, Key=k), keys))
        return StudyRef(study_uid=study_uid, datastore_id=",".join(self._image_sets(study_uid)))

    def _wait(self, job_id: str) -> dict:
        deadline = time.monotonic() + self.import_timeout
        while True:
            props = self.mi.get_dicom_import_job(
                datastoreId=self.datastore_id, jobId=job_id)["jobProperties"]
            status = props["jobStatus"]
            if status == "COMPLETED":
                return props
            if status == "FAILED":
                raise RuntimeError(f"HealthImaging import job {job_id} failed: "
                                   f"{props.get('message', 'no message')}")
            if time.monotonic() > deadline:
                raise TimeoutError(f"HealthImaging import job {job_id} still {status} after "
                                   f"{self.import_timeout:.0f} s")
            time.sleep(self.poll_seconds)

    def _reject_if_nothing_imported(self, props: dict) -> None:
        """A job that COMPLETED can still have rejected every file: it makes no image set and says why in
        its output manifest. On 2026-10-01 the RSNA head CTs (no SOPClassUID in the dataset) came back as
        "no primary image set for study ...", which names nothing; the manifest said "DICOM attribute
        SOPClassUID does not exist" for all 18 files. So when nothing was imported, raise with HealthImaging's
        own words. Some files rejected among others imported is left as it was. Best effort: if the manifest
        cannot be read, the caller's lookup still fails as before."""
        try:
            bucket, _, key = props["outputS3Uri"].removeprefix("s3://").partition("/")
            base = key if key.endswith("/") else key + "/"
            summary = json.loads(self.s3.get_object(Bucket=bucket, Key=base + "job-output-manifest.json")
                                 ["Body"].read())["jobSummary"]
            scanned = int(summary.get("numberOfScannedFiles", 0))
            if int(summary.get("numberOfImportedFiles", 0)) or not scanned:
                return
            lines = self.s3.get_object(Bucket=bucket, Key=base + "FAILURE/failure.ndjson")["Body"].read()
            why = Counter(json.loads(l).get("exception", {}).get("message", "no message")
                          for l in lines.decode("utf-8", "replace").splitlines() if l.strip())
        except Exception:                                   # noqa: BLE001
            return
        detail = "; ".join(f"{m} ({n} {'file' if n == 1 else 'files'})" for m, n in why.most_common(3))
        raise RuntimeError(f"HealthImaging rejected {scanned} of {scanned} files and made no image set: "
                           f"{detail or 'no reason given'}")

    def _image_sets(self, study_uid: str) -> list[str]:
        """Every primary image set of the study, sorted, so the joined ref is stable."""
        hits = sorted(s["imageSetId"] for s in self._summaries(study_uid=study_uid))
        if not hits:
            raise LookupError(f"no primary image set for study {study_uid}")
        return hits

    @staticmethod
    def _ids(ref) -> list[str]:
        return [i for i in ref.datastore_id.split(",") if i]

    def _set_for(self, ref, series_uid: str) -> str:
        """The image set holding the series. One image set: no lookup."""
        ids = self._ids(ref)
        if len(ids) == 1:
            return ids[0]
        for i in ids:
            if series_uid in self._document(i)["Study"]["Series"]:
                return i
        raise LookupError(f"series {series_uid} is in none of study {ref.study_uid}'s "
                          f"image sets {ids}")

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
        by_study: dict[str, list[str]] = {}
        for s in self._summaries(**filters):
            by_study.setdefault(s["DICOMTags"]["DICOMStudyInstanceUID"], []).append(s["imageSetId"])
        out = []
        for uid, ids in by_study.items():
            meta = self.get_metadata(StudyRef(uid, ",".join(sorted(ids))))
            # SearchImageSets has no modality filter; apply it to the metadata.
            if "modality" not in filters or meta.modality == filters["modality"]:
                out.append(meta)
        return out

    def _document(self, image_set_id: str) -> dict:
        # Cached: the frame stream reads the document for every frame, and a
        # 620-slice series is 620 requests. An imported image set does not
        # change under us; the cache is small and per process.
        if image_set_id in self._docs:
            return self._docs[image_set_id]
        r = self.mi.get_image_set_metadata(datastoreId=self.datastore_id,
                                           imageSetId=image_set_id)
        raw = r["imageSetMetadataBlob"].read()
        if raw[:2] == b"\x1f\x8b":             # gzip, as documented; not assumed decoded
            raw = gzip.decompress(raw)
        doc = json.loads(raw)
        if len(self._docs) >= 32:
            self._docs.pop(next(iter(self._docs)))
        self._docs[image_set_id] = doc
        return doc

    def get_metadata(self, ref: StudyRef) -> StudyMeta:
        docs = [(i, self._document(i)) for i in self._ids(ref)]
        for i, d in docs:
            got = d["Study"]["DICOM"].get("StudyInstanceUID")
            if got not in (None, ref.study_uid):
                raise LookupError(f"image set {i} holds study {got}, not {ref.study_uid}")
        doc = docs[0][1]
        study = doc["Study"]["DICOM"]
        series, modalities = [], set()
        all_series = {s_uid: s for _, d in docs for s_uid, s in d["Study"]["Series"].items()}
        for s_uid, s in all_series.items():
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
        set_id = self._set_for(ref, series_uid)
        inst = self._document(set_id)["Study"]["Series"][series_uid]["Instances"][instance_uid]
        frame_id = inst["ImageFrames"][frame - 1]["ID"]
        r = self.mi.get_image_frame(datastoreId=self.datastore_id, imageSetId=set_id,
                                    imageFrameInformation={"imageFrameId": frame_id})
        return r["imageFrameBlob"].read()

    def frame_pixels(self, ref, series_uid, instance_uid, frame=1):
        """The frame decoded to its stored pixel values, for the API's streaming
        route (AURALANE_FRAME_MODE=proxy). HTJ2K decodes losslessly with
        OpenJPEG: the smoke test measured max absolute difference 0 against
        the source."""
        from openjpeg import decode       # pylibjpeg-openjpeg
        return decode(self.get_frame(ref, series_uid, instance_uid, frame))

    def _wado(self, ref, series_uid: str, path: str) -> str:
        return (f"{self.dicomweb}/datastore/{self.datastore_id}/studies/{quote(ref.study_uid)}"
                f"{path}?{urlencode({'imageSetId': self._set_for(ref, series_uid)})}")

    def frame_url(self, ref, series_uid, instance_uid, frame=1, ttl=300) -> str:
        """A presigned GetDICOMInstanceFrames URL, valid for ttl seconds. Signing
        is local: no request is made. See the module docstring for what is
        unverified about using it from a browser."""
        url = self._wado(ref, series_uid, f"/series/{quote(series_uid)}/instances/"
                                          f"{quote(instance_uid)}/frames/{int(frame)}")
        req = AWSRequest(method="GET", url=url)
        SigV4QueryAuth(self.session.get_credentials(), SIGNING_NAME, self.region,
                       expires=ttl).add_auth(req)
        return req.url

    def series_metadata(self, ref, series_uid) -> list[dict]:
        """DICOM JSON for the series via DICOMweb GetDICOMSeriesMetadata, signed
        server side. Headers only: any element carried as bulk data is dropped,
        as the Orthanc provider does."""
        url = self._wado(ref, series_uid, f"/series/{quote(series_uid)}/metadata")
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
