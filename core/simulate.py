"""Simulate ingest: studies from the staged pool, through the real pipeline.

The pool is written once by scripts/stage_pool.py, on the edge machine: the
local corpora, de-identified there by sim/edge/deid.py, then copied to
s3://<bucket>/pool/<type>/<study>/ (aws) or data/pool/<type>/<study>/ (local).
De-identification happens at that step and nowhere else; the pipeline checks
the marks on every instance and refuses a study without them.

A batch picks studies from the pool and, for each, runs core.pipeline.ingest:
the datastore import (HealthImaging, or Orthanc locally), the model (the chest
Lambda and the SageMaker async endpoints, or in-process locally), adapter,
regional prior, triage, evidence and the worklist row. This module orchestrates
only; no model runs in the API process on AWS. Studies are assigned to the
selected readers as each one finishes, so they appear in the worklist one by one.

The fixture runtime has no pipeline, so there the feature reports itself
unavailable and says why. It never invents a study.

NON-DIAGNOSTIC; DECISION SUPPORT ONLY.
"""
from __future__ import annotations

import datetime
import json
import random
import shutil
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

import pydicom

from core.assign import Dealer, coverage_gaps

ROOT = Path(__file__).resolve().parents[1]
LOCAL_POOL = ROOT / "data" / "pool"
REPORT = "deid_report.json"        # {SOPInstanceUID: text regions masked at the edge}

# Pool type -> (modality, model id, reading pool, cap per batch). The model id
# is passed to the pipeline explicitly, not chosen by modality.
# TODO: the Alzheimer T1 model ("alz") once its weights exist; MR then routes by
# content (four sequences to BraTS, T1 only to Alzheimer).
TYPES = {
    "chest": ("CR", "cxr-densenet-v1", "Chest", 10),
    "brain": ("MR", "brain-brats-monai-v0.5.4", "Neuro", 3),
    "ct": ("CT", "ct-ich-vit-v1", "Neuro", 3),
}
LABELS = {"chest": "Chest X-ray", "brain": "Brain MR (BraTS)", "ct": "Head CT"}

# Cost per study, from docs/AWS-COSTS.md (us-east-1 on-demand, read 2026-09-27
# and 2026-09-28). Each figure carries the assumption it rests on, shown in the panel.
COSTS = {
    "chest": {"per_study": 0.0005, "per_wake": 0.0,
              "basis": "chest Lambda at 3,008 MB, assuming 10 s billed per study "
                       "($0.000049 per second)"},
    "brain": {"per_study": 0.0, "per_wake": 0.23,
              "basis": "brain endpoint ml.m5.2xlarge at $0.461 per hour; one wake keeps an "
                       "instance up about 20 to 30 min (estimate, docs/AWS-COSTS.md), shared "
                       "by every brain study in the batch"},
    "ct": {"per_study": 0.0, "per_wake": 0.12,
           "basis": "CT endpoint ml.m5.xlarge at $0.23 per hour; one wake, about 20 to 30 "
                    "min (estimate), shared by every CT study in the batch"},
}
COST_NOTE = ("Upper end of each range. Not included: HealthImaging import and storage, S3 "
             "and DynamoDB requests, a few cents at this size. If an endpoint is already "
             "awake from an earlier batch, its wake costs nothing extra.")


def estimate(counts: dict[str, int], runtime: str) -> dict[str, Any]:
    """Estimated AWS cost of a batch, itemised, with the basis of each line."""
    if runtime != "aws":
        return {"total_usd": 0.0, "lines": [],
                "note": "Local runtime: Orthanc, DynamoDB Local and in-process models. No AWS charge."}
    lines = []
    for t, n in counts.items():
        if n <= 0 or t not in COSTS:
            continue
        c = COSTS[t]
        usd = n * c["per_study"] + (c["per_wake"] if n else 0)
        lines.append({"type": t, "label": LABELS[t], "count": n, "usd": round(usd, 4),
                      "basis": c["basis"]})
    return {"total_usd": round(sum(l["usd"] for l in lines), 4), "lines": lines,
            "note": COST_NOTE}


class LocalPool:
    """data/pool/<type>/<study>/*.dcm, written by stage_pool.py --local."""

    def __init__(self, root: Path = LOCAL_POOL):
        self.root = Path(root)
        self.where = self.root.as_posix().rstrip("/") + "/"

    def list(self, kind: str) -> list[str]:
        d = self.root / kind
        return sorted(p.name for p in d.iterdir() if p.is_dir()) if d.is_dir() else []

    def fetch(self, kind: str, study: str, dest: Path) -> tuple[list[Path], dict]:
        d = self.root / kind / study
        report = d / REPORT
        return (sorted(d.rglob("*.dcm")),
                json.loads(report.read_text()) if report.exists() else {})


