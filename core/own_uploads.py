"""Upload your own studies: files from the browser, through the real pipeline.

A reader opens an upload, sends its files one request each (raw bodies, so the API needs no
multipart library and a file name, which can carry a patient's name, never reaches it), then
submits. The API sorts what arrived into studies and runs each one the way a study from the
pool or an edge agent runs:

    DICOM files       one study per StudyInstanceUID. CR, MR (four sequences) and CT, the modalities
                      a model is registered for.
    PNG or JPEG       a chest X-ray image, wrapped in a Computed Radiography DICOM object with a
                      generated synthetic identity (sim/generator/make_dicom.py) and taken as a
                      frontal (PA) view. One study per image.

Nothing here de-identifies. core.pipeline.ingest does, before the datastore sees anything
(locally, in this process; on AWS, in the ingest task, core/cloud_ingest.py). The API holds the
raw files in a temporary folder only until they are handed on, and deletes each as its study
finishes. On AWS this process holds no pixels beyond that and runs no model: the files go to S3
upload/ and the ingest task takes them from there.

Each study lands on the uploading reader's own worklist, in the reading pool its modality
belongs to; a reader who does not read that pool is told before anything is sent. File names are
never stored or audited.

NON-DIAGNOSTIC; DECISION SUPPORT ONLY.
"""
from __future__ import annotations

import datetime
import json
import random
import secrets
import shutil
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pydicom

from core.simulate import LABELS, TYPES

SPOOL = Path(tempfile.gettempdir()) / "auralane-uploads"
MAX_FILES = 1000               # a 155-slice, four-sequence brain MR is 620
MAX_FILE_MB = 64
MAX_TOTAL_MB = 400
MAX_STUDIES = 20
OPEN_PER_READER = 3
KEEP_S = 3600                  # an upload nobody submitted, and a finished one, are forgotten after this

BY_MODALITY = {modality: kind for kind, (modality, *_rest) in TYPES.items()}
ACCEPTS = ("DICOM files of one or more studies: chest X-ray (CR), brain MR with its four sequences, "
           "or head CT",
           "PNG or JPEG chest X-ray images, taken as frontal (PA) views")
PNG, JPEG = b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff"


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def classify(paths: list[Path]) -> tuple[list[dict], int, list[str]]:
    """Sort the received files into studies. -> (studies, files skipped, problems).

    A study is {kind: "dicom" | "image", type, modality, files}. A problem stops the whole upload
    before anything is sent, and never names a file or an identifier."""
    by_study: dict[str, dict[str, list[Path]]] = {}
    images: list[Path] = []
    skipped = 0
    for path in paths:
        with path.open("rb") as f:
            head = f.read(8)
        if head.startswith(PNG) or head.startswith(JPEG):
            images.append(path)
            continue
        try:
            ds = pydicom.dcmread(path, stop_before_pixels=True)
        except Exception:                                  # noqa: BLE001  not DICOM at all
            skipped += 1
            continue
        uid, modality = str(ds.get("StudyInstanceUID", "") or ""), str(ds.get("Modality", "") or "")
        if not uid or not modality or "SOPInstanceUID" not in ds:
            skipped += 1                                   # DICOMDIR and the like
            continue
        by_study.setdefault(uid, {}).setdefault(modality, []).append(path)

    studies, problems = [], []
    for by_modality in by_study.values():
        supported = {m: fs for m, fs in by_modality.items() if m in BY_MODALITY}
        skipped += sum(len(fs) for m, fs in by_modality.items() if m not in BY_MODALITY)
        if len(supported) != 1:
            named = ", ".join(sorted(by_modality))
            problems.append(f"a study has modality {named}; models are registered for "
                            f"{', '.join(sorted(BY_MODALITY))}, one per study")
            continue
        (modality, files), = supported.items()
        studies.append({"kind": "dicom", "type": BY_MODALITY[modality], "modality": modality,
                        "files": sorted(files)})
    studies += [{"kind": "image", "type": "chest", "modality": "CR", "files": [p]} for p in images]
    if not studies and not problems:
        problems.append("none of the files is a DICOM image or a PNG or JPEG")
    return studies, skipped, sorted(set(problems))


