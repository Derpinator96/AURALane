"""A local HTTP stand-in for AWS HealthImaging, for tests only. No AWS call is
made and no credentials are needed.

moto does not implement HealthImaging, so this serves the wire formats the
real service documents, and the provider under test talks to it through real
botocore clients (serialisation, SigV4 signing, response parsing) with
endpoint_url pointed here:

  S3, path style      PUT/GET/HEAD/DELETE /{bucket}/{key}   (staging for import)
  control plane       POST /startDICOMImportJob/datastore/{id}
                      GET  /getDICOMImportJob/datastore/{id}/job/{job}
  runtime             POST /datastore/{id}/searchImageSets
                      POST /datastore/{id}/imageSet/{set}/getImageSetMetadata  (gzip JSON)
                      POST /datastore/{id}/imageSet/{set}/getImageFrame
  DICOMweb            GET  /datastore/{id}/studies/.../frames/{n}?imageSetId=   (presigned)
                      GET  /datastore/{id}/studies/.../series/{s}/metadata?imageSetId=

Paths and shapes come from the botocore service model (medical-imaging
2023-07-19) and the HealthImaging developer guide's metadata example.

Where it differs from the real service, on purpose:
  - frames are lossless JPEG 2000 (openjpeg), standing in for HTJ2K, which
    openjpeg cannot write. Both are J2K codestreams and decode the same way.
  - an import job reports IN_PROGRESS once, then COMPLETED; the work is done
    at submission.
  - presigned URLs are checked for the SigV4 query parameters and expiry, not
    by recomputing the signature.
"""
from __future__ import annotations

import gzip
import io
import json
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import openjpeg
import pydicom

DATASTORE = "fakedatastore0000000000000000000"