class S3Pool:
    """s3://<bucket>/pool/<type>/<study>/, written by stage_pool.py."""

    def __init__(self, s3, bucket: str, prefix: str = "pool/"):
        self.s3, self.bucket, self.prefix = s3, bucket, prefix
        self.where = f"s3://{bucket}/{prefix}"

    def list(self, kind: str) -> list[str]:
        out = []
        for page in self.s3.get_paginator("list_objects_v2").paginate(
                Bucket=self.bucket, Prefix=f"{self.prefix}{kind}/", Delimiter="/"):
            out += [c["Prefix"].rstrip("/").rsplit("/", 1)[-1]
                    for c in page.get("CommonPrefixes", [])]
        return sorted(out)

    def fetch(self, kind: str, study: str, dest: Path) -> tuple[list[Path], dict]:
        keys = []
        for page in self.s3.get_paginator("list_objects_v2").paginate(
                Bucket=self.bucket, Prefix=f"{self.prefix}{kind}/{study}/"):
            keys += [o["Key"] for o in page.get("Contents", [])]

        def get(key: str) -> Path:
            local = dest / key.rsplit("/", 1)[-1]
            local.write_bytes(self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read())
            return local

        with ThreadPoolExecutor(16) as pool:
            paths = list(pool.map(get, keys))
        report = next((p for p in paths if p.name == REPORT), None)
        return (sorted(p for p in paths if p.suffix == ".dcm"),
                json.loads(report.read_text()) if report else {})


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="microseconds")


