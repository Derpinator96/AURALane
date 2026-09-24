"""Preflight for the AURALane PoC. Re-run it after every setup step.

    python scripts/doctor.py

One line per check. A failure prints the exact fix underneath it. Exits 1 if
any check FAILs; WARN lines are advice and never change the exit code. Steps
only a human can do are explained in docs/MANUAL-STEPS.md.
"""
import concurrent.futures
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "requirements.txt"
NIH_DIR = ROOT / "images"
BRATS_DIR = ROOT / "data" / "brain" / "raw"
CHEST_MANIFEST = ROOT / "data" / "chest" / "studies" / "manifest.json"
BRAIN_MANIFEST = ROOT / "data" / "brain" / "dicom" / "manifest.json"
BRAIN_MODEL = ROOT / "_external" / "brainmri" / "brats_mri_segmentation" / "models" / "model.ts"
# 127.0.0.1 rather than localhost: on Windows, localhost tries ::1 first and every
# refused loopback connection costs ~2 s of SYN retries.
ORTHANC_QIDO = "http://127.0.0.1:8042/dicom-web/studies"
DYNAMODB_URL = "http://127.0.0.1:8001"   # 8000 is the round-2 demo
AWS_REGION = "us-east-1"            # HealthImaging and the Bedrock models live here
TESSERACT_DIRS = [r"C:\Program Files\Tesseract-OCR",
                  r"C:\Program Files (x86)\Tesseract-OCR"]
MANUAL = "docs/MANUAL-STEPS.md"
COMPOSE_UP = "docker compose -f docker-compose.local.yml up -d"
CPU_TORCH = "pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu"

# pip name -> module name, only where they differ. A tuple means "any of these".
IMPORT_NAME = {
    "pillow": "PIL",
    "scikit-image": "skimage",
    "pylibjpeg-libjpeg": "libjpeg",
    "pylibjpeg-openjpeg": "openjpeg",
    "python-gdcm": "gdcm",
    "grad-cam": "pytorch_grad_cam",
    "python-multipart": ("python_multipart", "multipart"),
}

BRATS_FILE = re.compile(r"_(t1|t1ce|t2|flair|seg)\.nii(\.gz)?$", re.IGNORECASE)
BRATS_PARTS = {"t1", "t1ce", "t2", "flair", "seg"}

OK, WARN, FAIL = "ok", "WARN", "FAIL"

# localhost checks must never go through a system proxy
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


# -- helpers ----------------------------------------------------------------