class FakeHealthImaging:
    def __init__(self, datastore_id: str = DATASTORE, split_series: bool = False):
        """split_series: one primary image set per series, as the live service
        made for a four-series brain MR on 2026-09-28."""
        self.datastore_id = datastore_id
        self.split_series = split_series
        self.objects: dict[tuple[str, str], bytes] = {}      # (bucket, key) -> bytes
        self.jobs: dict[str, dict] = {}
        self.image_sets: dict[str, dict] = {}                # id -> {"study_uid", "instances"}
        self.frames: dict[str, bytes] = {}                   # frame id -> J2K codestream
        self.calls: list[str] = []
        self.lock = threading.Lock()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()

    # -- the import job ------------------------------------------------------
    def _import(self, body: dict) -> dict:
        bucket, prefix = re.match(r"s3://([^/]+)/(.*)", body["inputS3Uri"]).groups()
        datasets = [pydicom.dcmread(io.BytesIO(data))
                    for (b, k), data in sorted(self.objects.items())
                    if b == bucket and k.startswith(prefix)]
        rejected = [ds for ds in datasets if "SOPClassUID" not in ds]      # the live service refuses these
        datasets = [ds for ds in datasets if "SOPClassUID" in ds]
        for ds in datasets:
            uid, series = str(ds.StudyInstanceUID), str(ds.SeriesInstanceUID)
            set_id = next((i for i, s in self.image_sets.items() if s["study_uid"] == uid
                           and (not self.split_series or s["series_uid"] == series)), None)
            if set_id is None:
                set_id = uuid.uuid4().hex
                self.image_sets[set_id] = {"study_uid": uid, "series_uid": series,
                                           "instances": {}, "created": time.time()}
            frame_id = uuid.uuid4().hex
            self.frames[frame_id] = bytes(openjpeg.encode(ds.pixel_array, bits_stored=ds.BitsStored,
                                                          use_mct=False))
            self.image_sets[set_id]["instances"][str(ds.SOPInstanceUID)] = (ds, frame_id)
        # The job's output manifest, as the live service writes it: a summary, and one line per rejected file.
        ob, okey = re.match(r"s3://([^/]+)/(.*)", body["outputS3Uri"]).groups()
        self.objects[(ob, okey + "job-output-manifest.json")] = json.dumps({"jobSummary": {
            "numberOfScannedFiles": len(datasets) + len(rejected), "numberOfImportedFiles": len(datasets),
            "numberOfFilesWithCustomerError": len(rejected), "numberOfFilesWithServerError": 0,
            "numberOfGeneratedImageSets": len({s for s in self.image_sets})}}).encode()
        self.objects[(ob, okey + "FAILURE/failure.ndjson")] = "\n".join(json.dumps({
            "inputFile": f"import/x/in/{i:05d}.dcm", "exception": {
                "exceptionType": "ValidationException", "message": "DICOM attribute SOPClassUID does not exist"}})
            for i, _ in enumerate(rejected)).encode()
        job_id = uuid.uuid4().hex
        self.jobs[job_id] = {"jobId": job_id, "jobName": body.get("jobName", ""),
                             "datastoreId": self.datastore_id,
                             "dataAccessRoleArn": body["dataAccessRoleArn"],
                             "inputS3Uri": body["inputS3Uri"], "outputS3Uri": body["outputS3Uri"],
                             "submittedAt": time.time(), "polls": 0}
        return {"datastoreId": self.datastore_id, "jobId": job_id, "jobStatus": "SUBMITTED",
                "submittedAt": time.time()}

    def _job(self, job_id: str) -> dict:
        job = self.jobs[job_id]
        job["polls"] += 1
        status = "IN_PROGRESS" if job["polls"] == 1 else "COMPLETED"
        props = {k: v for k, v in job.items() if k != "polls"}
        return {"jobProperties": {**props, "jobStatus": status}}

    # -- metadata, in HealthImaging's keyword-based shape --------------------
    def document(self, set_id: str) -> dict:
        s = self.image_sets[set_id]
        first = next(iter(s["instances"].values()))[0]
        series: dict = {}
        for sop, (ds, frame_id) in s["instances"].items():
            ser = series.setdefault(str(ds.SeriesInstanceUID), {"DICOM": {
                "Modality": ds.Modality, "SeriesInstanceUID": str(ds.SeriesInstanceUID),
                "SeriesNumber": str(ds.get("SeriesNumber", "")) or None,
                "SeriesDescription": ds.get("SeriesDescription", None)}, "Instances": {}})
            ser["Instances"][sop] = {
                "DICOM": {"SOPInstanceUID": sop, "InstanceNumber": str(ds.get("InstanceNumber", "")),
                          "Rows": ds.Rows, "Columns": ds.Columns, "PixelData": None},
                "ImageFrames": [{"ID": frame_id, "FrameSizeInBytes": len(self.frames[frame_id])}]}
        return {"SchemaVersion": "1.1", "DatastoreID": self.datastore_id, "ImageSetID": set_id,
                "Patient": {"DICOM": {"PatientID": str(first.PatientID),
                                      "PatientName": str(first.PatientName)}},
                "Study": {"DICOM": {"StudyInstanceUID": s["study_uid"],
                                    "StudyDate": first.StudyDate,
                                    "StudyTime": first.get("StudyTime", "")},
                          "Series": series}}

    def _summaries(self, body: dict) -> dict:
        # searchCriteria is the whole request body (botocore: payload=searchCriteria).
        filters = body.get("filters", [])
        out = []
        for set_id, s in self.image_sets.items():
            doc = self.document(set_id)
            ok = True
            for f in filters:
                v = f["values"][0]
                if "DICOMStudyInstanceUID" in v:
                    ok &= v["DICOMStudyInstanceUID"] == s["study_uid"]
                if "DICOMStudyDateAndTime" in v:
                    ok &= v["DICOMStudyDateAndTime"]["DICOMStudyDate"] == doc["Study"]["DICOM"]["StudyDate"]
            if ok:
                out.append({"imageSetId": set_id, "version": 1, "createdAt": s["created"],
                            "updatedAt": s["created"], "isPrimary": True,
                            "DICOMTags": {"DICOMStudyInstanceUID": s["study_uid"],
                                          "DICOMStudyDate": doc["Study"]["DICOM"]["StudyDate"],
                                          "DICOMPatientId": doc["Patient"]["DICOM"]["PatientID"]}})
        return {"imageSetsMetadataSummaries": out}

    # -- HTTP ----------------------------------------------------------------
    def _handler(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            # HTTP/1.1 so botocore's "Expect: 100-continue" on S3 PUTs is answered
            # at once instead of timing out per object.
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _send(self, code, body=b"", ctype="application/json", extra=None):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def _json(self, obj, code=200):
                self._send(code, json.dumps(obj).encode())

            def _body(self):
                return self.rfile.read(int(self.headers.get("Content-Length") or 0))

            def _route(self):
                u = urlparse(self.path)
                path, query = unquote(u.path), parse_qs(u.query)
                ds = fake.datastore_id
                with fake.lock:
                    fake.calls.append(f"{self.command} {path}")
                    if self.command == "POST" and path == f"/startDICOMImportJob/datastore/{ds}":
                        return self._json(fake._import(json.loads(self._body())))
                    m = re.fullmatch(rf"/getDICOMImportJob/datastore/{ds}/job/(\w+)", path)
                    if m and self.command == "GET":
                        return self._json(fake._job(m.group(1)))
                    if self.command == "POST" and path == f"/datastore/{ds}/searchImageSets":
                        return self._json(fake._summaries(json.loads(self._body() or b"{}")))
                    m = re.fullmatch(rf"/datastore/{ds}/imageSet/(\w+)/(getImageSetMetadata|getImageFrame)", path)
                    if m and self.command == "POST":
                        set_id, op = m.groups()
                        if set_id not in fake.image_sets:
                            return self._json({"message": "no such image set"}, 404)
                        if op == "getImageSetMetadata":
                            return self._send(200, gzip.compress(json.dumps(fake.document(set_id)).encode()),
                                              "application/json", {"Content-Encoding": "gzip"})
                        frame_id = json.loads(self._body())["imageFrameId"]
                        return self._send(200, fake.frames[frame_id], "application/octet-stream")
                    m = re.fullmatch(rf"/datastore/{ds}/studies/([^/]+)/series/([^/]+)"
                                     rf"(?:/instances/([^/]+)/frames/(\d+)|/metadata)", path)
                    if m and self.command == "GET":
                        return self._dicomweb(m, query)
                    m = re.fullmatch(r"/([^/]+)/(.+)", path)
                    if m:
                        return self._s3(*m.groups())
                    return self._json({"message": f"fake has no route {self.command} {path}"}, 404)

            def _dicomweb(self, m, query):
                study, series, sop, frame = m.groups()
                s = fake.image_sets.get(query.get("imageSetId", [""])[0])
                if s is None or s["study_uid"] != study:
                    return self._json({"message": "not found"}, 404)
                if sop:                                     # presigned frame URL
                    need = ("X-Amz-Algorithm", "X-Amz-Credential", "X-Amz-Date",
                            "X-Amz-Expires", "X-Amz-Signature")
                    if not all(k in query for k in need):
                        return self._json({"message": "missing SigV4 query auth"}, 403)
                    signed = datetime.strptime(query["X-Amz-Date"][0], "%Y%m%dT%H%M%SZ").replace(
                        tzinfo=timezone.utc).timestamp()
                    if time.time() > signed + int(query["X-Amz-Expires"][0]):
                        return self._json({"message": "expired"}, 403)
                    ds, frame_id = s["instances"][sop]
                    boundary = uuid.uuid4().hex
                    body = (f"--{boundary}\r\nContent-Type: application/octet-stream; "
                            f"transfer-syntax=1.2.840.10008.1.2.4.201\r\n\r\n").encode()
                    body += fake.frames[frame_id] + f"\r\n--{boundary}--\r\n".encode()
                    return self._send(200, body, f'multipart/related; type="application/octet-stream"; '
                                                 f"boundary={boundary}")
                if not self.headers.get("Authorization", "").startswith("AWS4-HMAC-SHA256"):
                    return self._json({"message": "missing SigV4 header"}, 403)
                items = []
                for ds, _ in s["instances"].values():
                    if str(ds.SeriesInstanceUID) != series:
                        continue
                    copy = pydicom.Dataset(ds)
                    del copy.PixelData
                    item = copy.to_json_dict()
                    item["7FE00010"] = {"vr": "OW", "BulkDataURI": "bulk"}   # as a real server would
                    items.append(item)
                return self._send(200, json.dumps(items).encode(), "application/dicom+json")

            def _s3(self, bucket, key):
                if self.command == "PUT":
                    fake.objects[(bucket, key)] = self._body()
                    return self._send(200, b"", "application/xml", {"ETag": '"fake"'})
                if (bucket, key) not in fake.objects:
                    if self.command == "DELETE":
                        return self._send(204)
                    return self._send(404, b"<Error><Code>NoSuchKey</Code></Error>", "application/xml")
                if self.command == "DELETE":
                    del fake.objects[(bucket, key)]
                    return self._send(204)
                return self._send(200, fake.objects[(bucket, key)], "application/octet-stream")

            do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = _route

        return H
