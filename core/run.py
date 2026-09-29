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
                "auth": _aws_auth(p, env),
                # Bedrock is blocked at the account level; drafting ships on the
                # template everywhere, as decided on 2026-09-25.
                "llm": TemplateLLM(),
                "frame_proxy": _public_url() if proxy else None,
                "notify": (p.SnsNotifier(env["access_topic"]) if env["access_topic"] else None)}
    sys.exit(f"AURALANE_RUNTIME must be local, fixture or aws, got {runtime!r}")


class _LoopbackAuth:
    """AURALANE_AUTH=dev on the aws runtime: development tokens against the
    real AWS data, for testing on this machine only (cmd_serve refuses any
    host but loopback). The reader list still comes from Cognito, and a token
    can be minted for any of those readers (python -m core.run token --as)."""

    def __init__(self, cognito):
        from core.providers.local import DevAuth
        self.dev, self.cognito = DevAuth(key_file=DEV_KEY, password_file=DEV_PASSWORD_FILE), cognito

    def login(self, username, password):
        return self.dev.login(username, password)

    def verify(self, token):
        return self.dev.verify(token)

    def readers(self):
        return self.cognito.readers()


def _aws_auth(p, env):
    cognito = p.CognitoAuth(env["user_pool_id"], env["client_id"])
    return _LoopbackAuth(cognito) if os.environ.get("AURALANE_AUTH") == "dev" else cognito


def _identity():
    sys.path.insert(0, str(ROOT / "sim" / "edge"))
    import identity
    IDENTITY_DB.parent.mkdir(parents=True, exist_ok=True)
    return identity.IdentityMap(str(IDENTITY_DB))


def load_stack(name: str) -> None:
    """AURALANE_RUNTIME=aws and every stack output not already set, read from the
    CloudFormation stack (each output's description is the variable name), so
    `serve --stack Auralane` and `ingest --stack Auralane` need nothing exported."""
    import boto3
    os.environ["AURALANE_RUNTIME"] = "aws"
    os.environ.setdefault("AWS_REGION", "us-east-1")
    cfn = boto3.client("cloudformation", region_name=os.environ["AWS_REGION"])
    for o in cfn.describe_stacks(StackName=name)["Stacks"][0].get("Outputs", []):
        os.environ.setdefault(o["Description"], o["OutputValue"])


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


def _intake(runtime: str):
    """The admin screen's simulated intake: real studies from this machine's
    corpus, ingested in a shuffled order. Unavailable, with the reason, where
    there is nothing to ingest or no pipeline to ingest with."""
    import threading
    from core.intake import IntakeSimulator, catalogue
    if runtime == "fixture":
        return IntakeSimulator(None, {}, unavailable="the fixture runtime has no pipeline")
    if runtime == "aws":
        # Cloud-native: arrivals are copied into S3 and ingested by tasks in AWS,
        # so this works from the hosted API, which holds no studies itself.
        import boto3
        from core.intake import CloudIntake
        from core.providers.aws.config import REGION
        bucket = os.environ.get("AURALANE_BUCKET")
        if not bucket:
            return IntakeSimulator(None, {}, unavailable="AURALANE_BUCKET is not set")
        return CloudIntake(boto3.client("s3", region_name=REGION), bucket,
                           site_state=os.environ.get("AURALANE_SITE_STATE") or None)
    from core.pipeline import ingest
    from core.regional import setting
    from core.registry import Registry
    try:
        regional = setting()
    except ValueError as e:
        return IntakeSimulator(None, {}, unavailable=str(e))
    local = threading.local()        # boto3 resources and SQLite are per thread

    def ingest_one(study_dir: Path):
        if not hasattr(local, "p"):
            local.p, local.identity, local.registry = (providers(for_ingest=True), _identity(),
                                                       Registry())
        p = local.p
        return ingest(sorted(study_dir.rglob("*.dcm")), blob=p["blob"], datastore=p["datastore"],
                      table=p["table"], inference=p["inference"], registry=local.registry,
                      identity=local.identity, regional=regional)

    # Local models share this process, so one study at a time; on AWS the
    # models are remote and three in flight keep the endpoints busy.
    return IntakeSimulator(ingest_one, catalogue(), workers=3 if runtime == "aws" else 1)