class Simulator:
    def __init__(self, pool, ingest_one: Callable[..., Any] | None, table, runtime: str,
                 on_study: Callable[[dict, dict | None, str], None] | None = None,
                 workers: int = 1, unavailable: str | None = None):
        """ingest_one(paths, edge_reports=, model_id=, run_id=) -> Verdict.
        on_study(row, reader, actor): called when a study is scored, to assign it."""
        self.pool, self.ingest_one, self.table = pool, ingest_one, table
        self.runtime, self.on_study, self.workers = runtime, on_study, workers
        self.unavailable = unavailable
        self._lock = threading.Lock()
        self._batches: dict[str, dict[str, Any]] = {}

    # -- read -----------------------------------------------------------------
    def catalogue(self) -> dict[str, int]:
        if self.unavailable or self.pool is None:
            return {}
        return {t: len(self.pool.list(t)) for t in TYPES}

    def info(self) -> dict[str, Any]:
        if self.unavailable:
            return {"available": False, "reason": self.unavailable, "runtime": self.runtime}
        try:
            cat = self.catalogue()
        except Exception as e:                 # e.g. no credentials for the bucket
            return {"available": False, "reason": f"cannot read the pool: {e}",
                    "runtime": self.runtime}
        return {"available": any(cat.values()),
                "reason": None if any(cat.values()) else
                f"the pool at {self.pool.where} is empty: run scripts/stage_pool.py",
                "runtime": self.runtime, "where": self.pool.where,
                "types": [{"type": t, "label": LABELS[t], "pool": TYPES[t][2],
                           "cap": TYPES[t][3], "staged": cat.get(t, 0)} for t in TYPES],
                "running": [b["batch"] for b in self._batches.values() if b["running"]]}

    def status(self, batch: str) -> dict[str, Any]:
        with self._lock:
            b = self._batches.get(batch)
            if b is None:
                raise KeyError(batch)
            return json.loads(json.dumps(b))

    def batches(self) -> list[dict[str, Any]]:
        with self._lock:
            return [json.loads(json.dumps(b)) for b in self._batches.values()]

    def in_flight(self) -> dict[str, dict]:
        """{study: item} for every study of every batch, for the pipeline view."""
        with self._lock:
            return {i["study"]: {**i, "batch": b["batch"]} for b in self._batches.values()
                    for i in b["items"] if i.get("study")}

    # -- write ----------------------------------------------------------------
    def plan(self, counts: dict[str, int], readers: list[dict]) -> list[str]:
        """Problems that stop a batch before anything is sent."""
        problems = []
        for t, n in counts.items():
            if t not in TYPES:
                problems.append(f"unknown study type {t!r}")
            elif n < 0 or n > TYPES[t][3]:
                problems.append(f"{LABELS[t]}: {n} is outside 0 to {TYPES[t][3]}")
        if not any(counts.values()):
            problems.append("choose at least one study")
        if readers:
            gaps = coverage_gaps({TYPES[t][2] for t, n in counts.items() if n and t in TYPES},
                                 readers)
            if gaps:
                problems.append("no selected reader reads the " + ", ".join(gaps) + " pool")
        return problems

    def start(self, counts: dict[str, int], readers: list[dict], actor: str,
              seed: int | None = None) -> dict[str, Any]:
        if self.unavailable:
            raise RuntimeError(self.unavailable)
        problems = self.plan(counts, readers)
        if problems:
            raise ValueError("; ".join(problems))
        rng = random.Random(seed)
        queued = {r["study"] for r in self.table.scan("worklist")}
        order = []
        for t, n in counts.items():
            if not n:
                continue
            staged = self.pool.list(t)
            if len(staged) < n:
                raise ValueError(f"{LABELS[t]}: {n} asked for, {len(staged)} staged")
            fresh = [s for s in staged if s not in queued]
            rng.shuffle(fresh)
            again = [s for s in staged if s in queued]
            rng.shuffle(again)
            order += [(t, s) for s in (fresh + again)[:n]]
        rng.shuffle(order)
        batch = uuid.uuid4().hex[:10]
        state = {"batch": batch, "by": actor, "started_at": _now(), "finished_at": None,
                 "running": True, "runtime": self.runtime,
                 "readers": [r["id"] for r in readers],
                 "estimate": estimate(counts, self.runtime),
                 "items": [{"type": t, "study": s, "modality": TYPES[t][0],
                            "model_id": TYPES[t][1], "run_id": uuid.uuid4().hex[:12],
                            "status": "queued", "lane": None, "assigned_to": None,
                            "error": None} for t, s in order]}
        with self._lock:
            self._batches[batch] = state
        dealer = Dealer(readers) if readers else None
        threading.Thread(target=self._run, args=(batch, dealer, actor), daemon=True).start()
        return self.status(batch)

    def _set(self, batch: str, i: int, **fields) -> None:
        with self._lock:
            self._batches[batch]["items"][i].update(fields)

    def _run(self, batch: str, dealer: Dealer | None, actor: str) -> None:
        items = self.status(batch)["items"]
        lock = threading.Lock()

        def one(i: int, item: dict) -> None:
            self._set(batch, i, status="receiving", started_at=_now())
            tmp = Path(tempfile.mkdtemp(prefix="auralane-sim-"))
            try:
                start = time.perf_counter()
                paths, reports = self.pool.fetch(item["type"], item["study"], tmp)
                self._audit(item, "receive", start, {
                    "run_id": item["run_id"], "batch": batch, "instances": len(paths),
                    "source": f"{self.pool.where}{item['type']}/{item['study']}/",
                    "service": "Amazon S3 (staged pool)" if self.runtime == "aws"
                               else "local staged pool"})
                if not paths:
                    raise FileNotFoundError(f"no DICOM under {item['type']}/{item['study']}")
                self._set(batch, i, status="running")
                v = self.ingest_one(paths, edge_reports=reports, model_id=item["model_id"],
                                    run_id=item["run_id"])
                reader = None
                row = self.table.get_item("worklist", {"study": item["study"]})
                if row is not None and self.on_study is not None:
                    if dealer is not None:
                        with lock:
                            reader = dealer.pick(TYPES[item["type"]][2], row["lane"])
                    self.on_study(row, reader, actor)
                self._set(batch, i, status="done" if v.status == "SCORED" else "failed",
                          lane=v.lane, error=v.error, finished_at=_now(),
                          assigned_to=reader["id"] if reader else None)
            except Exception as e:
                self._set(batch, i, status="failed", error=f"{type(e).__name__}: {e}",
                          finished_at=_now())
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

        with ThreadPoolExecutor(self.workers) as pool:
            list(pool.map(lambda a: one(*a), enumerate(items)))
        with self._lock:
            self._batches[batch].update(running=False, finished_at=_now())

    def _audit(self, item: dict, action: str, start: float, detail: dict) -> None:
        from core.types import AuditEvent
        self.table.append_audit(AuditEvent(
            actor="simulate", action=action, study=item["study"], at=_now(), outcome="ok",
            duration_ms=round((time.perf_counter() - start) * 1000, 3), detail=detail))


def study_uid(path: Path) -> str:
    return str(pydicom.dcmread(path, stop_before_pixels=True).StudyInstanceUID)
