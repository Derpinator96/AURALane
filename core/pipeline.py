"""The ingest pipeline. One function, both runtimes, ports only.

    1 deidentify    sim/edge/deid.py, pseudonyms recorded in the identity map
    2 blob_put      the cleaned study, transient copy
    3 import        datastore.import_study
    4 prepare_inputs  registry entry by modality; the model's inputs (for brain,
                      channels identified and rebuilt as NIfTI)
    5 infer         inference.score, the model alone
    6 adapt         adapter.adapt -> Findings
    6b regional_prior  chest only: a bounded nudge from the site's state
                    (core/regional.py), after the z-score, before the lane
    7 triage        triage.rank -> lane, or abstention
    8 evidence      derived artefacts in blob storage under evidence/<study>/: the
                    Grad-CAM or overlay the model step wrote, and for volume
                    models the input NIfTI and the segmentation, which the 3D
                    viewer loads through presigned URLs
    9 persist       worklist row
   10 blob_delete   the transient copy, always, even after a failure

Studies staged by scripts/stage_pool.py were de-identified at the edge before
upload. ingest(edge_reports=...) takes them as they are: step 1 then checks
every instance carries the de-identification marks and records where the work
was done, instead of doing it twice. An instance without the marks fails the
study; it is never cleaned here as a fallback.

Each step's audit detail names the service that ran it (the provider's
.service), so the pipeline view shows HealthImaging or Orthanc from the run
itself, not from a guess about the runtime.

prepare_inputs and infer are separate steps so the audit, and the latency
table built from it, never counts pipeline overhead as model time.

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
import os
import tempfile
import time
import traceback
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

import pydicom

from core import series_index
from core.ports import BlobPort, DatastorePort, InferencePort, TablePort
from core.regional import RegionalSetting
from core.regional import apply as apply_regional
from core.registry import Registry, rank
from core.types import AuditEvent, Findings, StudyMeta, Verdict
from core.volumes import series_to_nifti, sort_slices

ROOT = Path(__file__).resolve().parents[1]
ACTOR = "pipeline"
HERE = "the pipeline process"      # steps that run where ingest() runs


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

    def __init__(self, table: TablePort, run_id: str | None = None):
        self.table = table
        self.id = run_id or uuid.uuid4().hex[:12]
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


def _conform(ds) -> None:
    """Some public sets (the RSNA head CTs) carry the SOP class only in the file meta. DICOM
    requires it in the dataset too, and Orthanc's STOW-RS rejects an instance without it, so it is
    copied across. The value is the file's own; nothing is invented."""
    meta = getattr(ds, "file_meta", None)
    if "SOPClassUID" not in ds and meta is not None and meta.get("MediaStorageSOPClassUID"):
        ds.SOPClassUID = meta.MediaStorageSOPClassUID


def _workers(n: int | None) -> int:
    return max(1, n or os.cpu_count() or 1)


@contextmanager
def _omp_limit(active: bool):
    """OMP_THREAD_LIMIT=1 for the duration, then the environment as it was."""
    if not active or "OMP_THREAD_LIMIT" in os.environ:
        yield
        return
    os.environ["OMP_THREAD_LIMIT"] = "1"
    try:
        yield
    finally:
        os.environ.pop("OMP_THREAD_LIMIT", None)


def deidentify_all(paths: Iterable[Path], identity, workers: int | None = None):
    """De-identify every instance, OCR included, on a thread pool.

    Every instance is de-identified and every image gets both OCR passes;
    parallelism changes only wall time, never which pixels are searched. No
    slice is sampled or skipped: a name on the one slice nobody OCRs is the
    failure this step exists to prevent.

    Threads, not processes: pytesseract.image_to_data runs the tesseract binary
    as a subprocess, so the wait happens outside the GIL, and arrays are not
    pickled. identity.IdentityMap takes a lock and opens its own connection per
    call, so sharing it across threads keeps UID mapping consistent.

    workers defaults to os.cpu_count(). Returns (datasets, reports) in the
    order of paths. The first exception from any instance is raised.
    """
    paths = list(paths)
    workers = _workers(workers)

    # Each tesseract process starts an OpenMP thread team sized to the machine.
    # Several at once oversubscribe the CPUs and spin against each other.
    # Measured on the 4-core build container, 16 synthetic 320 px images:
    #   OMP_THREAD_LIMIT unset: 1 worker 5.2 s, 2 workers 91.6 s, 4 workers 299.2 s
    #   OMP_THREAD_LIMIT=1:     1 worker 5.1 s, 2 workers  2.5 s, 4 workers   1.3 s
    # pytesseract hands os.environ to the subprocess, so the limit has to be in
    # os.environ, but only while OCR runs. Left set, torch (imported later for
    # inference) inherits it: its OpenMP runtime starts capped at one thread
    # while torch asks for one per core, and the chest Grad-CAM backward pass
    # did not finish in 120 s instead of taking 4.5 s. So it is restored after.
    # An explicit OMP_THREAD_LIMIT from the operator is left alone.
    def one(p):
        ds = pydicom.dcmread(p)
        return ds, deid.deidentify(ds, identity)

    with _omp_limit(workers > 1), ThreadPoolExecutor(max_workers=workers) as pool:
        done = list(pool.map(one, paths))
    return [ds for ds, _ in done], [r for _, r in done]


