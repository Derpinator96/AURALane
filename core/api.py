"""The clinician API. FastAPI over the ports; python -m core.run serve, port 8100.

Port 8000 belongs to the round-2 demo (server.py), which is the fallback and
must run alongside this.

Access control is enforced here, per route, never by hiding a button:
    radiologist   worklist, studies, frame URLs, verdicts, drafts, simulated
                  ingest, distributing the worklist, their own history
    admin         audit log, lane mix, model registry, assignments, pipeline
                  view, /metrics (or AURALANE_METRICS_TOKEN)
An admin token on a study route is 403: admins configure the system, they do
not read patient studies. A radiologist token on an admin route is 403.

The API never returns pixels. frame-url returns a URL the browser fetches from
the datastore directly.

Two kinds of image leave this system, and the rule differs between them:
  - DICOM frames live in the datastore (Orthanc, HealthImaging). The browser
    fetches them from the datastore itself; the API never proxies them.
  - Evidence overlays (Grad-CAM, segmentation) are derived artefacts in blob
    storage. The API hands out BlobPort.presigned_url for them: an S3 presigned
    URL on AWS, or locally a signed /api/blob URL this app serves. Serving a
    derived PNG from blob storage is not proxying the datastore.

Every number in a response comes from a stored row or the registry. Nothing is
recomputed here, and the browser computes nothing.

NON-DIAGNOSTIC; DECISION SUPPORT ONLY.
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import os
import secrets
import threading
import time
import uuid
from collections import Counter
from typing import Any, Literal
from urllib.parse import quote, urlencode

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

import triage
from core import assign as assignment
from core import pipeline_view
from core.registry import Registry
from core.types import AuditEvent, Principal, StudyRef

DISCLAIMER = "NON-DIAGNOSTIC; DECISION SUPPORT ONLY"
NO_STUDY = "-"

# Round-2 queue order. Abstained and failed studies sit after URGENT: a human
# picks their lane, so they must be seen before routine work.
LANE_ORDER = {"CRITICAL": 0, "URGENT": 1, "ABSTAIN": 2, "FAILED": 2, "EXPEDITED": 3,
              "ROUTINE": 4}
LANE_LABEL = {"ABSTAIN": "NEEDS HUMAN TRIAGE", "FAILED": "PIPELINE FAILED"}
# Clock text from triage.LANES, the one source of the SLAs.
CLOCK = {name: label.replace("< ", "under ") for name, _, label, _ in triage.LANES}
CLOCK["ABSTAIN"] = "a human picks the lane"
CLOCK["FAILED"] = "processing did not complete"


class Login(BaseModel):
    username: str
    password: str


class AccessRequestIn(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z0-9._-]{3,64}$")
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)
    password: str = Field(min_length=8, max_length=256)
    role: Literal["radiologist", "admin"]


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject"]


class IntakeIn(BaseModel):
    count: int = Field(30, ge=1, le=60)


class VerdictIn(BaseModel):
    verdict: Literal["agree", "disagree"]


class Counts(BaseModel):
    chest: int = Field(0, ge=0, le=10)
    brain: int = Field(0, ge=0, le=3)
    ct: int = Field(0, ge=0, le=3)


class SimulateIn(BaseModel):
    counts: Counts
    readers: list[str] = Field(default_factory=list, max_length=50)


class DistributeIn(BaseModel):
    readers: list[str] = Field(min_length=1, max_length=50)


class ReassignIn(BaseModel):
    reader: str | None


class DraftIn(BaseModel):
    text: str = Field(max_length=20000)
    reviewed: bool = False


class AnnotationIn(BaseModel):
    modality: str | None = None
    series_id: str | None = None
    image_instance_id: str | None = None
    annotation_type: str = "pinpoint"
    note_text: str
    coordinate_space: str = "IMAGE_NORMALIZED"  # "NIFTI_WORLD" | "IMAGE_NORMALIZED" | "DICOM_PATIENT"
    coordinate_x: float | None = None
    coordinate_y: float | None = None
    coordinate_z: float | None = None
    voxel: dict[str, Any] | None = None
    world_mm: dict[str, Any] | None = None
    slice_index: int | None = None
    segmentation_region: str | None = None
    viewer_context: dict[str, Any] = {}
    metadata: dict[str, Any] = {}


class AnnotationPatch(BaseModel):
    note_text: str | None = None
    segmentation_region: str | None = None
    metadata: dict[str, Any] | None = None


UNASSIGNED = "Unassigned"          # no registered model for the study's modality
CLOCK_MIN = {name: mins for name, _, _, mins in triage.LANES}
# The NIfTI the 3D viewer can load, by the name the client asks for.
SEQUENCES = {"t1c": "T1c", "t1ce": "T1c", "t1": "T1", "t2": "T2", "flair": "FLAIR"}

# Origins allowed to call the API from a browser when none are configured: the
# Vite dev server and vite preview. In development the proxy makes every call
# same-origin anyway; these matter when the client calls the API directly.
DEV_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173",
               "http://localhost:4173", "http://127.0.0.1:4173")


def _label(name: str | None) -> str | None:
    """Finding name for display: underscores to spaces, first letter capital."""
    if not name:
        return None
    text = name.replace("_", " ")
    return text[:1].upper() + text[1:]


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def overdue(row: dict, now: datetime.datetime | None = None) -> bool:
    """A critical study, assigned, not opened by its reader within the lane's
    clock (triage.LANES), counted from arrival. No automatic reassignment.
    TODO: reassign automatically once this is agreed with the readers."""
    if row.get("lane") != "CRITICAL" or not row.get("assigned_to") or row.get("opened_at"):
        return False
    try:
        arrived = datetime.datetime.fromisoformat(row["created_at"])
    except (KeyError, TypeError, ValueError):
        return False
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return now - arrived > datetime.timedelta(minutes=CLOCK_MIN["CRITICAL"])


def create_app(p: dict, registry: Registry | None = None,
               cors_origins: list[str] | None = None) -> FastAPI:
    registry = registry or Registry()               # startup error on a bad registry
    app = FastAPI(title="AURALane API")
    # The hosted client is on another origin. Tokens travel in the Authorization
    # header, never in a cookie, so credentials stay off; a wildcard origin can
    # therefore never be combined with credentials.
    app.add_middleware(CORSMiddleware, allow_origins=list(cors_origins or DEV_ORIGINS),
                       allow_credentials=False, allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
                       allow_headers=["Authorization", "Content-Type"])

    def principal(authorization: str = Header(default="")) -> Principal:
        if not authorization.startswith("Bearer "):
            raise HTTPException(401, "bearer token required")
        try:
            return p["auth"].verify(authorization.removeprefix("Bearer "))
        except Exception as e:
            raise HTTPException(401, f"invalid token: {e}")

    def require(group: str):
        def dep(who: Principal = Depends(principal)) -> Principal:
            if group not in who.groups:
                raise HTTPException(403, f"{group} group required")
            return who
        return dep

    radiologist, admin = require("radiologist"), require("admin")
    superadmin = require("superadmin")

    # Readers: every radiologist account, with display name and reading pools
    # (core/assign.py). Cognito is asked at most once a minute.
    _readers: dict[str, Any] = {"at": -1e9, "value": []}

    def readers() -> list[dict]:
        if time.monotonic() - _readers["at"] > 60:
            try:
                _readers["value"] = assignment.directory(p["auth"])
            except Exception:                # e.g. no ListUsersInGroup permission yet
                _readers["value"] = []
            _readers["at"] = time.monotonic()
        return _readers["value"]

    def pick_readers(ids: list[str]) -> list[dict]:
        known = {r["id"]: r for r in readers()}
        unknown = [i for i in ids if i not in known]
        if unknown:
            raise HTTPException(400, f"not a radiologist account: {', '.join(unknown)}")
        return [known[i] for i in ids]

    def blob_url(key: str | None) -> str | None:
        return p["blob"].presigned_url(key) if key else None

    # Frames. With p["frame_proxy"] set (the aws runtime's default), frame URLs
    # point back at this API, which reads the frame from the datastore with its
    # own credentials and streams the decoded pixels. The URL carries a
    # five-minute HMAC signature, like a presigned URL, because the viewer's
    # loader sends no bearer token. The key is per process: a restart only
    # expires links early. Without frame_proxy the datastore's own URL is used.
    frame_proxy = p.get("frame_proxy")
    # TODO: a shared key (environment) if the API ever runs more than one instance.
    frame_key = secrets.token_bytes(32)

    def _frame_sig(path: str, expires: int) -> str:
        return hmac.new(frame_key, f"{path}|{expires}".encode(), hashlib.sha256).hexdigest()

    def frame_link(ref: StudyRef, series_uid: str, sop: str, frame: int = 1) -> str:
        if frame_proxy is None:
            return p["datastore"].frame_url(ref, series_uid, sop, frame)
        path = (f"/api/frames/{quote(ref.study_uid, safe='')}/{quote(series_uid, safe='')}/"
                f"{quote(sop, safe='')}/{int(frame)}")
        expires = int(time.time()) + 300
        return f"{frame_proxy}{path}?{urlencode({'expires': expires, 'sig': _frame_sig(path, expires)})}"

    def row_or_404(study: str) -> dict:
        row = p["table"].get_item("worklist", {"study": study})
        if row is None:
            raise HTTPException(404, "no such study")
        return row

    def pool_of(row: dict) -> str:
        """The reading pool: the registry entry's, else the one registered model
        for the row's modality (a study can fail before a model is chosen)."""
        entry = registry.entries.get(row.get("model_id") or "")
        if entry is None:
            try:
                entry = registry.for_modality(row.get("modality") or "")
            except LookupError:
                return UNASSIGNED
        return entry["reading_pool"]

    def view(row: dict) -> dict[str, Any]:
        """A worklist row as the client shows it. Values copied, not computed."""
        t = row.get("triage") or {}
        lane = row["lane"]
        entry = registry.entries.get(row.get("model_id") or "", {})
        driver = t.get("driver")
        return {
            "study": row["study"],
            "patient_id": row.get("patient_id"),
            "exam": f"{row.get('modality') or ''} {entry.get('body_part', '')}".strip(),
            "modality": row.get("modality"),
            "pool": pool_of(row),
            "model_id": row.get("model_id"),
            "arrived": row.get("created_at"),
            "lane": lane,
            "lane_label": LANE_LABEL.get(lane, lane),
            "clock": CLOCK.get(lane),
            "acuity": t.get("acuity"),
            "abstained": bool(t.get("abstained")) or lane == "ABSTAIN",
            "driver": driver,
            "driver_label": _label(driver),
            "confidence": t.get("confidence"),
            "abstain_reason": t.get("reason") if lane == "ABSTAIN" else None,
            "status": row.get("status"),
            "verdict": row.get("verdict"),
            "error": row.get("error"),
            "source": row.get("source"),
            "assigned_to": row.get("assigned_to"),
            "assigned_name": row.get("assigned_name"),
            "opened_at": row.get("opened_at"),
            "overdue": overdue(row),
        }

    def ordered(rows: list[dict]) -> list[dict]:
        return sorted(rows, key=lambda r: (LANE_ORDER.get(r["lane"], 9),
                                           -((r.get("triage") or {}).get("acuity") or 0),
                                           r.get("created_at") or ""))

    # -- open ---------------------------------------------------------------
    @app.get("/api/health")
    def health():
        """Uptime probe. No token, no table read, no model: an external monitor
        calls it every few minutes for as long as the service exists."""
        return {"runtime": p.get("runtime")}

    @app.post("/api/auth/login")
    def login(body: Login):
        try:
            token = p["auth"].login(body.username, body.password)
        except PermissionError:
            raise HTTPException(401, "unknown user or wrong password")
        who = p["auth"].verify(token)
        return {"token": token, "user": {"email": who.email, "groups": list(who.groups)}}

    @app.get("/api/me")
    def me(who: Principal = Depends(principal)):
        return {"email": who.email, "groups": list(who.groups), "disclaimer": DISCLAIMER}

    # -- radiologist --------------------------------------------------------
    @app.get("/api/worklist")
    def worklist(who: Principal = Depends(radiologist)):
        rows = ordered(p["table"].scan("worklist"))
        # The sections the client draws, in display order. Ordering lives here
        # only; the client does not know the lane ranking.
        lanes = [{"lane": lane, "label": LANE_LABEL.get(lane, lane), "clock": CLOCK[lane],
                  "pinned": lane in ("ABSTAIN", "FAILED")}
                 for lane in sorted(LANE_ORDER, key=lambda l: (LANE_ORDER[l], l != "ABSTAIN"))]
        studies = [view(r) for r in rows]
        # Reading pools: every registered pool, even when empty, in alphabetical
        # order, which is not a ranking. Ranking never crosses pools.
        names = {e["reading_pool"] for e in registry.entries.values()}
        names |= {s["pool"] for s in studies}
        pools = [{"pool": n, "label": n} for n in sorted(names, key=lambda n: (n == UNASSIGNED, n))]
        return {"disclaimer": DISCLAIMER, "pools": pools, "lanes": lanes, "studies": studies,
                "me": who.email, "readers": readers()}

    @app.get("/api/studies/{study}")
    def study(study: str, who: Principal = Depends(radiologist)):
        row = row_or_404(study)
        if row.get("assigned_to") == who.email and not row.get("opened_at"):
            # The assigned reader opened it: this stops the critical clock alarm.
            row["opened_at"] = _now()
            p["table"].put_item("worklist", row)
            p["table"].append_audit(AuditEvent(
                actor=who.email, action="open", study=study, at=row["opened_at"],
                outcome="ok", duration_ms=0.0,
                detail={"lane": row["lane"], "assigned_at": row.get("assigned_at")}))
        entry = registry.entries.get(row.get("model_id") or "", {})
        # Models outside the registry (head CT) carry their weights on the row.
        urgency = entry.get("urgency") or (row.get("triage") or {}).get("urgency_weights") or {}
        findings = sorted(({"name": k, "label": _label(k), "signal": v,
                            "urgency": urgency.get(k)}
                           for k, v in (row.get("findings") or {}).items()),
                          key=lambda f: -f["signal"])
        series = []
        if row.get("datastore_id"):
            meta = p["datastore"].get_metadata(StudyRef(study, row["datastore_id"]))
            series = [{"series_uid": s.series_uid, "number": s.number,
                       "description": s.description, "instance_count": s.instance_count,
                       "instance_uids": list(s.instance_uids)} for s in meta.series]
        draft = p["llm"].draft({"study": study, "model_id": row.get("model_id"),
                                "lane": row["lane"], "triage": row.get("triage") or {},
                                "findings": row.get("findings") or {}})
        evidence = dict(row.get("evidence") or {})
        evidence_urls = {k: p["blob"].presigned_url(v) for k, v in evidence.items()
                         if isinstance(v, str) and k.endswith("_png")}
        return {"disclaimer": DISCLAIMER, "study": view(row), "findings": findings,
                "top_findings": (row.get("triage") or {}).get("top_findings", []),
                "decision_reason": (row.get("triage") or {}).get("decision_reason"),
                "evidence": evidence, "evidence_urls": evidence_urls, "series": series,
                "draft": draft, "draft_review": row.get("draft_review"),
                # A datastore with no real DICOM behind it says so, and the viewer
                # shows it. Orthanc and HealthImaging have no note.
                "datastore_note": getattr(p["datastore"], "note", None)}

    @app.get("/api/studies/{study}/series/{series_uid}")
    def series(study: str, series_uid: str, who: Principal = Depends(radiologist)):
        """Per instance: the frame URL the browser fetches pixels from, and the
        DICOM header the viewer needs to decode them. Headers, never pixels."""
        row = row_or_404(study)
        ref = StudyRef(study, row["datastore_id"])
        try:
            items = p["datastore"].series_metadata(ref, series_uid)
        except LookupError as e:
            raise HTTPException(404, str(e))
        instances = []
        for meta in items:
            sop = meta["00080018"]["Value"][0]
            instances.append({"sop": sop, "metadata": meta,
                              "frame_url": frame_link(ref, series_uid, sop)})
        return {"series_uid": series_uid, "instances": instances}

    @app.get("/api/studies/{study}/frame-url")
    def frame_url(study: str, series: str, instance: str, frame: int = 1,
                  who: Principal = Depends(radiologist)):
        """A URL the browser fetches pixels from: the datastore's own, or, with
        frame_proxy, this API's signed streaming route."""
        row = row_or_404(study)
        try:
            url = frame_link(StudyRef(study, row["datastore_id"]), series, instance, frame)
        except LookupError as e:
            raise HTTPException(404, str(e))
        return {"url": url}

    @app.get("/api/frames/{study}/{series_uid}/{sop}/{frame}")
    def frame_pixels(study: str, series_uid: str, sop: str, frame: int, expires: int, sig: str):
        """Decoded pixels for one frame, uncompressed little-endian, which the
        viewer's loader reads as application/octet-stream. The signature in the
        URL is the credential. Only exists in use with frame_proxy."""
        if frame_proxy is None:
            raise HTTPException(404, "frames are not proxied by this API")
        path = (f"/api/frames/{quote(study, safe='')}/{quote(series_uid, safe='')}/"
                f"{quote(sop, safe='')}/{int(frame)}")
        if expires < time.time() or not hmac.compare_digest(sig, _frame_sig(path, expires)):
            raise HTTPException(403, "frame link expired or not signed by this API")
        row = row_or_404(study)
        try:
            pixels = p["datastore"].frame_pixels(StudyRef(study, row["datastore_id"]),
                                                 series_uid, sop, frame)
        except (LookupError, KeyError, IndexError) as e:
            raise HTTPException(404, f"no such frame: {e}")
        return Response(pixels.tobytes(), media_type="application/octet-stream",
                        headers={"Cache-Control": "private, max-age=300"})

    @app.post("/api/studies/{study}/verdict")
    def verdict(study: str, body: VerdictIn, who: Principal = Depends(radiologist)):
        """Agree or disagree with the lane. Audited; the row updates in place."""
        start = time.perf_counter()
        row = row_or_404(study)
        at = _now()
        row["verdict"] = {"value": body.verdict, "by": who.email, "at": at}
        p["table"].put_item("worklist", row)
        t = row.get("triage") or {}
        p["table"].append_audit(AuditEvent(
            actor=who.email, action="verdict", study=study, at=at, outcome="ok",
            duration_ms=round((time.perf_counter() - start) * 1000, 3),
            detail={"verdict": body.verdict, "lane": row["lane"], "acuity": t.get("acuity"),
                    "driver": t.get("driver"), "model_id": row.get("model_id")}))
        return {"disclaimer": DISCLAIMER, "study": view(row)}

    # -- Clinician Pinpoint Notes / Annotations -------------------------------
    def find_annotation(annotation_id: str) -> dict:
        """The table is keyed by (study, annotation_id); a note is addressed by
        its id alone, so it is found by scan. Notes are few."""
        for a in p["table"].scan("annotations"):
            if annotation_id in (a.get("annotation_id"), a.get("id")):
                return a
        raise HTTPException(404, "annotation not found")

    @app.get("/api/studies/{study}/annotations")
    def get_study_annotations(study: str, who: Principal = Depends(radiologist)):
        """Retrieve all spatially-anchored clinician annotations for a study."""
        annotations = p["table"].query("annotations", study=study)
        annotations.sort(key=lambda a: a.get("created_at") or "", reverse=False)
        return {"disclaimer": DISCLAIMER, "study": study, "annotations": annotations, "total": len(annotations)}

    @app.post("/api/studies/{study}/annotations")
    def create_study_annotation(study: str, body: AnnotationIn, who: Principal = Depends(radiologist)):
        """Create a persistent spatially anchored clinician note on a study."""
        start = time.perf_counter()
        row = p["table"].get_item("worklist", {"study": study})
        ann_id = f"ann-{uuid.uuid4().hex[:10]}"
        at = _now()
        modality = body.modality or (row.get("modality") if row else "MR")

        ann_item = {
            "id": ann_id,
            "annotation_id": ann_id,
            "study": study,
            "study_id": study,
            "series_id": body.series_id,
            "image_instance_id": body.image_instance_id,
            "modality": modality,
            "annotation_type": body.annotation_type,
            "note_text": body.note_text,
            "created_by": who.email,
            "created_at": at,
            "updated_at": at,
            "coordinate_space": body.coordinate_space,
            "coordinate_x": body.coordinate_x,
            "coordinate_y": body.coordinate_y,
            "coordinate_z": body.coordinate_z,
            "voxel": body.voxel,
            "world_mm": body.world_mm,
            "slice_index": body.slice_index,
            "segmentation_region": body.segmentation_region,
            "viewer_context": body.viewer_context,
            "metadata": body.metadata,
        }
        p["table"].put_item("annotations", ann_item)
        p["table"].append_audit(AuditEvent(
            actor=who.email, action="create_annotation", study=study, at=at, outcome="ok",
            duration_ms=round((time.perf_counter() - start) * 1000, 3),
            detail={"annotation_id": ann_id, "modality": modality, "coordinate_space": body.coordinate_space,
                    "segmentation_region": body.segmentation_region}))
        return {"disclaimer": DISCLAIMER, "annotation": ann_item}

    @app.get("/api/annotations/{annotation_id}")
    def get_annotation(annotation_id: str, who: Principal = Depends(radiologist)):
        """Fetch a single annotation by ID."""
        item = find_annotation(annotation_id)
        return {"disclaimer": DISCLAIMER, "annotation": item}

    @app.patch("/api/annotations/{annotation_id}")
    def patch_annotation(annotation_id: str, body: AnnotationPatch, who: Principal = Depends(radiologist)):
        """Update an existing clinician note's text or metadata."""
        start = time.perf_counter()
        item = find_annotation(annotation_id)

        at = _now()
        if body.note_text is not None:
            item["note_text"] = body.note_text
        if body.segmentation_region is not None:
            item["segmentation_region"] = body.segmentation_region
        if body.metadata is not None:
            item["metadata"] = {**(item.get("metadata") or {}), **body.metadata}
        item["updated_at"] = at
        item["updated_by"] = who.email

        p["table"].put_item("annotations", item)
        p["table"].append_audit(AuditEvent(
            actor=who.email, action="update_annotation", study=item.get("study") or NO_STUDY, at=at, outcome="ok",
            duration_ms=round((time.perf_counter() - start) * 1000, 3),
            detail={"annotation_id": annotation_id}))
        return {"disclaimer": DISCLAIMER, "annotation": item}

    @app.delete("/api/annotations/{annotation_id}")
    def delete_annotation(annotation_id: str, who: Principal = Depends(radiologist)):
        """Delete an annotation."""
        start = time.perf_counter()
        item = find_annotation(annotation_id)

        study = item.get("study") or item.get("study_id") or NO_STUDY
        p["table"].delete_item("annotations", {"study": study, "annotation_id": item["annotation_id"]})
        at = _now()
        p["table"].append_audit(AuditEvent(
            actor=who.email, action="delete_annotation", study=study, at=at, outcome="ok",
            duration_ms=round((time.perf_counter() - start) * 1000, 3),
            detail={"annotation_id": annotation_id}))
        return {"disclaimer": DISCLAIMER, "deleted": True, "annotation_id": annotation_id}


    @app.get("/api/blob/{key:path}")
    def blob(key: str, expires: int, sig: str):
        """Evidence PNGs behind a local presigned URL. The signature and expiry in
        the URL are the credential, as with an S3 presigned URL, so no bearer
        token is needed. Only providers that sign locally (FileBlob) have
        open_signed; S3 URLs never point here."""
        opener = getattr(p["blob"], "open_signed", None)
        if opener is None:
            raise HTTPException(404, "no local blob store")
        try:
            path = opener(key, expires, sig)
        except PermissionError as e:
            raise HTTPException(403, str(e))
        except (FileNotFoundError, ValueError):
            raise HTTPException(404, "no such object")
        return FileResponse(path, headers={"Cache-Control": "private, max-age=300"})


    @app.post("/api/studies/{study}/draft")
    def save_draft(study: str, body: DraftIn, who: Principal = Depends(radiologist)):
        """The radiologist's edit of the template draft, and whether they marked
        it reviewed. Stored on the row; audited without the text."""
        row = row_or_404(study)
        at = _now()
        row["draft_review"] = {"text": body.text, "reviewed": body.reviewed,
                               "by": who.email, "at": at}
        p["table"].put_item("worklist", row)
        p["table"].append_audit(AuditEvent(
            actor=who.email, action="draft_reviewed" if body.reviewed else "draft_saved",
            study=study, at=at, outcome="ok", duration_ms=0.0,
            detail={"lane": row["lane"], "chars": len(body.text)}))
        return {"disclaimer": DISCLAIMER, "draft_review": row["draft_review"]}

    # 3D viewer (NiiVue). The volumes are the model's own NIfTI inputs and its
    # segmentation, stored under evidence/ at ingest (core/pipeline.py). The
    # route answers with a presigned URL (S3, or this API's signed /api/blob),
    # never the bytes, the same rule as every other evidence image.
    def _evidence(study: str) -> dict:
        return row_or_404(study).get("evidence") or {}

    @app.get("/api/studies/{study}/volume/{sequence}")
    def study_volume(study: str, sequence: str, who: Principal = Depends(radiologist)):
        name = sequence.lower().split(".nii")[0].replace("-", "").replace("_", "")
        channel = SEQUENCES.get(name)
        key = (_evidence(study).get("volumes") or {}).get(channel)
        if not key:
            raise HTTPException(404, f"no {sequence} volume stored for this study; volumes are "
                                     f"kept for brain MR ingested by this build")
        return {"url": blob_url(key), "name": f"{channel.lower()}.nii.gz", "sequence": channel}

    @app.get("/api/studies/{study}/segmentation")
    def study_segmentation(study: str, who: Principal = Depends(radiologist)):
        key = _evidence(study).get("segmentation")
        if not key:
            raise HTTPException(404, "no segmentation stored for this study")
        return {"url": blob_url(key), "name": "segmentation.nii.gz"}

    @app.get("/api/studies/{study}/metrics")
    def study_metrics(study: str, who: Principal = Depends(radiologist)):
        """Volumes from the brain model's own metrics (adapters/brats.py)."""
        ev = _evidence(study)
        if not ev.get("volumes_cm3"):
            raise HTTPException(404, "no volumetry for this study")
        return {"volumes_cm3": ev["volumes_cm3"], "axial_index": ev.get("axial_index"),
                "basis": "the brain model's own segmentation (MONAI SegResNet), in cm3"}

    # -- readers and distribution ---------------------------------------------
    @app.get("/api/readers")
    def list_readers(who: Principal = Depends(principal)):
        if not ({"radiologist", "admin"} & set(who.groups)):
            raise HTTPException(403, "radiologist or admin group required")
        return {"readers": readers(), "pools": list(assignment.POOLS)}

    @app.post("/api/distribute")
    def distribute(body: DistributeIn, who: Principal = Depends(radiologist)):
        """Deal every unread study in priority order among the chosen readers.
        Refused, naming the pool, if a pool on the list has no chosen reader."""
        chosen = pick_readers(body.readers)
        rows = [r for r in ordered(p["table"].scan("worklist")) if not r.get("verdict")]
        items = [{"study": r["study"], "pool": pool_of(r), "lane": r["lane"], "row": r}
                 for r in rows]
        items = [i for i in items if i["pool"] != UNASSIGNED]
        try:
            dealt = assignment.deal(items, chosen)
        except LookupError as e:
            raise HTTPException(409, str(e))
        at = _now()
        for item, reader in dealt:
            row = item["row"]
            if row.get("assigned_to") != reader["id"]:
                assignment.assign_row(p["table"], row, reader, who.email, at,
                                      action="reassign" if row.get("assigned_to") else "assign")
        counts = Counter(r["id"] for _, r in dealt)
        critical = Counter(r["id"] for i, r in dealt if i["lane"] == "CRITICAL")
        return {"disclaimer": DISCLAIMER, "dealt": len(dealt),
                "readers": [{"id": r["id"], "name": r["name"], "studies": counts[r["id"]],
                             "critical": critical[r["id"]]} for r in chosen]}

    # -- simulated ingest --------------------------------------------------------
    def simulator():
        sim = p.get("simulate")
        if sim is None:
            raise HTTPException(409, "simulated ingest is not configured on this API")
        return sim

    @app.get("/api/simulate")
    def simulate_info(who: Principal = Depends(radiologist)):
        sim = p.get("simulate")
        if sim is None:
            return {"available": False, "reason": "not configured on this API",
                    "runtime": p.get("runtime")}
        return sim.info()

    @app.post("/api/simulate/estimate")
    def simulate_estimate(body: Counts, who: Principal = Depends(radiologist)):
        from core.simulate import estimate
        return estimate(body.model_dump(), p.get("runtime"))

    @app.post("/api/simulate", status_code=202)
    def simulate_start(body: SimulateIn, who: Principal = Depends(radiologist)):
        """Starts a batch in the background and returns its id at once. Studies
        reach the worklist one by one as each finishes. Audited."""
        sim = simulator()
        chosen = pick_readers(body.readers)
        try:
            state = sim.start(body.counts.model_dump(), chosen, who.email)
        except (ValueError, RuntimeError) as e:
            raise HTTPException(409, str(e))
        p["table"].append_audit(AuditEvent(
            actor=who.email, action="simulate_ingest", study=NO_STUDY, at=_now(), outcome="ok",
            duration_ms=0.0, detail={"batch": state["batch"], "counts": body.counts.model_dump(),
                                     "readers": body.readers,
                                     "estimate_usd": state["estimate"]["total_usd"]}))
        return state

    @app.get("/api/simulate/{batch}")
    def simulate_status(batch: str, who: Principal = Depends(radiologist)):
        try:
            return simulator().status(batch)
        except KeyError:
            raise HTTPException(404, "no such batch")

    @app.get("/api/me/history")
    def my_history(limit: int = 100, who: Principal = Depends(radiologist)):
        """This reader's own audit events (verdicts, opens, drafts, assignments
        they made). The full audit log stays admin only."""
        studies = {r["study"] for r in p["table"].scan("worklist")} | {NO_STUDY}
        events = [e for s in studies for e in p["table"].query("audit", study=s)
                  if e.get("actor") == who.email]
        events.sort(key=lambda e: e["event_id"], reverse=True)
        return {"disclaimer": DISCLAIMER, "total": len(events), "events": events[:limit]}

    # -- admin ----------------------------------------------------------------
    @app.get("/api/admin/audit")
    def audit(limit: int = 200, who: Principal = Depends(admin)):
        studies = {r["study"] for r in p["table"].scan("worklist")} | {NO_STUDY}
        events = [e for s in studies for e in p["table"].query("audit", study=s)]
        events.sort(key=lambda e: e["event_id"], reverse=True)
        return {"disclaimer": DISCLAIMER, "total": len(events), "events": events[:limit]}

    @app.get("/api/admin/lane-mix")
    def lane_mix(who: Principal = Depends(admin)):
        rows = p["table"].scan("worklist")
        counts = Counter(r["lane"] for r in rows)
        return {"disclaimer": DISCLAIMER, "total": len(rows),
                "lanes": [{"lane": lane, "label": LANE_LABEL.get(lane, lane),
                           "count": counts.get(lane, 0),
                           "percent": (round(100 * counts.get(lane, 0) / len(rows), 1)
                                       if rows else None)}
                          for lane in ("CRITICAL", "URGENT", "ABSTAIN", "EXPEDITED",
                                       "ROUTINE", "FAILED")],
                "basis": f"counted from {len(rows)} worklist rows at request time"
                         + (". Fixture rows were picked three per lane by make_fixtures.py, "
                            "so this is not a population lane mix"
                            if p.get("runtime") == "fixture" else "")}

    # -- access requests: sign up, then a super admin decides --------------------
    # The requester chooses their own password; it goes to the identity
    # provider's sign-up call and is never stored, logged or audited here. The
    # account cannot sign in, and has no group, until a super admin approves.
    @app.post("/api/access-requests", status_code=202)
    def request_access(body: AccessRequestIn):
        auth = p["auth"]
        if not hasattr(auth, "request_access"):
            raise HTTPException(409, "access requests go through Cognito on the deployed "
                                     "site; this runtime has fixed development users")
        if p["table"].get_item("access", {"username": body.username}):
            raise HTTPException(409, "a request for this username already exists")
        try:
            auth.request_access(body.username, body.email, body.password)
        except ValueError as e:
            raise HTTPException(400, str(e))
        at = _now()
        p["table"].put_item("access", {"username": body.username, "email": body.email,
                                       "role": body.role, "status": "pending",
                                       "requested_at": at})
        p["table"].append_audit(AuditEvent(
            actor=body.username, action="access_request", study=NO_STUDY, at=at,
            outcome="ok", duration_ms=0.0, detail={"role": body.role}))
        if p.get("notify"):
            p["notify"](f"AURALANE: {body.username} requests {body.role} access",
                        "\n".join([f"{body.username} <{body.email}> asked for {body.role} "
                                   f"access at {at}.",
                                   "Approve or reject it under Admin, Access requests.",
                                   "NON-DIAGNOSTIC; DECISION SUPPORT ONLY."]))
        return {"status": "pending", "username": body.username, "role": body.role}

    @app.get("/api/admin/access-requests")
    def access_requests(who: Principal = Depends(superadmin)):
        try:
            rows = p["table"].scan("access")
        except KeyError:
            rows = []
        rows.sort(key=lambda r: (r["status"] != "pending", r.get("requested_at", "")))
        return {"requests": rows}

    @app.post("/api/admin/access-requests/{username}")
    def decide_access(username: str, body: DecisionIn, who: Principal = Depends(superadmin)):
        row = p["table"].get_item("access", {"username": username})
        if not row:
            raise HTTPException(404, "no such access request")
        if row["status"] != "pending":
            raise HTTPException(409, f"already {row['status']}")
        start = time.perf_counter()
        if body.decision == "approve":
            p["auth"].approve(username, row["role"])
        else:
            p["auth"].reject(username)
        row.update(status="approved" if body.decision == "approve" else "rejected",
                   decided_by=who.email, decided_at=_now())
        p["table"].put_item("access", row)
        p["table"].append_audit(AuditEvent(
            actor=who.email, action=f"access_{row['status']}", study=NO_STUDY,
            at=row["decided_at"], outcome="ok",
            duration_ms=round((time.perf_counter() - start) * 1000, 3),
            detail={"username": username, "role": row["role"]}))
        return {"request": row}

    # -- simulated intake: real studies from this host's corpus ----------------
    @app.get("/api/admin/intake")
    def intake_status(who: Principal = Depends(admin)):
        sim = p.get("intake")
        if sim is None:
            return {"available": False, "reason": "not configured on this API",
                    "running": False, "catalogue": {}, "runtime": p.get("runtime")}
        return {**sim.status(), "runtime": p.get("runtime")}

    @app.post("/api/admin/intake", status_code=202)
    def intake_start(body: IntakeIn, who: Principal = Depends(admin)):
        """Starts a background run; poll GET /api/admin/intake. Audited."""
        sim = p.get("intake")
        if sim is None:
            raise HTTPException(409, "not configured on this API")
        start = time.perf_counter()
        try:
            state = sim.start(body.count, who.email)
        except RuntimeError as e:
            raise HTTPException(409, str(e))
        p["table"].append_audit(AuditEvent(
            actor=who.email, action="intake_simulation", study=NO_STUDY, at=_now(), outcome="ok",
            duration_ms=round((time.perf_counter() - start) * 1000, 3),
            detail={"requested": body.count, "studies": state.get("total"),
                    "runtime": p.get("runtime")}))
        return {**state, "runtime": p.get("runtime")}

    # -- assignments (admin) -----------------------------------------------------
    @app.get("/api/admin/assignments")
    def assignments(who: Principal = Depends(admin)):
        """Per reader: studies by lane, unread, and critical studies not opened
        within the lane clock. Study ids and lanes only: admins do not read studies."""
        rows = ordered(p["table"].scan("worklist"))
        per: dict[str, dict] = {}
        for r in readers():
            per[r["id"]] = {"id": r["id"], "name": r["name"], "pools": r["pools"],
                            "lanes": Counter(), "unread": 0, "overdue": 0, "total": 0}
        studies = []
        for row in rows:
            rid = row.get("assigned_to")
            late = overdue(row)
            studies.append({"study": row["study"], "lane": row["lane"],
                            "lane_label": LANE_LABEL.get(row["lane"], row["lane"]),
                            "modality": row.get("modality"), "pool": pool_of(row),
                            "arrived": row.get("created_at"), "assigned_to": rid,
                            "assigned_name": row.get("assigned_name"),
                            "assigned_at": row.get("assigned_at"),
                            "opened_at": row.get("opened_at"),
                            "read": bool(row.get("verdict")), "overdue": late})
            if rid is None:
                continue
            e = per.setdefault(rid, {"id": rid, "name": row.get("assigned_name") or rid,
                                     "pools": [], "lanes": Counter(), "unread": 0,
                                     "overdue": 0, "total": 0})
            e["lanes"][row["lane"]] += 1
            e["total"] += 1
            e["unread"] += 0 if row.get("verdict") else 1
            e["overdue"] += 1 if late else 0
        return {"disclaimer": DISCLAIMER, "lanes": list(LANE_ORDER),
                "lane_labels": {k: LANE_LABEL.get(k, k) for k in LANE_ORDER},
                "readers": [{**e, "lanes": dict(e["lanes"])} for e in per.values()],
                "unassigned": sum(1 for s in studies if not s["assigned_to"]),
                "studies": studies,
                "clock": f"A critical study turns red when its reader has not opened it within "
                         f"{CLOCK_MIN['CRITICAL']} minutes of arrival. Nothing is reassigned "
                         f"automatically."}

    @app.post("/api/admin/assignments/{study}")
    def reassign(study: str, body: ReassignIn, who: Principal = Depends(admin)):
        row = row_or_404(study)
        reader = pick_readers([body.reader])[0] if body.reader else None
        if reader and pool_of(row) not in reader["pools"]:
            raise HTTPException(409, f"{reader['name']} does not read the {pool_of(row)} pool")
        row = assignment.assign_row(p["table"], row, reader, who.email, _now(),
                                    action="reassign")
        return {"disclaimer": DISCLAIMER, "study": study, "assigned_to": row["assigned_to"],
                "assigned_name": row["assigned_name"]}

    # -- pipeline view (admin) and /metrics ---------------------------------------
    # Built from the audit trail only (core/pipeline_view.py). The whole picture
    # is recomputed at most every 10 seconds (one audit query per study); studies
    # in a simulate batch are read fresh on every call.
    _pipe: dict[str, Any] = {"at": -1e9, "value": None}
    _pipe_lock = threading.Lock()

    pipeline_view.set_runtime(p.get("runtime"))

    def _study_events(studies) -> dict[str, list[dict]]:
        # One query per study, sixteen at a time: sequential reads from Render
        # to us-east-1 took 11 s for 36 studies.
        studies = list(studies)
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(16) as pool:
            return dict(zip(studies, pool.map(lambda s: p["table"].query("audit", study=s), studies)))

    def _snapshot() -> dict[str, Any]:
        with _pipe_lock:
            if _pipe["value"] is None or time.monotonic() - _pipe["at"] > 10:
                rows = p["table"].scan("worklist")
                events = _study_events({r["study"] for r in rows})
                study_runs = {s: pipeline_view.latest_run(evs) for s, evs in events.items()}
                all_runs = [r for evs in events.values()
                            for r in pipeline_view.runs(evs).values()]
                _pipe["value"] = {"rows": rows, "study_runs": study_runs, "all_runs": all_runs}
                _pipe["at"] = time.monotonic()
            return _pipe["value"]

    @app.get("/api/admin/pipeline")
    def pipeline(who: Principal = Depends(admin)):
        snap = _snapshot()
        rows = snap["rows"]
        by_study = {r["study"]: r for r in rows}
        sim = p.get("simulate")
        flight = sim.in_flight() if sim is not None else {}
        live_events = _study_events(flight)
        live = []
        for study, item in flight.items():
            run = sorted((e for e in live_events[study]
                          if (e.get("detail") or {}).get("run_id") == item["run_id"]),
                         key=lambda e: e["event_id"])
            pos = pipeline_view.position(run)
            live.append({"study": study, "batch": item["batch"], "type": item["type"],
                         "modality": item["modality"], "status": item["status"],
                         "stage": pos["stage"],
                         "failed": pos["failed"] or item["status"] == "failed",
                         "done": item["status"] in ("done", "failed"),
                         "lane": pos.get("lane") or item.get("lane"),
                         "assigned_to": item.get("assigned_to"),
                         "end_to_end_ms": pipeline_view.end_to_end_ms(run)})
        recent = sorted(((s, r) for s, r in snap["study_runs"].items() if r),
                        key=lambda sr: sr[1][-1]["event_id"], reverse=True)[:20]
        late = [{"study": r["study"], "assigned_to": r.get("assigned_to"),
                 "assigned_name": r.get("assigned_name"), "arrived": r.get("created_at")}
                for r in rows if overdue(r)]
        return {"disclaimer": DISCLAIMER, "runtime": p.get("runtime"),
                "stages": pipeline_view.stages(snap["all_runs"]),
                "live": live,
                "batches": [{k: b[k] for k in ("batch", "running", "started_at",
                                               "finished_at", "by")}
                            for b in (sim.batches() if sim is not None else [])],
                "recent": [{"study": s, "modality": by_study.get(s, {}).get("modality"),
                            "lane": by_study.get(s, {}).get("lane"),
                            "end_to_end_ms": pipeline_view.end_to_end_ms(r),
                            "failed": any(e["outcome"] != "ok" for e in r)}
                           for s, r in recent],
                "totals": pipeline_view.totals(rows, snap["study_runs"], _now()[:10]),
                "overdue": late,
                "basis": "Every figure is counted from audit events the pipeline steps wrote "
                         "themselves. Nothing is estimated."}

    @app.get("/api/admin/pipeline/{study}")
    def pipeline_study(study: str, who: Principal = Depends(admin)):
        run = pipeline_view.latest_run(p["table"].query("audit", study=study))
        if not run:
            raise HTTPException(404, "no pipeline run recorded for this study")
        row = p["table"].get_item("worklist", {"study": study}) or {}
        return {"disclaimer": DISCLAIMER, "study": study, "modality": row.get("modality"),
                "lane": row.get("lane"), "model_id": row.get("model_id"),
                **pipeline_view.timeline(run)}

    metrics_token = os.environ.get("AURALANE_METRICS_TOKEN")

    @app.get("/metrics")
    def metrics(authorization: str = Header(default="")):
        """Prometheus text format. A scraper sends AURALANE_METRICS_TOKEN as a
        bearer token; otherwise an admin's token is required."""
        token = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
        if not (metrics_token and token and hmac.compare_digest(token, metrics_token)):
            who = principal(authorization)
            if "admin" not in who.groups:
                raise HTTPException(403, "admin group or the metrics token required")
        snap = _snapshot()
        return PlainTextResponse(pipeline_view.prometheus(snap["all_runs"], snap["rows"]),
                                 media_type="text/plain; version=0.0.4")

    @app.get("/api/admin/models")
    def models(who: Principal = Depends(admin)):
        return {"disclaimer": DISCLAIMER, "models": list(registry.entries.values()),
                "lanes": [{"lane": n, "acuity_floor": f, "clock": CLOCK[n]}
                          for n, f, _, _ in triage.LANES],
                "abstain_band": [triage.ABSTAIN_LO, triage.ABSTAIN_HI]}

    return app
