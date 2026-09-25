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
import time
from collections import Counter
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

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


class VerdictIn(BaseModel):
    verdict: Literal["agree", "disagree"]


def _label(name: str | None) -> str | None:
    """Finding name for display: underscores to spaces, first letter capital."""
    if not name:
        return None
    text = name.replace("_", " ")
    return text[:1].upper() + text[1:]


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def create_app(p: dict, registry: Registry | None = None) -> FastAPI:
    registry = registry or Registry()               # startup error on a bad registry
    app = FastAPI(title="AURALane API")

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

    def row_or_404(study: str) -> dict:
        row = p["table"].get_item("worklist", {"study": study})
        if row is None:
            raise HTTPException(404, "no such study")
        return row

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
        return {"ok": True, "disclaimer": DISCLAIMER}

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
        return {"disclaimer": DISCLAIMER, "lanes": lanes, "studies": [view(r) for r in rows]}

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
                "draft": draft}

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
                              "frame_url": p["datastore"].frame_url(ref, series_uid, sop)})
        return {"series_uid": series_uid, "instances": instances}

    @app.get("/api/studies/{study}/frame-url")
    def frame_url(study: str, series: str, instance: str, frame: int = 1,
                  who: Principal = Depends(radiologist)):
        """A URL the browser fetches pixels from directly. The API never proxies them."""
        row = row_or_404(study)
        try:
            url = p["datastore"].frame_url(StudyRef(study, row["datastore_id"]),
                                           series, instance, frame)
        except LookupError as e:
            raise HTTPException(404, str(e))
        return {"url": url}

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

    @app.get("/api/admin/models")
    def models(who: Principal = Depends(admin)):
        return {"disclaimer": DISCLAIMER, "models": list(registry.entries.values()),
                "lanes": [{"lane": n, "acuity_floor": f, "clock": CLOCK[n]}
                          for n, f, _, _ in triage.LANES],
                "abstain_band": [triage.ABSTAIN_LO, triage.ABSTAIN_HI]}

    return app