def run(cmd, timeout=10):
    """-> (returncode, text). returncode is None if the command could not run."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                           timeout=timeout)
    except FileNotFoundError:
        return None, "not found"
    except subprocess.TimeoutExpired:
        return None, f"timed out after {timeout}s"
    return p.returncode, (p.stdout.strip() or p.stderr.strip())


def http(url, method="GET", headers=None, body=None, timeout=3):
    """-> (status, headers-lowercased, text). status is None if unreachable."""
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with _opener.open(req, timeout=timeout) as r:
            return (r.status, {k.lower(): v for k, v in r.headers.items()},
                    r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return (e.code, {k.lower(): v for k, v in e.headers.items()},
                e.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError) as e:
        return None, {}, str(getattr(e, "reason", e))


def port_open(port, timeout=0.5):
    """Fast pre-check. A listening loopback port accepts in well under a millisecond,
    so a short timeout cannot misreport a live service - it only saves the ~2 s
    Windows spends retrying a refused one."""
    try:
        socket.create_connection(("127.0.0.1", port), timeout=timeout).close()
        return True
    except OSError:
        return False


def importable(module):
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


# -- checks: each returns (status, name, detail, fix) -------------------------

def check_python():
    v = ".".join(map(str, sys.version_info[:3]))
    if sys.version_info < (3, 11):
        return FAIL, "python", f"{v}, need >= 3.11", "winget install Python.Python.3.12"
    return OK, "python", v, None


def check_venv():
    if sys.prefix != sys.base_prefix:
        try:
            where = os.path.relpath(sys.prefix, ROOT)
        except ValueError:
            where = sys.prefix
        return OK, "virtualenv", where, None
    return (WARN, "virtualenv", "not active - package results are for the system Python",
            r".venv\Scripts\activate")


def check_node():
    fix = "winget install OpenJS.NodeJS.LTS, then open a new terminal"
    exe = shutil.which("node")
    if not exe:
        return FAIL, "node", "not found", fix
    _, out = run([exe, "--version"])
    m = re.match(r"v(\d+)", out)
    if not m:
        return FAIL, "node", f"`node --version` said: {out[:60]}", fix
    if int(m.group(1)) < 20:
        return FAIL, "node", f"{out}, need >= 20", fix
    return OK, "node", out, None


def check_docker():
    exe = shutil.which("docker")
    if not exe:
        return FAIL, "docker", "not installed", f"Docker Desktop - see {MANUAL}"
    rc, out = run([exe, "info", "--format", "{{.ServerVersion}}"], timeout=15)
    if rc != 0:
        return (FAIL, "docker", "installed, but the daemon is not reachable",
                "start Docker Desktop and wait for 'Engine running'")
    return OK, "docker", f"engine {out}", None


def check_tesseract():
    exe = shutil.which("tesseract")
    if exe:
        _, out = run([exe, "--version"])
        return OK, "tesseract", (out.splitlines() or ["unknown version"])[0], None
    for d in TESSERACT_DIRS:
        if os.path.exists(os.path.join(d, "tesseract.exe")):
            return (FAIL, "tesseract", f"installed in {d} but not on PATH",
                    f"add that folder to your user PATH ({MANUAL}), then open a new terminal")
    return (FAIL, "tesseract", "not installed",
            f"winget install UB-Mannheim.TesseractOCR, then add it to PATH ({MANUAL})")


def check_aws():
    exe = shutil.which("aws")
    if not exe:
        return (FAIL, "aws", "CLI not installed",
                "winget install Amazon.AWSCLI, then open a new terminal")
    rc, out = run([exe, "sts", "get-caller-identity", "--output", "json"], timeout=20)
    if rc != 0:
        why = (out.splitlines() or ["no output"])[0][:70]
        return FAIL, "aws", f"credentials do not resolve: {why}", f"aws configure  ({MANUAL})"
    try:
        arn = json.loads(out).get("Arn", "?")
    except ValueError:
        arn = "?"
    env = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    region = env or run([exe, "configure", "get", "region"])[1]
    if region != AWS_REGION:
        fix = (f"set AWS_REGION / AWS_DEFAULT_REGION to {AWS_REGION}, or unset them"
               if env else f"aws configure set region {AWS_REGION}")
        return FAIL, "aws", f"{arn}, but region is {region or 'unset'} - need {AWS_REGION}", fix
    return OK, "aws", f"{arn} ({region})", None


def check_packages():
    if not REQUIREMENTS.exists():
        return FAIL, "packages", "requirements.txt is missing", "git checkout -- requirements.txt"
    names = []
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            names.append(re.split(r"[\[<>=!~;\s]", line, maxsplit=1)[0].lower())
    missing = []
    for name in names:
        mods = IMPORT_NAME.get(name, name.replace("-", "_"))
        if not any(importable(m) for m in ((mods,) if isinstance(mods, str) else mods)):
            missing.append(name)
    total = len(names)
    if not missing:
        return OK, "packages", f"{total}/{total} importable", None
    fix = [r"activate .venv first (.venv\Scripts\activate), then:"]
    if {"torch", "torchvision"} & set(missing):
        fix.append(CPU_TORCH)
    fix.append("pip install -r requirements.txt")
    return (FAIL, "packages",
            f"{total - len(missing)}/{total} importable - missing {', '.join(missing)}", fix)


def check_orthanc():
    if not port_open(8042):
        return FAIL, "orthanc", "not reachable on :8042", COMPOSE_UP
    code, _, body = http(ORTHANC_QIDO, headers={"Accept": "application/dicom+json"})
    if code is None:
        return FAIL, "orthanc", "not reachable on :8042", COMPOSE_UP
    if code == 401:
        return (FAIL, "orthanc", "up, but authentication is on",
                "turn authentication off in docker-compose.local.yml (local dev only)")
    if code == 404:
        return (FAIL, "orthanc", "up, but the DICOMweb plugin is off (404 on /dicom-web)",
                "enable DICOMweb in docker-compose.local.yml")
    if code == 204:
        return OK, "orthanc", "DICOMweb up, 0 studies", None
    if code != 200 or not body.lstrip().startswith("["):
        return (FAIL, "orthanc", f"HTTP {code}, not a DICOMweb answer - something else on :8042?",
                "free port 8042, then " + COMPOSE_UP)
    try:
        n = len(json.loads(body))
    except ValueError:
        n = "?"
    return OK, "orthanc", f"DICOMweb up, {n} studies", None


def check_dynamodb():
    # A ListTables call. DynamoDB Local does not validate signatures, and any
    # AWS JSON-protocol answer - even an error - proves it is DynamoDB on the port.
    headers = {
        "Content-Type": "application/x-amz-json-1.0",
        "X-Amz-Target": "DynamoDB_20120810.ListTables",
        "X-Amz-Date": "20260101T000000Z",
        "Authorization": ("AWS4-HMAC-SHA256 Credential=local/20260101/us-east-1/dynamodb/"
                          "aws4_request, SignedHeaders=host;x-amz-date, Signature=0"),
    }
    if not port_open(8001):
        return (FAIL, "dynamodb", "not reachable on :8001",
                COMPOSE_UP + "  (just started? it needs about 5 s)")
    code, hdrs, body = http(DYNAMODB_URL, method="POST", headers=headers, body=b"{}")
    if code is None:
        return (FAIL, "dynamodb", "not reachable on :8001",
                COMPOSE_UP + "  (just started? it needs about 5 s)")
    try:
        data = json.loads(body)
    except ValueError:
        data = {}
    if isinstance(data, dict) and "TableNames" in data:
        return OK, "dynamodb", f"local, {len(data['TableNames'])} tables", None
    if isinstance(data, dict) and "__type" in data:
        return OK, "dynamodb", "reachable (answered the probe with an AWS error)", None
    server = hdrs.get("server", "unknown")
    return (FAIL, "dynamodb", f":8001 is answered by something else (server: {server})",
            "stop whatever holds :8001")


def check_nih():
    n = sum(1 for _ in NIH_DIR.glob("*.png")) if NIH_DIR.is_dir() else 0
    if not n:
        return (FAIL, "nih pngs", "none in images/",
                f"NIH ChestX-ray14 sample into images/ ({MANUAL})")
    return OK, "nih pngs", f"{n} in images/", None


def check_brats():
    fix = f"put cases in data/brain/raw/<case>/  ({MANUAL})"
    if not BRATS_DIR.is_dir():
        return FAIL, "brats", "data/brain/raw/ does not exist", fix
    cases = {}
    for f in BRATS_DIR.rglob("*.nii*"):
        m = BRATS_FILE.search(f.name)
        if m:
            cases.setdefault(f.parent, set()).add(m.group(1).lower())
    complete = [c for c, parts in cases.items() if BRATS_PARTS <= parts]
    if complete:
        return OK, "brats", f"{len(complete)} complete cases in data/brain/raw/", None
    if cases:
        return (FAIL, "brats",
                f"{len(cases)} folders, none with all of t1/t1ce/t2/flair/seg", fix)
    return FAIL, "brats", "no BraTS NIfTI files in data/brain/raw/", fix


def _manifest(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def check_chest_dicom():
    m = _manifest(CHEST_MANIFEST)
    if m is None:
        return (FAIL, "chest dicom", "no data/chest/studies/manifest.json",
                "python data/chest/make_chest_corpus.py")
    burned = sum(bool(e.get("burned_in")) for e in m)
    return OK, "chest dicom", f"{len({e['study_uid'] for e in m})} studies, {burned} burned-in", None


def check_brain_dicom():
    m = _manifest(BRAIN_MANIFEST)
    if m is None:
        return (FAIL, "brain dicom", "no data/brain/dicom/manifest.json",
                "python data/brain/nifti_to_dicom.py")
    studies = len({e["study_uid"] for e in m})
    series = len({e["series_uid"] for e in m})
    return OK, "brain dicom", f"{studies} studies, {series} series, {len(m)} instances", None


def check_brain_model():
    if not BRAIN_MODEL.is_file():
        return (FAIL, "brain model", "_external/brainmri/.../models/model.ts missing",
                "git clone https://github.com/shauryajain111/brainmri.git _external/brainmri")
    return OK, "brain model", f"model.ts {BRAIN_MODEL.stat().st_size / 1e6:.1f} MB", None


CHECKS = [check_python, check_venv, check_node, check_docker, check_tesseract, check_aws,
          check_packages, check_orthanc, check_dynamodb, check_nih, check_chest_dicom,
          check_brats, check_brain_dicom, check_brain_model]


# -- output -----------------------------------------------------------------

def _safe(check):
    try:
        return check()
    except Exception as e:                       # a doctor must never crash
        name = check.__name__.replace("check_", "")
        return FAIL, name, f"check itself crashed: {type(e).__name__}: {e}", None


def main():
    sys.stdout.reconfigure(errors="replace")     # cp1252 consoles cannot print everything
    colour = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    if colour and os.name == "nt":
        os.system("")                            # switches the Windows console to ANSI mode
    paint = {OK: "\033[32m", WARN: "\033[33m", FAIL: "\033[31m"} if colour else {}
    reset = "\033[0m" if colour else ""

    with concurrent.futures.ThreadPoolExecutor(len(CHECKS)) as pool:
        results = list(pool.map(_safe, CHECKS))

    print(f"AURALane doctor  {ROOT}")
    for status, name, detail, fix in results:
        print(f"  {paint.get(status, '')}[{status:^4}]{reset} {name:<11} {detail}")
        if status != OK and fix:
            for line in ([fix] if isinstance(fix, str) else fix):
                print(f"         -> {line}")

    failing = sum(1 for r in results if r[0] == FAIL)
    if failing:
        print(f"{paint.get(FAIL, '')}{failing} failing{reset}. Human-only steps: {MANUAL}")
    else:
        print(f"{paint.get(OK, '')}all green{reset}")
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())
