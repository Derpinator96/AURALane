"""Time the API the way the client uses it, and print a Markdown table.

    python scripts/bench_api.py --base https://auralane-api.onrender.com \\
        --user <name> --password-env AURALANE_BENCH_PASSWORD --admin-user <name>
    python scripts/bench_api.py --base http://127.0.0.1:8102 --token <token> --admin-token <token>

Sign-in is either --user with the password read from an environment variable
(never a command-line argument) or a ready --token. The admin row needs an
admin sign-in (--admin-user or --admin-token) and is skipped without one.

Every request is timed end to end. When the response carries a Server-Timing
header the server's own split (total, dynamodb, healthimaging, s3, auth) is
shown next to it. Rows, each the median of --repeat runs (default 5):

    health              GET /api/health
    worklist            GET /api/worklist
    study open          GET /api/studies/<chest>
    series metadata     GET /api/studies/<chest>/series/<uid>
    chest frames x10    the first 10 frame URLs, six at a time (as the viewer)
    brain frames x10    the same for a brain MR series, when the account has one
    admin pipeline      GET /api/admin/pipeline

Frames are fetched from whatever URL the API hands out, so the run also shows
whether pixels go through the API (a /api/frames URL) or straight to the
datastore. --accept htj2k asks the datastore for the stored HTJ2K bytes, as the
client does; --accept default sends what Cornerstone sent before that change
(uncompressed frames).

NON-DIAGNOSTIC; DECISION SUPPORT ONLY.
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

ACCEPT = {
    "default": 'multipart/related; type="application/octet-stream"; transfer-syntax=*',
    "htj2k": 'multipart/related; type="image/jphc"; transfer-syntax=1.2.840.10008.1.2.4.202',
}


def parse_timing(h: str | None) -> dict[str, float]:
    out = {}
    for part in (h or "").split(","):
        name, _, rest = part.strip().partition(";")
        for kv in rest.split(";"):
            k, _, v = kv.strip().partition("=")
            if k == "dur" and name:
                try:
                    out[name] = float(v)
                except ValueError:
                    pass
    return out


class Bench:
    def __init__(self, base: str, timeout: float = 120.0):
        self.base = base.rstrip("/")
        self.http = httpx.Client(timeout=timeout, follow_redirects=True)

    def login(self, user: str, password: str) -> str:
        r = self.http.post(f"{self.base}/api/auth/login", json={"username": user, "password": password})
        r.raise_for_status()
        return r.json()["token"]

    def get(self, path: str, token: str | None = None, headers: dict | None = None):
        h = dict(headers or {})
        if token:
            h["Authorization"] = f"Bearer {token}"
        url = path if path.startswith("http") else f"{self.base}{path}"
        t = time.perf_counter()
        r = self.http.get(url, headers=h)
        ms = (time.perf_counter() - t) * 1000
        return r, ms


def median(xs):
    return statistics.median(xs) if xs else float("nan")


def timed(bench: Bench, path: str, token: str | None, repeat: int):
    """-> (median ms, last Server-Timing split, last response)."""
    runs, timing, resp = [], {}, None
    for _ in range(repeat):
        r, ms = bench.get(path, token)
        r.raise_for_status()
        runs.append(ms)
        timing, resp = parse_timing(r.headers.get("server-timing")), r
    return median(runs), timing, resp


def frames(bench: Bench, urls: list[str], accept: str, token: str | None, workers: int = 6):
    """Fetch every URL, six at a time. -> (wall ms, median per-frame ms, bytes, via API?)."""
    def one(u):
        h = {"Accept": accept} if "/api/frames/" not in u else {}
        r, ms = bench.get(u, None, h)
        r.raise_for_status()
        return ms, len(r.content)

    t = time.perf_counter()
    with ThreadPoolExecutor(workers) as pool:
        res = list(pool.map(one, urls))
    wall = (time.perf_counter() - t) * 1000
    return wall, median([m for m, _ in res]), sum(b for _, b in res), any("/api/frames/" in u for u in urls)


def split(t: dict[str, float]) -> str:
    keep = [f"{k} {t[k]:.0f}" for k in ("total", "dynamodb", "healthimaging", "s3", "auth") if k in t]
    return ", ".join(keep) if keep else "n/a"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True)
    ap.add_argument("--user")
    ap.add_argument("--password-env", default="AURALANE_BENCH_PASSWORD")
    ap.add_argument("--token")
    ap.add_argument("--admin-user")
    ap.add_argument("--admin-password-env", default="AURALANE_BENCH_ADMIN_PASSWORD")
    ap.add_argument("--admin-token")
    ap.add_argument("--repeat", type=int, default=5)
    ap.add_argument("--accept", choices=sorted(ACCEPT), default="htj2k")
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    b = Bench(args.base)
    token = args.token
    if not token:
        if not args.user or not os.environ.get(args.password_env):
            sys.exit(f"give --token, or --user and the password in ${args.password_env}")
        token = b.login(args.user, os.environ[args.password_env])
    admin = args.admin_token
    if not admin and args.admin_user and os.environ.get(args.admin_password_env):
        admin = b.login(args.admin_user, os.environ[args.admin_password_env])

    rows = []

    def add(name, ms, extra=""):
        rows.append((name, ms, extra))

    ms, t, _ = timed(b, "/api/health", None, args.repeat)
    add("health", ms, split(t))
    ms, t, r = timed(b, "/api/worklist", token, args.repeat)
    studies = r.json()["studies"]
    add(f"worklist ({len(studies)} studies)", ms, split(t))

    def open_and_series(modality: str):
        pick = next((s for s in studies if s["modality"] == modality and s["lane"] != "FAILED"), None)
        if not pick:
            return None
        ms1, t1, r1 = timed(b, f"/api/studies/{pick['study']}", token, args.repeat)
        detail = r1.json()
        series = max(detail["series"], key=lambda s: s.get("instance_count", 0))
        ms2, t2, r2 = timed(b, f"/api/studies/{pick['study']}/series/{series['series_uid']}", token, args.repeat)
        return pick, series, (ms1, t1), (ms2, t2), r2.json()["instances"]

    chest = open_and_series("CR")
    if chest:
        pick, series, (ms1, t1), (ms2, t2), inst = chest
        add("study open (chest)", ms1, split(t1))
        add("series metadata (chest)", ms2, split(t2))
        wall, per, nbytes, proxied = frames(b, [i["frame_url"] for i in inst[:10]], ACCEPT[args.accept], token)
        add(f"chest frames x{min(10, len(inst))}", wall,
            f"{per:.0f} ms per frame, {nbytes / 1e6:.2f} MB, {'via the API' if proxied else 'direct from the datastore'}")
    brain = open_and_series("MR")
    if brain:
        pick, series, (ms1, t1), (ms2, t2), inst = brain
        add("study open (brain MR)", ms1, split(t1))
        add(f"series metadata (brain MR, {len(inst)} instances)", ms2, split(t2))
        wall, per, nbytes, proxied = frames(b, [i["frame_url"] for i in inst[:10]], ACCEPT[args.accept], token)
        add("brain frames x10", wall,
            f"{per:.0f} ms per frame, {nbytes / 1e6:.2f} MB, {'via the API' if proxied else 'direct from the datastore'}")
    if admin:
        ms, t, _ = timed(b, "/api/admin/pipeline", admin, args.repeat)
        add("admin pipeline", ms, split(t))

    print(f"\n### {args.label or args.base}  (median of {args.repeat}; frames: {args.accept} Accept)\n")
    print("| request | ms | detail |\n|---|---:|---|")
    for name, ms, extra in rows:
        print(f"| {name} | {ms:.0f} | {extra} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
