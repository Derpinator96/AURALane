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
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
IDENTITY_DB = ROOT / "data" / "identity" / "identity.db"
DEV_KEY = ROOT / "data" / "dev" / "devauth.key"
DEV_PASSWORD_FILE = ROOT / "data" / "dev" / "devauth.password"   # unless AURALANE_DEV_PASSWORD
BLOB_URL = "/api/blob"        # served by core.api from a FileBlob's signed URLs
DISCLAIMER = "NON-DIAGNOSTIC; DECISION SUPPORT ONLY"

# Serving beyond loopback means other machines reach DevAuth. Its password and
# signing key would otherwise come from data/dev (absent on a fresh host, so
# created with random values nobody can read) or be random per process (lost at
# every restart), and the evidence URLs would be relative to the wrong host. So
# a non-loopback serve refuses to start without these. AWS uses Cognito.
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
HOSTED_REQUIRED = {
    "AURALANE_DEV_PASSWORD": "the sign-in password for both development users",
    "AURALANE_DEV_JWT_SECRET": "the token signing key, so sessions survive a restart",
    "AURALANE_PUBLIC_URL": "this API's own public URL, e.g. https://<service>.onrender.com",
}


def _blob_url() -> str:
    """Where the API serves local blobs. Relative in development, where the Vite
    proxy shares one origin. When the client is hosted elsewhere, absolute from
    AURALANE_PUBLIC_URL: evidence overlays go straight into <img src>, so a
    relative URL would resolve against the client's host, which has no API."""
    return _public_url() + BLOB_URL


def _public_url() -> str:
    """This API's own URL when hosted (AURALANE_PUBLIC_URL), else empty: in
    development the Vite proxy puts client and API on one origin."""
    return os.environ.get("AURALANE_PUBLIC_URL", "").rstrip("/")


def cors_origins() -> list[str] | None:
    """AURALANE_CORS_ORIGINS, comma-separated; None means core.api's development
    defaults. Scheme and host only, no path: https://<project>.vercel.app"""
    raw = os.environ.get("AURALANE_CORS_ORIGINS", "")
    origins = []
    for item in raw.split(","):
        cleaned = item.strip().rstrip("/")
        if not cleaned:
            continue
        if "://" in cleaned:
            p = urlsplit(cleaned)
            cleaned = f"{p.scheme}://{p.netloc}"
        origins.append(cleaned)
    return origins or None


def providers(for_ingest: bool = False) -> dict:
    runtime = os.environ.get("AURALANE_RUNTIME", "local")
    if runtime == "local":
        from core.providers import local as p
        blob = p.FileBlob(url_base=_blob_url())
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
        return {"runtime": runtime, "blob": p.FileBlob(f.BLOB, url_base=_blob_url()),
                "datastore": f.FixtureDatastore(table), "table": table, "inference": None,
                "auth": p.DevAuth(key_file=DEV_KEY, password_file=DEV_PASSWORD_FILE), "llm": p.TemplateLLM()}
    if runtime == "aws":
        from core.providers import aws as p
        from core.providers.aws.config import (ENV, EXISTING_DATASTORE_ID, REQUIRED,
                                               REQUIRED_FOR_INGEST)
        from core.providers.local.llm import TemplateLLM
        need = REQUIRED_FOR_INGEST if for_ingest else REQUIRED
        missing = [ENV[k] for k in need if not os.environ.get(ENV[k])]
        if missing:
            sys.exit(f"AURALANE_RUNTIME=aws {'ingest' if for_ingest else 'serve'} needs "
                     f"{', '.join(missing)} (the CDK stack's outputs; see infra/README.md)")
        env = {k: os.environ.get(v) for k, v in ENV.items()}
        # Frames: "presigned" (default) hands the browser a SigV4 DICOMweb URL;
        # the browser fetches pixels from HealthImaging and the API never reads
        # them. Checked live on 2026-09-28: the CORS preflight for Cornerstone's
        # Accept header answers 200 (allow-origin *, allow-headers accept), and
        # the frame comes back as multipart/related, uncompressed. "proxy"
        # streams decoded pixels through this API instead: the fallback.
        proxy = os.environ.get("AURALANE_FRAME_MODE", "presigned") == "proxy"
        return {"runtime": runtime, "blob": p.S3Blob(env["bucket"]),
                "datastore": p.HealthImagingDatastore(
                    env["bucket"], env["import_role_arn"],
                    datastore_id=env["datastore_id"] or EXISTING_DATASTORE_ID),
                "table": p.DynamoTable(prefix=env["table_prefix"] or "auralane"),
                "inference": p.LambdaSageMakerInference(
                    env["bucket"], env["chest_function"], env["brain_endpoint"],
                    ct_endpoint=env["ct_endpoint"]) if for_ingest else None,
                "auth": p.CognitoAuth(env["user_pool_id"], env["client_id"]),
                # Bedrock is blocked at the account level; drafting ships on the
                # template everywhere, as decided on 2026-09-25.
                "llm": TemplateLLM(),
                "frame_proxy": _public_url() if proxy else None}
    sys.exit(f"AURALANE_RUNTIME must be local, fixture or aws, got {runtime!r}")


def _identity():
    sys.path.insert(0, str(ROOT / "sim" / "edge"))
    import identity
    IDENTITY_DB.parent.mkdir(parents=True, exist_ok=True)
    return identity.IdentityMap(str(IDENTITY_DB))


def regional_setting(state: str | None):
    """AURALANE_SITE_STATE (or --state) and AURALANE_REGIONAL_PRIOR, checked
    before anything is ingested: a mistyped state stops here, naming the valid
    ones."""
    from core.regional import setting
    try:
        return setting(state)
    except ValueError as e:
        sys.exit(str(e))


def cmd_ingest(args) -> int:
    from core.pipeline import ingest
    from core.registry import Registry
    p = providers(for_ingest=True)
    target = Path(args.path)
    files = sorted(target.rglob("*.dcm")) if target.is_dir() else [target]
    v = ingest(files, blob=p["blob"], datastore=p["datastore"], table=p["table"],
               inference=p["inference"], registry=Registry(), identity=_identity(),
               ocr_workers=args.ocr_workers, regional=regional_setting(args.state))
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
    # Checked before providers(): DevAuth would otherwise create a random
    # password file on this host before anyone saw the error.
    if (args.host not in LOOPBACK
            and os.environ.get("AURALANE_RUNTIME", "local") != "aws"):
        missing = [v for v in HOSTED_REQUIRED if not os.environ.get(v)]
        if missing:
            sys.exit(f"refusing to serve on {args.host}: set "
                     + "; ".join(f"{v} ({HOSTED_REQUIRED[v]})" for v in missing))
    import uvicorn
    from core.api import create_app
    prov = providers()
    if prov["runtime"] != "aws" and not os.environ.get("AURALANE_DEV_PASSWORD"):
        print(f"dev sign-in password: {DEV_PASSWORD_FILE.relative_to(ROOT)}")
    origins = cors_origins()
    print(f"CORS origins: {', '.join(origins) if origins else 'development defaults'}")
    uvicorn.run(create_app(prov, cors_origins=origins), host=args.host, port=args.port)
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
    i.add_argument("--state", default=None,
                   help="the site's Indian state for the chest regional prior; overrides "
                        "AURALANE_SITE_STATE for this ingest (never read from DICOM)")
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
