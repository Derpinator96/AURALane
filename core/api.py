"""The clinician API. FastAPI over the ports; python -m core.run serve, port 8100.

Port 8000 belongs to the round-2 demo (server.py), which is the fallback and
must run alongside this.

Access control is enforced here, per route, never by hiding a button:
    radiologist   worklist, studies, frame URLs, verdicts
    admin         audit log, lane mix, model registry
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
import secrets
import time
from collections import Counter
from typing import Any, Literal
from urllib.parse import quote, urlencode

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

import triage
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


UNASSIGNED = "Unassigned"          # no registered model for the study's modality

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


def create_app(p: dict, registry: Registry | None = None,
               cors_origins: list[str] | None = None) -> FastAPI:
    registry = registry or Registry()               # startup error on a bad registry
    app = FastAPI(title="AURALane API")
    # The hosted client is on another origin. Tokens travel in the Authorization
    # header, never in a cookie, so credentials stay off; a wildcard origin can
    # therefore never be combined with credentials.
    app.add_middleware(CORSMiddleware, allow_origins=list(cors_origins or DEV_ORIGINS),
                       allow_credentials=False, allow_methods=["GET", "POST"],
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
        return {"disclaimer": DISCLAIMER, "pools": pools, "lanes": lanes, "studies": studies}

    @app.get("/api/studies/{study}")
    def study(study: str, who: Principal = Depends(radiologist)):
        row = row_or_404(study)
        entry = registry.entries.get(row.get("model_id") or "", {})
        urgency = entry.get("urgency", {})
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
                "evidence": evidence, "evidence_urls": evidence_urls, "series": series,
                "draft": draft,
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

    @app.get("/api/admin/models")
    def models(who: Principal = Depends(admin)):
        return {"disclaimer": DISCLAIMER, "models": list(registry.entries.values()),
                "lanes": [{"lane": n, "acuity_floor": f, "clock": CLOCK[n]}
                          for n, f, _, _ in triage.LANES],
                "abstain_band": [triage.ABSTAIN_LO, triage.ABSTAIN_HI]}

    return app
