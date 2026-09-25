"""Runner. The only place that chooses between local and AWS providers.

    AURALANE_RUNTIME=local python -m core.run ingest data/chest/studies/<study>
    AURALANE_RUNTIME=local python -m core.run serve            # API on :8080
    AURALANE_RUNTIME=local python -m core.run token radiologist  # dev token

AURALANE_RUNTIME is read once, in providers() below. Nothing else in the
codebase branches on runtime. It defaults to local.

serve listens on 8080 because 8000 belongs to the round-2 demo (server.py),
which has to start while this is running.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IDENTITY_DB = ROOT / "data" / "identity" / "identity.db"
DEV_KEY = ROOT / "data" / "dev" / "devauth.key"
DISCLAIMER = "NON-DIAGNOSTIC; DECISION SUPPORT ONLY"
LANE_ORDER = {"CRITICAL": 0, "URGENT": 1, "ABSTAIN": 2, "FAILED": 2, "EXPEDITED": 3,
              "ROUTINE": 4}


def providers() -> dict:
    runtime = os.environ.get("AURALANE_RUNTIME", "local")
    if runtime == "local":
        from core.providers import local as p
        return {"runtime": runtime, "blob": p.FileBlob(), "datastore": p.OrthancDatastore(),
                "table": p.DynamoLocalTable(), "inference": p.InProcessInference(),
                "auth": p.DevAuth(key_file=DEV_KEY), "llm": p.TemplateLLM()}
    if runtime == "aws":
        from core.providers import aws as p
        return {"runtime": runtime, "blob": p.S3Blob(), "datastore": p.HealthImagingDatastore(),
                "table": p.DynamoTable(), "inference": p.LambdaSageMakerInference(),
                "auth": p.CognitoAuth(), "llm": p.BedrockLLM()}
    sys.exit(f"AURALANE_RUNTIME must be local or aws, got {runtime!r}")


def _identity():
    sys.path.insert(0, str(ROOT / "sim" / "edge"))
    import identity
    IDENTITY_DB.parent.mkdir(parents=True, exist_ok=True)
    return identity.IdentityMap(str(IDENTITY_DB))


def cmd_ingest(args) -> int:
    from core.pipeline import ingest
    from core.registry import Registry
    p = providers()
    target = Path(args.path)
    files = sorted(target.rglob("*.dcm")) if target.is_dir() else [target]
    v = ingest(files, blob=p["blob"], datastore=p["datastore"], table=p["table"],
               inference=p["inference"], registry=Registry(), identity=_identity(),
               ocr_workers=args.ocr_workers)
    study = v.ref.study_uid if v.ref else None
    rows = p["table"].query("audit", study=study) if study else []
    print(DISCLAIMER)
    print(json.dumps({"status": v.status, "lane": v.lane, "study": study,
                      "model_id": v.model_id, "error": v.error,
                      "triage": {k: v.triage.get(k) for k in
                                 ("acuity", "driver", "signal", "confidence", "sla", "reason")
                                 if k in v.triage},
                      "evidence": v.findings.evidence if v.findings else {}}, indent=1))
    if rows:
        run_id = max(rows, key=lambda r: r["event_id"])["detail"]["run_id"]
        print("audit (this run):")
        for r in sorted(rows, key=lambda r: r["event_id"]):
            if r["detail"]["run_id"] == run_id:
                print(f"  {r['action']:<12} {r['outcome']:<6} {r['duration_ms']:>10.1f} ms")
    return 0 if v.status == "SCORED" else 1


def create_app(p: dict | None = None):
    """FastAPI app over the ports. Bearer token on every route except health."""
    from fastapi import Depends, FastAPI, Header, HTTPException

    from core.registry import Registry
    from core.types import StudyRef

    p = p or providers()
    app = FastAPI(title="AURALane API")
    Registry()                                   # startup error on a bad registry

    def principal(authorization: str = Header(default="")):
        if not authorization.startswith("Bearer "):
            raise HTTPException(401, "bearer token required")
        try:
            who = p["auth"].verify(authorization.removeprefix("Bearer "))
        except Exception as e:
            raise HTTPException(401, f"invalid token: {e}")
        if not {"radiologist", "admin"} & set(who.groups):
            raise HTTPException(403, "radiologist or admin group required")
        return who

    def row_or_404(study):
        row = p["table"].get_item("worklist", {"study": study})
        if row is None:
            raise HTTPException(404, "no such study")
        return row

    @app.get("/api/health")
    def health():
        return {"ok": True, "runtime": p["runtime"], "disclaimer": DISCLAIMER}

    @app.get("/api/worklist")
    def worklist(who=Depends(principal)):
        rows = p["table"].scan("worklist")
        rows.sort(key=lambda r: (LANE_ORDER.get(r["lane"], 9),
                                 -((r.get("triage") or {}).get("acuity") or 0),
                                 r["created_at"]))
        return {"disclaimer": DISCLAIMER, "studies": rows}

    @app.get("/api/studies/{study}")
    def study(study: str, who=Depends(principal)):
        row = row_or_404(study)
        audit = sorted(p["table"].query("audit", study=study), key=lambda r: r["event_id"])
        draft = p["llm"].draft({"study": study, "model_id": row["model_id"],
                                "lane": row["lane"], "triage": row.get("triage") or {},
                                "findings": row.get("findings") or {}})
        evidence = {k: p["blob"].presigned_url(v) for k, v in (row.get("evidence") or {}).items()
                    if k.endswith("_png")}
        return {"disclaimer": DISCLAIMER, "study": row, "audit": audit, "draft": draft,
                "evidence_urls": evidence}

    @app.get("/api/studies/{study}/frame_url")
    def frame_url(study: str, series: str, instance: str, frame: int = 1,
                  who=Depends(principal)):
        """A URL the browser fetches pixels from directly. The API never proxies them."""
        row = row_or_404(study)
        ref = StudyRef(study, row["datastore_id"])
        return {"url": p["datastore"].frame_url(ref, series, instance, frame)}

    return app


def cmd_serve(args) -> int:
    import uvicorn
    uvicorn.run(create_app(), host=args.host, port=args.port)
    return 0


def cmd_token(args) -> int:
    auth = providers()["auth"]
    if not hasattr(auth, "issue"):
        sys.exit("token issues development tokens and only exists with the local runtime")
    print(auth.issue(args.user))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m core.run")
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("ingest", help="de-identify, store, score and queue one study")
    i.add_argument("path", help="a study directory or one .dcm file")
    i.add_argument("--ocr-workers", type=int, default=None,
                   help="threads for de-identification OCR (default: CPU count)")
    s = sub.add_parser("serve", help="the worklist API")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8080)
    t = sub.add_parser("token", help="a development bearer token (local runtime only)")
    t.add_argument("user", choices=["radiologist", "admin"])
    args = ap.parse_args(argv)
    return {"ingest": cmd_ingest, "serve": cmd_serve, "token": cmd_token}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