def _simulator(prov: dict):
    """Simulate ingest (radiologist screen): staged, edge-de-identified studies
    through the real pipeline. Unavailable, with the reason, where there is no
    pipeline or no pool."""
    import datetime
    import threading
    from core.assign import assign_row
    from core.simulate import LocalPool, S3Pool, Simulator
    runtime, table = prov["runtime"], prov["table"]

    def on_study(row, reader, actor):
        if reader is not None:
            assign_row(table, row, reader, actor,
                       datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"))

    if runtime == "fixture":
        return Simulator(None, None, table, runtime, unavailable=(
            "this preview serves fixed rows and has no pipeline; simulated ingest runs on "
            "the AWS runtime and locally"))
    from core.pipeline import ingest
    from core.regional import setting
    from core.registry import Registry
    try:
        regional = setting()
    except ValueError as e:
        return Simulator(None, None, table, runtime, unavailable=str(e))
    registry = Registry()
    if runtime == "aws":
        import boto3
        from core.providers.aws.config import REGION
        missing = [v for v in ("AURALANE_BUCKET", "AURALANE_CHEST_FUNCTION")
                   if not os.environ.get(v)]
        if missing:
            return Simulator(None, None, table, runtime,
                             unavailable=f"{', '.join(missing)} not set on this API")
        s3 = boto3.client("s3", region_name=REGION)
        pool = S3Pool(s3, os.environ["AURALANE_BUCKET"])
        if os.environ.get("AURALANE_SIMULATE_IN_API", "").lower() != "on":
            # Each study runs in its own Fargate ingest task (core/cloud_ingest.py):
            # the hosted API is small and holds no pixels. In-API ingest stays
            # behind AURALANE_SIMULATE_IN_API=on for a machine with the memory.
            from core.simulate import CloudDispatch
            return Simulator(pool, None, table, runtime, on_study=on_study, workers=8,
                             dispatch=CloudDispatch(
                                 s3, os.environ["AURALANE_BUCKET"],
                                 site_state=os.environ.get("AURALANE_SITE_STATE") or None))
        local = threading.local()        # boto3 resources are per thread

        def ingest_one(paths, **kw):
            if not hasattr(local, "p"):
                local.p = providers(for_ingest=True)
            p = local.p
            return ingest(paths, blob=p["blob"], datastore=p["datastore"], table=p["table"],
                          inference=p["inference"], registry=registry, identity=None,
                          regional=regional, **kw)
        # Four in flight: the models are remote. Brain MR, the memory peak (620
        # instances read, four volumes built), is held to one at a time.
        return Simulator(pool, ingest_one, table, runtime, on_study=on_study, workers=4)

    shared = {}

    def ingest_local(paths, **kw):
        if "p" not in shared:           # the models load once, on first use
            shared["p"] = providers(for_ingest=True)
        p = shared["p"]
        return ingest(paths, blob=p["blob"], datastore=p["datastore"], table=p["table"],
                      inference=p["inference"], registry=registry, identity=None,
                      regional=regional, **kw)
    # Local models share this process: one study at a time.
    return Simulator(LocalPool(), ingest_local, table, runtime, on_study=on_study, workers=1)


def cmd_serve(args) -> int:
    # Checked before providers(): DevAuth would otherwise create a random
    # password file on this host before anyone saw the error.
    if (args.host not in LOOPBACK
            and os.environ.get("AURALANE_RUNTIME", "local") != "aws"):
        missing = [v for v in HOSTED_REQUIRED if not os.environ.get(v)]
        if missing:
            sys.exit(f"refusing to serve on {args.host}: set "
                     + "; ".join(f"{v} ({HOSTED_REQUIRED[v]})" for v in missing))
    if os.environ.get("AURALANE_AUTH") == "dev" and args.host not in LOOPBACK:
        sys.exit("AURALANE_AUTH=dev is for this machine only: serve on 127.0.0.1")
    import uvicorn
    from core.api import create_app
    prov = providers()
    prov["intake"] = _intake(prov["runtime"])
    prov["simulate"] = _simulator(prov)
    if prov["runtime"] != "aws" and not os.environ.get("AURALANE_DEV_PASSWORD"):
        print(f"dev sign-in password: {DEV_PASSWORD_FILE.relative_to(ROOT)}")
    origins = cors_origins()
    print(f"CORS origins: {', '.join(origins) if origins else 'development defaults'}")
    uvicorn.run(create_app(prov, cors_origins=origins), host=args.host, port=args.port)
    return 0


def _s3():
    import boto3
    from core.providers.aws.config import REGION
    bucket = os.environ.get("AURALANE_BUCKET")
    if not bucket:
        sys.exit("needs AURALANE_BUCKET: pass --stack Auralane")
    return boto3.client("s3", region_name=REGION), bucket


def cmd_upload(args) -> int:
    """The edge agent: send one study to the cloud pipeline and, with --wait,
    print the result the ingest task writes."""
    import time
    from core.upload import RESULTS, new_batch, upload_study
    s3, bucket = _s3()
    target = Path(args.path)
    files = sorted(target.rglob("*.dcm")) if target.is_dir() else [target]
    if not files:
        sys.exit(f"no .dcm files under {target}")
    batch = new_batch()
    key = upload_study(s3, bucket, files, batch, "000", site_state=args.state)
    print(f"uploaded {len(files)} files; manifest s3://{bucket}/{key}")
    if not args.wait:
        return 0
    result = f"{RESULTS}{batch}/000.json"
    t0 = time.monotonic()
    while time.monotonic() - t0 < args.wait:
        try:
            r = json.loads(s3.get_object(Bucket=bucket, Key=result)["Body"].read())
            print(json.dumps(r, indent=1))
            return 0 if r["status"] == "SCORED" else 1
        except s3.exceptions.NoSuchKey:
            time.sleep(10)
            print(f"  waiting for the ingest task: {int(time.monotonic() - t0)} s", flush=True)
    sys.exit(f"no result after {args.wait} s; see the ingest task's logs")


def cmd_upload_corpus(args) -> int:
    """This machine's study corpus -> S3 corpus/, for the hosted simulated intake."""
    from core.intake import catalogue
    from core.upload import upload_corpus
    s3, bucket = _s3()
    print(json.dumps(upload_corpus(s3, bucket, catalogue())))
    return 0


def cmd_token(args) -> int:
    if getattr(args, "as_reader", None):
        # A development token for a named reader id (AURALANE_AUTH=dev testing).
        import time as _t

        import jwt
        from core.providers.local import DevAuth
        from core.providers.local.devauth import AUDIENCE, ISSUER
        key = DevAuth(key_file=DEV_KEY, password_file=DEV_PASSWORD_FILE)._key
        now = int(_t.time())
        groups = ["admin", "superadmin"] if args.user == "admin" else ["radiologist"]
        print(jwt.encode({"sub": f"dev-as-{args.as_reader}", "email": args.as_reader,
                          "groups": groups, "iss": ISSUER, "aud": AUDIENCE, "iat": now,
                          "exp": now + 3600 * 8}, key, algorithm="HS256"))
        return 0
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
    for sp in (i, s):
        sp.add_argument("--stack", default=None,
                        help="read the aws runtime's settings from this CloudFormation stack's outputs")
    t = sub.add_parser("token", help="a development bearer token (local runtime only)")
    t.add_argument("user", choices=["radiologist", "radiologist-1", "radiologist-2",
                                    "radiologist-3", "radiologist-4", "admin"])
    t.add_argument("--as", dest="as_reader", help="the token's reader id (AURALANE_AUTH=dev)")
    u = sub.add_parser("upload", help="send one study to the cloud pipeline (the edge's only step)")
    u.add_argument("path", help="a study directory or one .dcm file")
    u.add_argument("--state", default=None, help="the site's state for the chest regional prior")
    u.add_argument("--wait", type=int, default=0, help="seconds to wait for the result")
    c = sub.add_parser("upload-corpus", help="put this machine's study corpus in S3, once")
    for sp in (u, c):
        sp.add_argument("--stack", default=None, help="read settings from this CloudFormation stack")
    args = ap.parse_args(argv)
    if getattr(args, "stack", None):
        load_stack(args.stack)
    return {"ingest": cmd_ingest, "serve": cmd_serve, "token": cmd_token, "upload": cmd_upload,
            "upload-corpus": cmd_upload_corpus}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