def wrap_image(path: Path, out: Path, rng: random.Random | None = None) -> Path:
    """A chest X-ray image -> one Computed Radiography DICOM file with a synthetic identity.
    The image's pixels are kept as they are; any text burned into them is the de-identifier's
    to mask, not this function's."""
    from sim.generator import make_dicom as md
    rng = rng or random.Random(secrets.randbits(64))
    when = datetime.datetime.now(datetime.timezone.utc)
    pixels, maxval = md.read_grayscale(path)
    ds = md.build_instance(pixels, maxval, md.make_identity(rng.randrange(10000, 99999), rng, when, False),
                           when, "an uploaded image")
    # build_instance describes a public NIH image; this is neither, and what is burned into the
    # pixels is not known here.
    ds.PatientComments = "SIMULATED IDENTITY - wrapped by AURALane from an uploaded image"
    ds.DerivationDescription = ("Wrapped from an uploaded image by AURALane. The identifiers are "
                                "generated and do not belong to anyone.")
    del ds.BurnedInAnnotation
    ds.save_as(out, enforce_file_format=True)
    return out


class Uploads:
    def __init__(self, table, runtime: str,
                 ingest_one: Callable[..., Any] | None = None,
                 dispatch: Callable[..., Any] | None = None,
                 on_study: Callable[[dict, dict | None, str], None] | None = None,
                 workers: int = 1, unavailable: str | None = None, spool: Path = SPOOL):
        """ingest_one(paths, model_id=) -> Verdict: the pipeline, in this process (local).
        dispatch(files, item, upload, index, set_fields) -> object with status, lane, error and
        study: the study goes to an ingest task in AWS instead (CloudUpload).
        on_study(row, reader, actor): called when a study is scored, to assign it to the reader."""
        self.table, self.runtime, self.unavailable = table, runtime, unavailable
        self.ingest_one, self.dispatch, self.on_study = ingest_one, dispatch, on_study
        self.workers, self.spool = workers, Path(spool)
        # Called after each study finishes: the API drops its caches (the pipeline wrote the row
        # through its own table object).
        self.after_study: Callable[[], None] | None = None
        self._lock = threading.Lock()
        self._uploads: dict[str, dict[str, Any]] = {}
        # Raw files left by a process that died are not kept.
        shutil.rmtree(self.spool, ignore_errors=True)

    # -- read -----------------------------------------------------------------
    def limits(self) -> dict[str, int]:
        return {"files": MAX_FILES, "file_mb": MAX_FILE_MB, "total_mb": MAX_TOTAL_MB,
                "studies": MAX_STUDIES}

    def info(self) -> dict[str, Any]:
        if self.unavailable:
            return {"available": False, "reason": self.unavailable, "runtime": self.runtime}
        return {"available": True, "reason": None, "runtime": self.runtime,
                "limits": self.limits(), "accepts": list(ACCEPTS),
                "types": [{"type": t, "label": LABELS[t], "modality": TYPES[t][0],
                           "pool": TYPES[t][2]} for t in TYPES]}

    def status(self, upload: str, owner_id: str) -> dict[str, Any]:
        with self._lock:
            u = self._get(upload, owner_id)
            return json.loads(json.dumps(self._public(u)))

    @staticmethod
    def _public(u: dict) -> dict:
        return {**{k: u[k] for k in ("upload", "state", "running", "opened_at", "finished_at",
                                     "files", "skipped")},
                "items": [{k: v for k, v in it.items() if not k.startswith("_")}
                          for it in u["items"]]}

    def _get(self, upload: str, owner_id: str) -> dict[str, Any]:
        u = self._uploads.get(upload)
        if u is None or u["owner"] != owner_id:          # someone else's is no different from none
            raise KeyError(upload)
        return u

    # -- receive --------------------------------------------------------------
    def open(self, reader: dict) -> dict[str, Any]:
        """A new, empty upload for this reader."""
        if self.unavailable:
            raise RuntimeError(self.unavailable)
        self._forget_old()
        with self._lock:
            live = [u for u in self._uploads.values()
                    if u["owner"] == reader["id"] and u["state"] == "open"]
            if len(live) >= OPEN_PER_READER:
                raise RuntimeError(f"{OPEN_PER_READER} uploads are already open; submit or "
                                   "discard one first")
            upload = secrets.token_hex(6)
            folder = self.spool / upload
            folder.mkdir(parents=True, exist_ok=True)
            self._uploads[upload] = {
                "upload": upload, "owner": reader["id"], "reader": reader, "state": "open",
                "running": False, "opened_at": _now(), "finished_at": None, "seen": time.monotonic(),
                "dir": folder, "received": {}, "files": 0, "bytes": 0, "skipped": 0, "items": []}
            return {"upload": upload, "state": "open", "limits": self.limits()}

    def begin(self, upload: str, owner_id: str, n: int) -> tuple[Path, int]:
        """Where file n goes, and how many bytes it may have. Raises KeyError (no such upload),
        ValueError (this file cannot be added)."""
        with self._lock:
            u = self._get(upload, owner_id)
            if u["state"] != "open":
                raise ValueError("this upload was already submitted")
            if not 0 <= n < MAX_FILES:
                raise ValueError(f"file numbers run from 0 to {MAX_FILES - 1}")
            if n not in u["received"] and u["files"] >= MAX_FILES:
                raise ValueError(f"at most {MAX_FILES} files in one upload")
            room = MAX_TOTAL_MB * 2**20 - u["bytes"] + u["received"].get(n, 0)
            if room <= 0:
                raise ValueError(f"at most {MAX_TOTAL_MB} MB in one upload")
            u["seen"] = time.monotonic()
            return u["dir"] / f"{n:05d}.part", min(room, MAX_FILE_MB * 2**20)

    def commit(self, upload: str, owner_id: str, n: int, size: int) -> dict[str, Any]:
        """File n arrived whole, size bytes. Sending the same n again replaces it."""
        with self._lock:
            u = self._get(upload, owner_id)
            u["bytes"] += size - u["received"].get(n, 0)
            u["received"][n] = size
            u["files"] = len(u["received"])
            return {"upload": upload, "files": u["files"], "bytes": u["bytes"]}

    def abort(self, upload: str, owner_id: str, n: int) -> None:
        """File n did not arrive whole: drop what was written of it."""
        with self._lock:
            u = self._uploads.get(upload)
            if u is not None and u["owner"] == owner_id:
                (u["dir"] / f"{n:05d}.part").unlink(missing_ok=True)
                if u["received"].pop(n, None) is not None:
                    u["files"] = len(u["received"])

    def discard(self, upload: str, owner_id: str) -> None:
        """Forget an upload that was not submitted, and delete its files."""
        with self._lock:
            u = self._get(upload, owner_id)
            if u["state"] != "open":
                raise ValueError("this upload was already submitted")
            del self._uploads[upload]
        shutil.rmtree(u["dir"], ignore_errors=True)

    def _forget_old(self) -> None:
        with self._lock:
            old = [k for k, u in self._uploads.items()
                   if not u["running"] and time.monotonic() - u["seen"] > KEEP_S]
            gone = [self._uploads.pop(k) for k in old]
        for u in gone:
            shutil.rmtree(u["dir"], ignore_errors=True)

    # -- submit ---------------------------------------------------------------
    def plan(self, upload: str, owner_id: str) -> tuple[list[dict], int]:
        """The studies in an upload, checked. Raises ValueError with every problem at once."""
        with self._lock:
            u = self._get(upload, owner_id)
            if u["state"] != "open":
                raise ValueError("this upload was already submitted")
            paths = sorted(u["dir"] / f"{n:05d}.part" for n in u["received"])
            reader = u["reader"]
        if not paths:
            raise ValueError("no files were uploaded")
        studies, skipped, problems = classify(paths)
        if len(studies) > MAX_STUDIES:
            problems.append(f"{len(studies)} studies; at most {MAX_STUDIES} in one upload")
        for pool in sorted({TYPES[s["type"]][2] for s in studies} - set(reader["pools"])):
            problems.append(f"you do not read the {pool} pool, so a study in it cannot go on "
                            "your worklist")
        if problems:
            raise ValueError("; ".join(problems))
        return studies, skipped

    def submit(self, upload: str, owner_id: str, actor: str) -> dict[str, Any]:
        """Check the upload and start it in the background. -> its status, at once."""
        if self.unavailable:
            raise RuntimeError(self.unavailable)
        studies, skipped = self.plan(upload, owner_id)
        with self._lock:
            u = self._get(upload, owner_id)
            if u["state"] != "open":
                raise ValueError("this upload was already submitted")
            u.update(state="submitted", running=True, skipped=skipped, seen=time.monotonic(),
                     items=[{"n": i + 1, "type": s["type"], "label": LABELS[s["type"]],
                             "modality": s["modality"], "files": len(s["files"]),
                             "status": "queued", "lane": None, "study": None, "patient_id": None,
                             "error": None, "_files": s["files"], "_kind": s["kind"]}
                            for i, s in enumerate(studies)])
        threading.Thread(target=self._run, args=(upload, actor), daemon=True).start()
        return self.status(upload, owner_id)

    def _set(self, upload: str, i: int, **fields) -> None:
        with self._lock:
            self._uploads[upload]["items"][i].update(fields)

    def _run(self, upload: str, actor: str) -> None:
        with self._lock:
            u = self._uploads[upload]
            items, reader, folder = list(u["items"]), u["reader"], u["dir"]

        def one(i: int, item: dict) -> None:
            files: list[Path] = item["_files"]
            made: list[Path] = []
            try:
                self._set(upload, i, status="receiving")
                if item["_kind"] == "image":
                    wrapped = folder / f"image-{i:03d}.dcm"
                    made.append(wrap_image(files[0], wrapped))
                    files = made
                self._set(upload, i, status="running")
                if self.dispatch is not None:
                    v = self.dispatch(files, item, upload, i,
                                      lambda **f: self._set(upload, i, **f))
                    study = getattr(v, "study", None)
                else:
                    v = self.ingest_one(files, model_id=TYPES[item["type"]][1])
                    study = v.ref.study_uid if getattr(v, "ref", None) else None
                row = self.table.get_item("worklist", {"study": study}) if study else None
                if row is not None and self.on_study is not None:
                    self.on_study(row, reader, actor)
                self._set(upload, i, status="done" if v.status == "SCORED" else "failed",
                          lane=v.lane, error=v.error, study=study,
                          patient_id=row.get("patient_id") if row else None)
            except Exception as e:                           # noqa: BLE001
                self._set(upload, i, status="failed", error=f"{type(e).__name__}: {e}")
            finally:
                for f in item["_files"] + made:              # the raw file is gone once handled
                    f.unlink(missing_ok=True)
                if self.after_study is not None:
                    try:
                        self.after_study()
                    except Exception:                        # noqa: BLE001
                        pass

        with ThreadPoolExecutor(self.workers) as pool:
            list(pool.map(lambda a: one(*a), enumerate(items)))
        shutil.rmtree(folder, ignore_errors=True)
        with self._lock:
            self._uploads[upload].update(running=False, finished_at=_now(), seen=time.monotonic())
            for it in self._uploads[upload]["items"]:
                it.pop("_files", None)
                it.pop("_kind", None)