def _model_inputs(entry: dict, adapter, cleaned: list, meta: StudyMeta,
                  workdir: Path) -> dict[str, Any]:
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
        # The adapter identifies each channel from the sequence token deid.py
        # keeps (T1C, T1, T2, FLAIR) and raises if it cannot. SeriesNumber is
        # never used for this: it follows acquisition order.
        paths = {}
        for channel, series in adapter.resolve_channels(meta.series, entry).items():
            path = workdir / f"{channel}.nii.gz"
            series_to_nifti(by_series[series.series_uid]).to_filename(path)
            paths[channel] = path
        return {"nifti": paths}
    if fmt == "dicom-series":
        # Head CT: one series of slices, each with its own rescale. The series
        # with the most slices, as triagelane-ct's discover_study_dicom_paths
        # chooses; ordered by position, not by InstanceNumber.
        by_series = defaultdict(list)
        for ds in cleaned:
            by_series[str(ds.SeriesInstanceUID)].append(ds)
        chosen = sort_slices(max(by_series.values(), key=len))
        return {"slices": [(ds.pixel_array, float(ds.get("RescaleSlope", 1) or 1),
                            float(ds.get("RescaleIntercept", 0) or 0)) for ds in chosen]}
    raise ValueError(f"no input builder for format {fmt!r}")


def _masked_input_slices(entry: dict, adapter, cleaned: list, reports: list,
                         meta: StudyMeta) -> dict[str, list[int]]:
    """{model channel: axial indices} of the input slices where de-identification
    blanked regions it read as text. Indices are voxel k in the volume
    series_to_nifti builds. Empty when nothing was blanked, and for non-volume
    inputs.

    The OCR pass can read anatomy as text: on BraTS 2021 case 00621 it blanked
    8 of 620 slices, none of which carry burned-in text. A blanked box inside
    the brain changes the model's input and reads as outside the brain to
    core/mask_check.py, so the adapter names these slices when a check fails.
    """
    if entry["input"]["format"] != "nifti":
        return {}
    masked = {str(ds.SOPInstanceUID) for ds, r in zip(cleaned, reports)
              if r["text_regions_masked"]}
    if not masked:
        return {}
    by_series = defaultdict(list)
    for ds in cleaned:
        by_series[str(ds.SeriesInstanceUID)].append(ds)
    out = {}
    for channel, series in adapter.resolve_channels(meta.series, entry).items():
        ks = [k for k, ds in enumerate(sort_slices(by_series[series.series_uid]))
              if str(ds.SOPInstanceUID) in masked]
        if ks:
            out[channel] = ks
    return out


def service(provider, entry: dict | None = None) -> str:
    """The name a provider gives itself, for the audit (pipeline view)."""
    name = getattr(provider, "service", None)
    if callable(name):
        return name(entry)
    return name or type(provider).__name__


def check_edge_deid(cleaned: list) -> None:
    """Studies de-identified at the edge must say so on every instance
    (PS3.15: PatientIdentityRemoved YES, a DeidentificationMethod)."""
    bad = [str(ds.get("SOPInstanceUID", "?")) for ds in cleaned
           if str(ds.get("PatientIdentityRemoved", "")).upper() != "YES"
           or not ds.get("DeidentificationMethod")]
    if bad:
        raise ValueError(f"{len(bad)} of {len(cleaned)} instances are not marked de-identified "
                         f"(first {bad[0]}); refusing to store them")


