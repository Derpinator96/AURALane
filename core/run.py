"""Runner. The only place that chooses a provider set.

    AURALANE_RUNTIME=local   python -m core.run ingest data/chest/studies/<study>
    AURALANE_RUNTIME=local   python -m core.run serve     # API on :8100
    AURALANE_RUNTIME=fixture python -m core.run serve     # same API on the fixture rows
    AURALANE_RUNTIME=local   python -m core.run token radiologist

AURALANE_RUNTIME is read once, in providers() below: local (Orthanc, DynamoDB
Local, files), fixture (fixtures/worklist.json in memory, no Docker) or aws.
Nothing else in the codebase branches on runtime. It defaults to local.

serve listens on 8100 because 8000 belongs to the round-2 demo (server.py),
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
DEV_PASSWORD_FILE = ROOT / "data" / "dev" / "devauth.password"   # unless AURALANE_DEV_PASSWORD
BLOB_URL = "/api/blob"        # served by core.api from a FileBlob's signed URLs
DISCLAIMER = "NON-DIAGNOSTIC; DECISION SUPPORT ONLY"

def providers() -> dict:
    runtime = os.environ.get("AURALANE_RUNTIME", "local")
    if runtime == "local":
        from core.providers import local as p
        blob = p.FileBlob(url_base=BLOB_URL)
        # The browser reaches Orthanc through the web server's /dicom-web proxy
        # (client/vite.config.js); Orthanc itself sends no CORS headers.
        return {"runtime": runtime, "blob": blob,
                "datastore": p.OrthancDatastore(public_web="/dicom-web"),
                "table": p.DynamoLocalTable(), "inference": p.InProcessInference(blob=blob),
                "auth": p.DevAuth(key_file=DEV_KEY, password_file=DEV_PASSWORD_FILE), "llm": p.TemplateLLM()}
    if runtime == "fixture":
        from core.providers import fixture as f
        from core.providers import local as p
        table = f.FixtureTable()
        return {"runtime": runtime, "blob": p.FileBlob(f.BLOB, url_base=BLOB_URL),
                "datastore": f.FixtureDatastore(table), "table": table, "inference": None,
                "auth": p.DevAuth(key_file=DEV_KEY, password_file=DEV_PASSWORD_FILE), "llm": p.TemplateLLM()}
    if runtime == "aws":
        from core.providers import aws as p
        return {"runtime": runtime, "blob": p.S3Blob(), "datastore": p.HealthImagingDatastore(),
                "table": p.DynamoTable(), "inference": p.LambdaSageMakerInference(),
                "auth": p.CognitoAuth(), "llm": p.BedrockLLM()}
    sys.exit(f"AURALANE_RUNTIME must be local, fixture or aws, got {runtime!r}")


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


def cmd_serve(args) -> int:
    import uvicorn
    from core.api import create_app
    prov = providers()
    if prov["runtime"] != "aws" and not os.environ.get("AURALANE_DEV_PASSWORD"):
        print(f"dev sign-in password: {DEV_PASSWORD_FILE.relative_to(ROOT)}")
    uvicorn.run(create_app(prov), host=args.host, port=args.port)
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
    s.add_argument("--port", type=int, default=8100)
    t = sub.add_parser("token", help="a development bearer token (local runtime only)")
    t.add_argument("user", choices=["radiologist", "admin"])
    args = ap.parse_args(argv)
    return {"ingest": cmd_ingest, "serve": cmd_serve, "token": cmd_token}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
