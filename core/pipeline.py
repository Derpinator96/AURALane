"""The ingest pipeline. One function, both runtimes, ports only.

    1 deidentify    sim/edge/deid.py, pseudonyms recorded in the identity map
    2 blob_put      the cleaned study, transient copy
    3 import        datastore.import_study
    4 infer         registry entry by modality, inference.score
    5 adapt         adapter.adapt -> Findings
    6 triage        triage.rank -> lane, or abstention
    7 persist       worklist row
    8 blob_delete   the transient copy, always, even after a failure

Every step appends an audit event with its measured duration in milliseconds.
If a step raises, the audit records the failure, the worklist gets a row with
status FAILED, and the remaining model steps are skipped. A study that errors
stays visible; a study that disappears is worse.

De-identification runs first and nothing is written anywhere before it
succeeds. deidentify raises OCRUnavailable when burned-in text cannot be
searched for, and that is a FAILED study, not a partially cleaned one.
"""
from __future__ import annotations

import datetime
import importlib.util
import io
import tempfile
import time
import traceback
import uuid
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

import pydicom

from core.ports import BlobPort, DatastorePort, InferencePort, TablePort
from core.registry import Registry, rank
from core.types import AuditEvent, Findings, StudyMeta, Verdict
from core.volumes import series_to_nifti

ROOT = Path(__file__).resolve().parents[1]
ACTOR = "pipeline"


def _load_deid():
    spec = importlib.util.spec_from_file_location("deid", ROOT / "sim" / "edge" / "deid.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


deid = _load_deid()


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="microseconds")


class _Run:
    """Holds per-run state and writes one audit event per step."""

    def __init__(self, table: TablePort):
        self.table = table
        self.id = uuid.uuid4().hex[:12]
        self.study: str | None = None          # pseudonymous StudyInstanceUID, once known

    @contextmanager
    def step(self, action: str, **detail):
        start = time.perf_counter()
        try:
            yield detail
        except Exception as e:
            detail["error"] = f"{type(e).__name__}: {e}"
            self._audit(action, "failed", start, detail)
            raise
        self._audit(action, "ok", start, detail)

    def _audit(self, action, outcome, start, detail):
        self.table.append_audit(AuditEvent(
            actor=ACTOR, action=action, study=self.study, at=_now(), outcome=outcome,
            duration_ms=round((time.perf_counter() - start) * 1000, 3),
            detail={"run_id": self.id, **detail}))


def _model_inputs(entry: dict, cleaned: list, meta: StudyMeta, workdir: Path) -> dict[str, Any]:
    fmt = entry["input"]["format"]
    if fmt == "dicom":
        if len(cleaned) != 1:
            raise ValueError(f"{entry['id']} takes one image, study has {len(cleaned)}")
        return {"pixels": cleaned[0].pixel_array}
    if fmt == "nifti":
        channels = entry["input"]["channels"]
        if len(meta.series) != len(channels):
            raise ValueError(f"{entry['id']} needs {len(channels)} series, study has "
                             f"{len(meta.series)}")
        by_series = defaultdict(list)
        for ds in cleaned:
            by_series[str(ds.SeriesInstanceUID)].append(ds)
        # SeriesNumber n is model channel n-1 (nifti_to_dicom.py writes them so).
        # The sequence names cannot be cross-checked here: de-identification
        # replaces SeriesDescription (PS3.15 Clean Descriptors), so after step 1
        # every series reads "TRIAGE SERIES". A source that numbers its series in
        # a different order is not caught, and a scrambled order still yields a
        # plausible-looking mask. Known limitation, stated in docs/HOW-IT-WORKS.md.
        numbers = [s.number for s in meta.series]
        if numbers != list(range(1, len(channels) + 1)):
            raise ValueError(f"series numbers {numbers}; expected 1..{len(channels)} "
                             f"in channel order {channels}")
        paths = {}
        for channel, series in zip(channels, meta.series):
            path = workdir / f"{channel}.nii.gz"
            series_to_nifti(by_series[series.series_uid]).to_filename(path)
            paths[channel] = path
        return {"nifti": paths}
    raise ValueError(f"no input builder for format {fmt!r}")


