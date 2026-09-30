"""Simulated intake: real studies from this machine's corpus, ingested through
the full pipeline in a mixed order, as if they were arriving from the scanners.

Nothing here is synthetic apart from the arrival order. Every study is
de-identified, stored, scored and queued by core.pipeline.ingest against the
configured runtime (Orthanc and DynamoDB Local, or HealthImaging, Lambda,
SageMaker and DynamoDB), so every lane on the worklist is a real result.

It runs where the studies are: the machine that serves the API with the
corpus on disk. A host with no corpus (the Render API) reports it unavailable
and why; it never invents a study.

One run at a time. Progress is read by polling status().
"""
from __future__ import annotations

import datetime
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
CORPUS = {
    "CR": ROOT / "data" / "chest" / "studies",
    "MR": ROOT / "data" / "brain" / "dicom",
    "CT": ROOT / "data" / "ct" / "raw",
}


# More studies, built beside the tested corpus: data/chest/studies is exactly the 40 the privacy gate
# counts, so further chest studies go in data/chest/extra:
#   python sim/generator/make_dicom.py --src images --out data/chest/extra --count 60 --seed 2026 --burn-in 0.1
EXTRA = {"CR": [ROOT / "data" / "chest" / "extra"]}


def _study_dirs(root: Path) -> list[Path]:
    return sorted(d for d in root.iterdir() if d.is_dir() and any(d.rglob("*.dcm"))) if root.is_dir() else []


def catalogue(corpus: dict[str, Path] | None = None) -> dict[str, list[Path]]:
    """Study directories on this machine, by modality: the corpus, and the extra folders beside it.
    A corpus passed in (a test's) is taken as it is."""
    if corpus is not None:
        return {m: _study_dirs(root) for m, root in corpus.items()}
    return {m: _study_dirs(root) + [d for e in EXTRA.get(m, []) for d in _study_dirs(e)]
            for m, root in CORPUS.items()}


def pick(studies: dict[str, list[Path]], count: int, rng: random.Random) -> list[tuple[str, Path]]:
    """Every MR and CT study available (they are few), chest to make up the
    count, shuffled into one arrival order."""
    chosen = [(m, p) for m in ("MR", "CT") for p in studies.get(m, [])][:count]
    chest = list(studies.get("CR", []))
    rng.shuffle(chest)
    chosen += [("CR", p) for p in chest[:max(0, count - len(chosen))]]
    rng.shuffle(chosen)
    return chosen


class IntakeSimulator:
    def __init__(self, ingest_one: Callable[[Path], Any], studies: dict[str, list[Path]],
                 workers: int = 1, unavailable: str | None = None):
        """ingest_one(study_dir) -> Verdict. workers: studies in flight at once
        (1 for the local runtime, whose models share one process)."""
        self.ingest_one, self.studies, self.workers = ingest_one, studies, workers
        self.unavailable = unavailable or (None if any(studies.values())
                                           else "no study corpus on this host")
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {"running": False, "runs": 0}

    def status(self) -> dict[str, Any]:
        with self._lock:
            s = {k: (list(v) if isinstance(v, list) else v) for k, v in self._state.items()}
        s["available"] = self.unavailable is None
        s["reason"] = self.unavailable
        s["catalogue"] = {m: len(v) for m, v in self.studies.items()}
        s["workers"] = self.workers
        return s

    def start(self, count: int, actor: str, seed: int | None = None) -> dict[str, Any]:
        if self.unavailable:
            raise RuntimeError(self.unavailable)
        with self._lock:
            if self._state["running"]:
                raise RuntimeError("a simulated intake is already running")
            order = pick(self.studies, count, random.Random(seed))
            self._state = {
                "running": True, "runs": self._state["runs"] + 1, "by": actor,
                "started_at": _now(), "finished_at": None, "total": len(order),
                "done": 0, "failed": 0,
                "items": [{"modality": m, "source": p.name, "status": "queued"} for m, p in order],
            }
        threading.Thread(target=self._run, args=(order,), daemon=True).start()
        return self.status()

    def _run(self, order: list[tuple[str, Path]]) -> None:
        def one(i: int, path: Path) -> None:
            self._set(i, status="ingesting")
            t0 = time.perf_counter()
            try:
                v = self.ingest_one(path)
                self._set(i, status=v.status, lane=v.lane, study=v.ref.study_uid if v.ref else None,
                          error=v.error, seconds=round(time.perf_counter() - t0, 1))
            except Exception as e:                       # a crash is a failed item, not a dead run
                self._set(i, status="FAILED", lane="FAILED", error=f"{type(e).__name__}: {e}",
                          seconds=round(time.perf_counter() - t0, 1))

        with ThreadPoolExecutor(self.workers) as pool:
            list(pool.map(lambda ip: one(*ip), [(i, p) for i, (_, p) in enumerate(order)]))
        with self._lock:
            self._state.update(running=False, finished_at=_now())

    def _set(self, i: int, **fields) -> None:
        with self._lock:
            item = self._state["items"][i]
            item.update(fields)
            if fields.get("status") == "SCORED":
                self._state["done"] += 1
            elif fields.get("status") == "FAILED":
                self._state["failed"] += 1


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


