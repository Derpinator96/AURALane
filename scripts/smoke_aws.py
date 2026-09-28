"""End-to-end smoke test on AWS: the definition of done.

    python scripts/smoke_aws.py --api https://auralane-api.onrender.com --user radiologist --password <pw>
    python scripts/smoke_aws.py --api local --user radiologist --password <pw>

The stack outputs are read from CloudFormation (stack Auralane), so nothing
needs exporting; your AWS credentials are used for ingest. --api local runs
the same API code in this process against AWS, before Render is switched over.
It checks the API's runtime and signs in first, so a wrong password costs nothing.

1. Ingests one chest, one brain MR and one head CT study through the real
   pipeline with the aws providers: de-identify here, import to HealthImaging,
   score on Lambda / SageMaker, write DynamoDB.
2. Signs in to the deployed API as a radiologist (Cognito) and reads the
   worklist, printing every study with its lane and marking the three ingested.
3. Fetches one frame through the URL the API hands the viewer, and checks
   whether HealthImaging's own presigned URL answers a browser origin with
   CORS headers (the answer decides AURALANE_FRAME_MODE; see docs/DEPLOY.md).

Needs the stack outputs and a scoped AWS key in the environment, as for
`python -m core.run ingest`. Makes AWS calls that cost money (docs/AWS-COSTS.md):
three imports, one Lambda call, two async jobs. Creates no AWS resources.
Exits 0 only if all three studies reach the deployed worklist.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULTS = {
    "chest": ROOT / "data" / "chest" / "studies",
    "brain": ROOT / "data" / "brain" / "dicom",
    "ct": ROOT / "data" / "ct" / "raw",
}


def _first_study(root: Path) -> Path:
    dirs = sorted(d for d in root.iterdir() if d.is_dir()) if root.is_dir() else []
    if not dirs:
        sys.exit(f"no study directory under {root}")
    return dirs[0]


_LOCAL = None     # a TestClient on the real API app, for --api local


def _load_stack(stack: str) -> None:
    """Fill every AURALANE_* variable not already set from the stack's outputs
    (each output's description is the variable name), so the only thing to type
    is the command."""
    import boto3
    os.environ.setdefault("AURALANE_RUNTIME", "aws")
    os.environ.setdefault("AWS_REGION", "us-east-1")
    cfn = boto3.client("cloudformation", region_name=os.environ["AWS_REGION"])
    for o in cfn.describe_stacks(StackName=stack)["Stacks"][0].get("Outputs", []):
        os.environ.setdefault(o["Description"], o["OutputValue"])


def _http(url: str, *, method="GET", body=None, token=None, origin=None):
    if _LOCAL is not None and not url.startswith("http"):
        headers = {**({"Authorization": f"Bearer {token}"} if token else {}),
                   **({"Origin": origin} if origin else {})}
        r = _LOCAL.request(method, url.removeprefix("local"), json=body, headers=headers)
        return r.status_code, r.headers, r.content
    req = urllib.request.Request(url, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if origin:
        req.add_header("Origin", origin)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def ingest_three(studies: dict[str, Path], state: str | None) -> dict[str, dict]:
    import core.run as run
    from core.pipeline import ingest
    from core.registry import Registry
    p = run.providers(for_ingest=True)
    regional = run.regional_setting(state)
    out = {}
    for kind, path in studies.items():
        files = sorted(path.rglob("*.dcm"))
        print(f"[{kind}] ingesting {len(files)} files from {path}", flush=True)
        t0 = time.perf_counter()
        v = ingest(files, blob=p["blob"], datastore=p["datastore"], table=p["table"],
                   inference=p["inference"], registry=Registry(), identity=run._identity(),
                   regional=regional)
        out[kind] = {"study": v.ref.study_uid if v.ref else None, "status": v.status,
                     "lane": v.lane, "error": v.error,
                     "seconds": round(time.perf_counter() - t0, 1)}
        print(f"[{kind}] {v.status} {v.lane} in {out[kind]['seconds']} s"
              + (f": {v.error}" if v.error else ""), flush=True)
    return out


def check_api(api: str, user: str, password: str, ingested: dict[str, dict],
              origin: str) -> bool:
    status, _, body = _http(f"{api}/api/auth/login", method="POST",
                            body={"username": user, "password": password})
    if status != 200:
        print(f"login failed: {status} {body[:200]!r}")
        return False
    token = json.loads(body)["token"]
    status, _, body = _http(f"{api}/api/worklist", token=token)
    if status != 200:
        print(f"worklist failed: {status} {body[:200]!r}")
        return False
    rows = json.loads(body)["studies"]
    wanted = {v["study"]: k for k, v in ingested.items() if v["study"]}
    print(f"\ndeployed worklist, {len(rows)} studies:")
    for r in rows:
        mark = f"  <- {wanted[r['study']]}" if r["study"] in wanted else ""
        print(f"  {r['lane']:<10} {(r.get('modality') or ''):<3} {r['study']}{mark}")
    found = {r["study"] for r in rows} & set(wanted)
    missing = [wanted[s] for s in wanted if s not in found]
    if missing:
        print(f"MISSING from the deployed worklist: {', '.join(missing)}")

    # One frame, through exactly the URL the viewer would use.
    chest = ingested.get("chest", {}).get("study")
    if chest:
        _, _, body = _http(f"{api}/api/studies/{chest}", token=token)
        detail = json.loads(body)
        if detail.get("series"):
            s = detail["series"][0]
            _, _, body = _http(f"{api}/api/studies/{chest}/series/{s['series_uid']}", token=token)
            inst = json.loads(body)["instances"][0]
            status, headers, data = _http(inst["frame_url"], origin=origin)
            print(f"\nframe via the viewer's URL: HTTP {status}, {len(data)} bytes, "
                  f"CORS allow-origin {headers.get('Access-Control-Allow-Origin')!r}")
    return not missing


def check_presigned(ingested: dict[str, dict], origin: str) -> None:
    """Whether HealthImaging's presigned DICOMweb URL could serve a browser:
    it must answer 200 and send Access-Control-Allow-Origin for our origin."""
    import core.run as run
    from core.types import StudyRef
    chest = ingested.get("chest", {}).get("study")
    if not chest:
        return
    p = run.providers()
    row = p["table"].get_item("worklist", {"study": chest})
    ref = StudyRef(chest, row["datastore_id"])
    meta = p["datastore"].get_metadata(ref)
    s = meta.series[0]
    url = p["datastore"].frame_url(ref, s.series_uid, s.instance_uids[0])
    status, headers, data = _http(url, origin=origin)
    cors = headers.get("Access-Control-Allow-Origin")
    print(f"presigned HealthImaging frame: HTTP {status}, {len(data)} bytes, "
          f"CORS allow-origin {cors!r}")
    print("  -> AURALANE_FRAME_MODE=presigned can work from the browser" if status == 200 and cors
          else "  -> set AURALANE_FRAME_MODE=proxy on the API")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=os.environ.get("AURALANE_API_URL", "").rstrip("/"),
                    help="the deployed API, e.g. https://auralane-api.onrender.com; or "
                         "'local' to run the same API code here against AWS")
    ap.add_argument("--stack", default="Auralane", help="CloudFormation stack to read outputs from")
    ap.add_argument("--user", default=os.environ.get("AURALANE_SMOKE_USER"))
    ap.add_argument("--password", default=os.environ.get("AURALANE_SMOKE_PASSWORD"))
    ap.add_argument("--origin", default="https://aura-lane.vercel.app",
                    help="the browser origin to test CORS for")
    ap.add_argument("--state", default=None, help="site state for the chest regional prior")
    for kind, root in DEFAULTS.items():
        ap.add_argument(f"--{kind}", type=Path, default=None,
                        help=f"a {kind} study directory (default: first under {root})")
    args = ap.parse_args()
    if not (args.api and args.user and args.password):
        sys.exit("need --api, --user and --password (or AURALANE_API_URL, "
                 "AURALANE_SMOKE_USER, AURALANE_SMOKE_PASSWORD)")
    _load_stack(args.stack)
    if os.environ["AURALANE_RUNTIME"] != "aws":
        sys.exit("AURALANE_RUNTIME is set to something other than aws in this shell")
    if args.api == "local":
        global _LOCAL
        import core.run as run
        from core.api import create_app
        from fastapi.testclient import TestClient
        _LOCAL = TestClient(create_app(run.providers()))
    # Sign in first: a wrong password or a missing user costs nothing this way.
    status, _, body = _http(f"{args.api}/api/health")
    runtime = json.loads(body).get("runtime") if status == 200 else None
    if runtime != "aws":
        sys.exit(f"{args.api} is serving the {runtime!r} runtime, not aws: finish "
                 f"docs/DEPLOY.md step 6, or use --api local")
    status, _, body = _http(f"{args.api}/api/auth/login", method="POST",
                            body={"username": args.user, "password": args.password})
    if status != 200:
        sys.exit(f"sign-in as {args.user} failed ({status}): {body[:200]!r}. "
                 f"Check the Cognito user exists (docs/DEPLOY.md step 4).")
    studies = {k: getattr(args, k) or _first_study(root) for k, root in DEFAULTS.items()}
    ingested = ingest_three(studies, args.state)
    ok = check_api(args.api, args.user, args.password, ingested, args.origin)
    check_presigned(ingested, args.origin)
    print("\nSMOKE PASSED: all three studies are on the deployed worklist" if ok
          else "\nSMOKE FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