def _evidence(entry: dict, study: str, findings: Findings, inputs: dict, raw: Any,
              blob: BlobPort, d: dict, cleaned: list | None = None,
              series_index_bytes=None) -> Findings:
    """Volume models: the model's NIfTI inputs and its segmentation, to
    evidence/<study>/ for the 3D viewer. Every model: record what evidence the
    row points at, and the slim series index the viewer reads instead of asking
    the datastore for metadata (core/series_index.py)."""
    evidence = dict(findings.evidence)
    if series_index_bytes is not None:
        try:
            evidence["series_index"] = blob.put(f"evidence/{study}/series_index.json.gz",
                                                series_index_bytes())
        except Exception as e:                       # best effort: the API falls back to DICOMweb
            d["series_index_error"] = f"{type(e).__name__}: {e}"
    # Kept for abstained studies too: that is when a radiologist most needs
    # to look, to pick the lane the model would not.
    if entry["input"]["format"] == "nifti":
        volumes = {}
        for channel, path in inputs["nifti"].items():
            volumes[channel] = blob.put(f"evidence/{study}/{channel.lower()}.nii.gz",
                                        Path(path).read_bytes())
        evidence["volumes"] = volumes
        # The segmentation only when the study scored: an abstained study's mask
        # failed the check (core/mask_check.py) or was below the volume gate,
        # and must not be drawn as if it were the model's finding.
        pred = raw.get("_prediction_path") if isinstance(raw, dict) else None
        if findings.findings and pred and Path(pred).exists():
            evidence["segmentation"] = blob.put(f"evidence/{study}/segmentation.nii.gz",
                                                Path(pred).read_bytes())
    if entry["modality"] == "CT" and cleaned:
        # The head CT as a volume for the 3D viewer. Best effort: the worklist row
        # and the Grad-CAM do not depend on it.
        try:
            from core.volumes import ct_volume_bytes
            evidence["volumes"] = {"CT": blob.put(f"evidence/{study}/ct.nii.gz",
                                                  ct_volume_bytes(cleaned))}
        except Exception as e:
            d["ct_volume_error"] = f"{type(e).__name__}: {e}"
    d["keys"] = sorted(k for k, v in evidence.items() if isinstance(v, (str, dict))
                       and k not in ("regional", "ct", "channels"))
    return Findings(findings=findings.findings, meta=findings.meta, evidence=evidence)