class CloudIntake:
    """The same button on the AWS runtime: arrivals are started in S3 and run
    in AWS. start() copies corpus studies into upload/ server-side (nothing is
    downloaded; this works from the hosted API), and each manifest starts an
    ingest task (core/cloud_ingest.py). Progress is read from the results the
    tasks write to intake/<batch>/, so it survives an API restart.

    Items are shown by modality and arrival number, never by a source name:
    corpus folders are named after original study UIDs.
    """

    def __init__(self, s3, bucket: str, site_state: str | None = None):
        from core.upload import corpus_catalogue
        self.s3, self.bucket, self.site_state = s3, bucket, site_state
        try:
            self.studies = corpus_catalogue(s3, bucket)
            self.unavailable = None if any(self.studies.values()) else (
                "no corpus in S3 yet: run python -m core.run upload-corpus --stack Auralane")
        except Exception as e:
            self.studies, self.unavailable = {}, f"cannot list the S3 corpus: {e}"
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {"running": False, "runs": 0}

    def status(self) -> dict[str, Any]:
        import json
        with self._lock:
            state = self._state
            for it in state.get("items", []):
                if it["status"] in ("SCORED", "FAILED") or "result" not in it:
                    continue
                try:
                    r = json.loads(self.s3.get_object(Bucket=self.bucket,
                                                      Key=it["result"])["Body"].read())
                except self.s3.exceptions.NoSuchKey:
                    continue
                it.update(status=r["status"], lane=r.get("lane"), study=r.get("study"),
                          error=r.get("error"), seconds=r.get("seconds"))
                state["done" if r["status"] == "SCORED" else "failed"] += 1
            if state.get("items") and state["running"] and not state.get("uploading") and all(
                    it["status"] in ("SCORED", "FAILED") for it in state["items"]):
                state.update(running=False, finished_at=_now())
            s = {k: ([dict(i) for i in v] if k == "items" else v) for k, v in state.items()}
        s.update(available=self.unavailable is None, reason=self.unavailable,
                 catalogue={m: len(v) for m, v in self.studies.items()}, workers="in AWS")
        return s

    def start(self, count: int, actor: str, seed: int | None = None) -> dict[str, Any]:
        from core.upload import RESULTS, copy_study, new_batch
        if self.unavailable:
            raise RuntimeError(self.unavailable)
        with self._lock:
            if self._state["running"]:
                raise RuntimeError("a simulated intake is already running")
            batch = new_batch()
            order = pick(self.studies, count, random.Random(seed))
            self._state = {
                "running": True, "uploading": True, "runs": self._state["runs"] + 1,
                "by": actor, "batch": batch, "started_at": _now(), "finished_at": None,
                "total": len(order), "done": 0, "failed": 0,
                "items": [{"modality": m, "source": f"arrival {i + 1}", "status": "queued",
                           "result": f"{RESULTS}{batch}/{i:03d}.json"}
                          for i, (m, _) in enumerate(order)]}

        def upload(i: int, modality: str, prefix: str) -> None:
            try:
                copy_study(self.s3, self.bucket, prefix, batch, f"{i:03d}",
                           self.site_state, modality)
                self._set(i, status="in AWS")
            except Exception as e:
                self._set(i, status="FAILED", lane="FAILED", error=f"{type(e).__name__}: {e}")
                with self._lock:
                    self._state["failed"] += 1

        def run() -> None:
            with ThreadPoolExecutor(4) as pool:
                list(pool.map(lambda x: upload(*x), [(i, m, p) for i, (m, p) in enumerate(order)]))
            with self._lock:
                self._state["uploading"] = False

        threading.Thread(target=run, daemon=True).start()
        return self.status()

    def _set(self, i: int, **fields) -> None:
        with self._lock:
            self._state["items"][i].update(fields)