def ingest(paths: Iterable[Path], *, blob: BlobPort, datastore: DatastorePort,
           table: TablePort, inference: InferencePort, registry: Registry,
           identity) -> Verdict:
    run = _Run(table)
    paths = sorted(Path(p) for p in paths)
    keys: list[str] = []
    ref = entry = findings = None
    meta: StudyMeta | None = None

    try:
        with tempfile.TemporaryDirectory(prefix="auralane-ingest-") as tmp:
            work = Path(tmp)

            with run.step("deidentify", instances=len(paths)) as d:
                if not paths:
                    raise ValueError("no DICOM files to ingest")
                cleaned, masked = [], 0
                for p in paths:
                    ds = pydicom.dcmread(p)
                    masked += deid.deidentify(ds, identity)["text_regions_masked"]
                    cleaned.append(ds)
                uids = {str(ds.StudyInstanceUID) for ds in cleaned}
                if len(uids) != 1:
                    raise ValueError(f"files span {len(uids)} studies; ingest one at a time")
                run.study = uids.pop()
                d["text_regions_masked"] = masked

            with run.step("blob_put") as d:
                files = []
                for ds in cleaned:
                    buf = io.BytesIO()
                    ds.save_as(buf, enforce_file_format=True)
                    key = f"transient/{run.id}/{ds.SOPInstanceUID}.dcm"
                    keys.append(blob.put(key, buf.getvalue()))
                    local = work / "dicom" / f"{ds.SOPInstanceUID}.dcm"
                    local.parent.mkdir(exist_ok=True)
                    local.write_bytes(buf.getvalue())
                    files.append(local)
                d["objects"] = len(keys)

            with run.step("import") as d:
                ref = datastore.import_study(files)
                meta = datastore.get_metadata(ref)
                d.update(datastore_id=ref.datastore_id, modality=meta.modality,
                         series=len(meta.series))

            with run.step("infer") as d:
                entry = registry.for_modality(meta.modality)
                d.update(model_id=entry["id"], runtime=entry["runtime"])
                inputs = _model_inputs(entry, cleaned, meta, work)
                raw = inference.score(ref, entry, **inputs)

            with run.step("adapt", model_id=entry["id"]) as d:
                findings = registry.adapter(entry).adapt(raw, {
                    "entry": entry, "study": run.study, "blob": blob,
                    "inputs": inputs, "model_output": raw})
                if not isinstance(findings, Findings):
                    raise TypeError(f"{entry['adapter']}.adapt returned {type(findings).__name__}")
                d.update(findings=len(findings.findings), evidence=sorted(findings.evidence))

            with run.step("triage") as d:
                if findings.findings:
                    t = rank(findings, entry)
                else:
                    t = {"lane": "ABSTAIN", "abstained": True, "sla": "a human picks the lane",
                         "reason": findings.meta.get("abstain_reason", "no findings")}
                d.update(lane=t["lane"], acuity=t.get("acuity"), driver=t.get("driver"))
            verdict = Verdict(ref=ref, model_id=entry["id"], status="SCORED",
                              lane=t["lane"], triage=t, findings=findings)

            with run.step("persist", table="worklist"):
                table.put_item("worklist", _row(run, verdict, meta))
    except Exception as e:
        verdict = Verdict(ref=ref, model_id=entry["id"] if entry else None, status="FAILED",
                          lane="FAILED", findings=findings,
                          error=f"{type(e).__name__}: {e}")
        _persist_failure(run, verdict, meta, traceback.format_exc(limit=3))
    finally:
        _delete_transient(run, blob, keys)
    return verdict


def _row(run: _Run, v: Verdict, meta: StudyMeta | None) -> dict[str, Any]:
    return {
        "study": run.study or f"run:{run.id}",
        "run_id": run.id,
        "status": v.status,
        "lane": v.lane,
        "model_id": v.model_id,
        "modality": meta.modality if meta else None,
        "study_date": meta.study_date if meta else None,
        "patient_id": meta.patient_id if meta else None,       # pseudonym
        "datastore_id": v.ref.datastore_id if v.ref else None,
        "triage": v.triage,
        "findings": v.findings.findings if v.findings else {},
        "evidence": v.findings.evidence if v.findings else {},
        "error": v.error,
        "created_at": _now(),
    }


def _persist_failure(run: _Run, v: Verdict, meta, tb: str) -> None:
    """Best effort: a failure to record a failure must not hide the first one."""
    try:
        with run.step("persist", table="worklist", status="FAILED"):
            run.table.put_item("worklist", _row(run, v, meta))
    except Exception:
        v.error = f"{v.error}; and the FAILED row could not be written"


def _delete_transient(run: _Run, blob: BlobPort, keys: list[str]) -> None:
    try:
        with run.step("blob_delete", objects=len(keys)):
            for k in keys:
                blob.delete(k)
    except Exception:
        pass            # recorded in the audit by run.step