class CloudUpload:
    """Hands an uploaded study to an ingest task in AWS and waits for its result.

    The files go to upload/own-<upload>/<item>/ with a manifest; the manifest's arrival starts
    one Fargate task (core/cloud_ingest.py), which de-identifies, imports into HealthImaging,
    calls the models and writes the worklist row, then intake/own-<upload>/<item>.json. The raw
    files are deleted by the task, and expire from the bucket after a day if it never runs."""

    def __init__(self, s3, bucket: str, site_state: str | None = None,
                 timeout_s: float = 40 * 60, poll_s: float = 5.0):
        self.s3, self.bucket, self.site_state = s3, bucket, site_state
        self.timeout_s, self.poll_s = timeout_s, poll_s

    def __call__(self, files: list[Path], item: dict, upload: str, index: int, set_fields):
        from core.upload import RESULTS, upload_study, wait_result
        batch, name = f"own-{upload}", f"{index:03d}"
        upload_study(self.s3, self.bucket, files, batch, name, site_state=self.site_state,
                     modality=item["modality"])
        set_fields(status="running")
        r = wait_result(self.s3, self.bucket, f"{RESULTS}{batch}/{name}.json",
                        self.timeout_s, self.poll_s)
        return SimpleNamespace(status=r.get("status"), lane=r.get("lane"), error=r.get("error"),
                               study=r.get("study"))