def ingest(paths: Iterable[Path], *, blob: BlobPort, datastore: DatastorePort,
           table: TablePort, inference: InferencePort, registry: Registry,
           identity, ocr_workers: int | None = None,
           regional: RegionalSetting | None = None,
           edge_reports: dict[str, int] | None = None,
           run_id: str | None = None, model_id: str | None = None) -> Verdict:
    """edge_reports: for studies de-identified at the edge (stage_pool.py),
    {SOPInstanceUID: text regions masked there}; the study is checked, not
    cleaned again. run_id: to join events the caller wrote before this run.
    model_id: the registry entry to use, when the caller knows it (simulated
    ingest); otherwise the one registered for the study's modality."""
    run = _Run(table, run_id)
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
                if edge_reports is not None:
                    cleaned = [pydicom.dcmread(p) for p in paths]
                    check_edge_deid(cleaned)
                    reports = [{"text_regions_masked": int(edge_reports.get(
                        str(ds.SOPInstanceUID), 0))} for ds in cleaned]
                    d["where"] = "edge, before upload (scripts/stage_pool.py); checked here"
                    d["service"] = "edge de-identifier (sim/edge/deid.py)"
                else:
                    cleaned, reports = deidentify_all(paths, identity, ocr_workers)
                    d["ocr_workers"] = _workers(ocr_workers)
                    d["service"] = "sim/edge/deid.py, in this process"
                masked = sum(r["text_regions_masked"] for r in reports)
                uids = {str(ds.StudyInstanceUID) for ds in cleaned}
                if len(uids) != 1:
                    raise ValueError(f"files span {len(uids)} studies; ingest one at a time")
                run.study = uids.pop()
                d["text_regions_masked"] = masked

            with run.step("blob_put", service=service(blob)) as d:
                files, items = [], []
                for ds in cleaned:
                    _conform(ds)
                    buf = io.BytesIO()
                    ds.save_as(buf, enforce_file_format=True)
                    items.append((f"transient/{run.id}/{ds.SOPInstanceUID}.dcm", buf.getvalue()))
                    local = work / "dicom" / f"{ds.SOPInstanceUID}.dcm"
                    local.parent.mkdir(exist_ok=True)
                    local.write_bytes(buf.getvalue())
                    files.append(local)
                # 16 at a time: to S3 each put is a round trip to us-east-1.
                with ThreadPoolExecutor(16) as pool:
                    keys.extend(pool.map(lambda kv: blob.put(*kv), items))
                d["objects"] = len(keys)

            with run.step("import", service=service(datastore)) as d:
                ref = datastore.import_study(files)
                meta = datastore.get_metadata(ref)
                d.update(datastore_id=ref.datastore_id, modality=meta.modality,
                         series=len(meta.series))

            with run.step("prepare_inputs", service=HERE) as d:
                entry = (registry.entries[model_id] if model_id
                         else registry.for_modality(meta.modality))
                if entry["modality"] != meta.modality:
                    raise ValueError(f"{entry['id']} reads {entry['modality']}, the study is "
                                     f"{meta.modality}")
                d.update(model_id=entry["id"], format=entry["input"]["format"])
                inputs = _model_inputs(entry, registry.adapter(entry), cleaned, meta, work)
                deid_masked = _masked_input_slices(entry, registry.adapter(entry), cleaned,
                                                   reports, meta)
                if deid_masked:
                    d["deid_masked_slices"] = deid_masked

            with run.step("infer", model_id=entry["id"], runtime=entry["runtime"],
                          service=service(inference, entry)):
                raw = inference.score(ref, entry, **inputs)

            with run.step("adapt", model_id=entry["id"], service=HERE) as d:
                findings = registry.adapter(entry).adapt(raw, {
                    "entry": entry, "study": run.study, "blob": blob,
                    "inputs": inputs, "model_output": raw, "deid_masked": deid_masked})
                if not isinstance(findings, Findings):
                    raise TypeError(f"{entry['adapter']}.adapt returned {type(findings).__name__}")
                d.update(findings=len(findings.findings), evidence=sorted(findings.evidence))
                if "mask_check" in findings.meta:            # brain Check A, core/mask_check.py
                    mc = findings.meta["mask_check"]
                    # Every criterion's measured value and limit, not only the names
                    # that failed, so the audit shows by how much.
                    d.update(mask_check_passed=mc["passed"], mask_check_failed=mc["failed"],
                             mask_check=mc["criteria"])

            if entry.get("regional_prior") and regional is not None:
                with run.step("regional_prior", service=HERE) as d:
                    findings = _regional(findings, regional, d)

            with run.step("triage", service=HERE) as d:
                if findings.findings:
                    t = rank(findings, entry)
                else:
                    t = {"lane": "ABSTAIN", "abstained": True, "sla": "a human picks the lane",
                         "reason": findings.meta.get("abstain_reason", "no findings")}
                d.update(lane=t["lane"], acuity=t.get("acuity"), driver=t.get("driver"))
            verdict = Verdict(ref=ref, model_id=entry["id"], status="SCORED",
                              lane=t["lane"], triage=t, findings=findings, run_id=run.id)

            with run.step("evidence", service=service(blob)) as d:
                findings = _evidence(entry, run.study, findings, inputs, raw, blob, d, cleaned,
                                     lambda: series_index.dumps(series_index.build(datastore, ref, meta)))
                verdict.findings = findings

            with run.step("persist", table="worklist", service=service(table)):
                table.put_item("worklist", _row(run, verdict, meta))
    except Exception as e:
        verdict = Verdict(ref=ref, model_id=entry["id"] if entry else None, status="FAILED",
                          lane="FAILED", findings=findings,
                          error=f"{type(e).__name__}: {e}", run_id=run.id)
        _persist_failure(run, verdict, meta, traceback.format_exc(limit=3))
    finally:
        _delete_transient(run, blob, keys)
    return verdict


def _regional(findings: Findings, regional: RegionalSetting, d: dict) -> Findings:
    """Apply the site's regional prior to chest signals, or record why not.
    The evidence always says which, so the rationale panel never guesses."""
    if not regional.enabled or regional.state is None:
        why = "off (AURALANE_REGIONAL_PRIOR=off)" if not regional.enabled else "no site state set"
        d["applied"] = why
        return Findings(findings=findings.findings, meta=findings.meta,
                        evidence={**findings.evidence,
                                  "regional": {"state": regional.state, "applied": False,
                                               "reason": why}})
    adjusted, ev = apply_regional(findings.findings, regional.state)
    d.update(applied=True, state=regional.state,
             factors={k: v["factor"] for k, v in ev["factors"].items()})
    return Findings(findings=adjusted, meta=findings.meta,
                    evidence={**findings.evidence, "regional": {**ev, "applied": True}})


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
        with run.step("persist", table="worklist", status="FAILED",
                      service=service(run.table)):
            run.table.put_item("worklist", _row(run, v, meta))
    except Exception:
        v.error = f"{v.error}; and the FAILED row could not be written"


def _delete_transient(run: _Run, blob: BlobPort, keys: list[str]) -> None:
    try:
        with run.step("blob_delete", objects=len(keys), service=service(blob)):
            with ThreadPoolExecutor(16) as pool:
                list(pool.map(blob.delete, keys))
    except Exception:
        pass            # recorded in the audit by run.step
