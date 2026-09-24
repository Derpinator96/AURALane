"""OrthancDatastore: the local stand-in for AWS HealthImaging.

STOW-RS to import, QIDO-RS to search, WADO-RS to retrieve, against Orthanc's
DICOMweb plugin. Same request shapes as scripts/orthanc_roundtrip.py, which
passes 12 of 12 against this stack.

datastore_id is Orthanc's own study identifier, looked up with POST
/tools/lookup (Orthanc REST API, checked against a live Orthanc 1.13.0 in this
build). It is deliberately a different value from the StudyInstanceUID, the
same way a HealthImaging ImageSetID is.
"""
from __future__ import annotations

import email.parser
import email.policy
import uuid
from pathlib import Path

import httpx
import pydicom

from core.ports import DatastorePort
from core.types import SeriesMeta, StudyMeta, StudyRef

BATCH = 50
FAILED_SOP_SEQUENCE = "00081198"
T = {"study_uid": "0020000D", "series_uid": "0020000E", "sop_uid": "00080018",
     "modality": "00080060", "modalities": "00080061", "date": "00080020",
     "time": "00080030", "patient_id": "00100020", "series_no": "00200011",
     "series_desc": "0008103E", "instance_no": "00200013"}
JSON = {"Accept": "application/dicom+json"}
FRAME_ACCEPT = 'multipart/related; type="application/octet-stream"; transfer-syntax=*'


def _v(item, key, default=None):
    v = item.get(T[key], {}).get("Value")
    return v[0] if v else default


def parse_multipart(content_type: str, body: bytes) -> list[bytes]:
    """Parts of a multipart/related WADO-RS response, as bytes."""
    msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
        f"Content-Type: {content_type}\r\n\r\n".encode() + body)
    return [p.get_payload(decode=True) for p in msg.iter_parts()]


class OrthancDatastore(DatastorePort):
    def __init__(self, base: str = "http://localhost:8042", timeout: float = 60):
        self.base = base.rstrip("/")
        self.web = f"{self.base}/dicom-web"
        self.http = httpx.Client(timeout=timeout)

    # -- write ---------------------------------------------------------------
    def import_study(self, dicom_paths: list[Path]) -> StudyRef:
        paths = [Path(p) for p in dicom_paths]
        uids = {str(pydicom.dcmread(p, stop_before_pixels=True).StudyInstanceUID)
                for p in paths}
        if len(uids) != 1:
            raise ValueError(f"import_study takes one study, got {len(uids)} StudyInstanceUIDs")
        study_uid = uids.pop()

        for i in range(0, len(paths), BATCH):
            boundary = uuid.uuid4().hex
            body = bytearray()
            for p in paths[i:i + BATCH]:
                body += f"--{boundary}\r\nContent-Type: application/dicom\r\n\r\n".encode()
                body += p.read_bytes() + b"\r\n"
            body += f"--{boundary}--\r\n".encode()
            r = self.http.post(f"{self.web}/studies", content=bytes(body), headers={
                "Content-Type": f'multipart/related; type="application/dicom"; boundary={boundary}',
                **JSON})
            r.raise_for_status()
            failed = r.json().get(FAILED_SOP_SEQUENCE, {}).get("Value", [])
            if failed:
                raise RuntimeError(f"STOW-RS refused {len(failed)} instances of {study_uid}")

        return StudyRef(study_uid=study_uid, datastore_id=self._orthanc_id(study_uid))

    def _orthanc_id(self, study_uid: str) -> str:
        r = self.http.post(f"{self.base}/tools/lookup", content=study_uid)
        r.raise_for_status()
        ids = [x["ID"] for x in r.json() if x.get("Type") == "Study"]
        if not ids:
            raise LookupError(f"Orthanc has no study {study_uid}")
        return ids[0]

    # -- read ----------------------------------------------------------------
    def _qido(self, path: str, params=None) -> list[dict]:
        r = self.http.get(f"{self.web}{path}", params=params, headers=JSON)
        if r.status_code == 204:
            return []
        r.raise_for_status()
        return r.json()

    def search(self, **filters) -> list[StudyMeta]:
        params = {}
        if "modality" in filters:
            params["ModalitiesInStudy"] = filters["modality"]
        if "study_date" in filters:
            params["StudyDate"] = filters["study_date"]
        if "study_uid" in filters:
            params["StudyInstanceUID"] = filters["study_uid"]
        unknown = set(filters) - {"modality", "study_date", "study_uid"}
        if unknown:
            raise ValueError(f"unsupported search filters: {sorted(unknown)}")
        out = []
        for item in self._qido("/studies", params):
            uid = _v(item, "study_uid")
            out.append(self.get_metadata(StudyRef(uid, self._orthanc_id(uid))))
        return out

    def get_metadata(self, ref: StudyRef) -> StudyMeta:
        study = self._qido("/studies", {"StudyInstanceUID": ref.study_uid,
                                        "includefield": [T["time"], T["patient_id"]]})
        if not study:
            raise LookupError(f"no study {ref.study_uid}")
        study = study[0]

        series, modalities = [], set()
        for s in self._qido(f"/studies/{ref.study_uid}/series",
                            {"includefield": [T["series_desc"], T["modality"]]}):
            s_uid = _v(s, "series_uid")
            modalities.add(_v(s, "modality"))
            inst = self._qido(f"/studies/{ref.study_uid}/series/{s_uid}/instances",
                              {"includefield": T["instance_no"]})
            inst.sort(key=lambda i: int(_v(i, "instance_no", 0)))
            no = _v(s, "series_no")
            series.append(SeriesMeta(
                series_uid=s_uid,
                number=int(no) if no is not None else None,
                description=_v(s, "series_desc", ""),
                instance_count=len(inst),
                instance_uids=tuple(_v(i, "sop_uid") for i in inst)))
        series.sort(key=lambda s: (s.number is None, s.number))

        if len(modalities) != 1:
            raise ValueError(f"study {ref.study_uid} mixes modalities {sorted(modalities)}")
        return StudyMeta(ref=ref, modality=modalities.pop(),
                         study_date=_v(study, "date", ""), study_time=_v(study, "time", ""),
                         series=tuple(series), patient_id=_v(study, "patient_id", ""))

    def frame_url(self, ref, series_uid, instance_uid, frame=1, ttl=300) -> str:
        """The WADO-RS frame URL itself. Orthanc URLs do not expire; ttl is
        accepted for interface parity and ignored. Fetch it with Accept set to
        FRAME_ACCEPT."""
        return (f"{self.web}/studies/{ref.study_uid}/series/{series_uid}"
                f"/instances/{instance_uid}/frames/{frame}")

    def get_frame(self, ref, series_uid, instance_uid, frame=1) -> bytes:
        r = self.http.get(self.frame_url(ref, series_uid, instance_uid, frame),
                          headers={"Accept": FRAME_ACCEPT})
        r.raise_for_status()
        parts = parse_multipart(r.headers["content-type"], r.content)
        if len(parts) != 1:
            raise RuntimeError(f"expected one frame part, got {len(parts)}")
        return parts[0]
