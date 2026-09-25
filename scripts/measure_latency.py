"""Measure per-step pipeline latency and write docs/LATENCY.md.

    docker compose -f docker-compose.local.yml up -d
    AURALANE_RUNTIME=local python scripts/measure_latency.py \\
        --chest data/chest/studies/<study dir> --brain data/brain/dicom/<study dir>

Runs core.pipeline.ingest over one chest and one brain study, --runs times
each (default 2), with the local providers. The durations are not timed here:
they are read back from the audit events the pipeline writes for that run, so
the table shows exactly what the audit trail records.

Run 1 includes loading the model into memory. Later runs re-ingest the same
study: the identity map returns the same pseudonyms and the datastore already
holds the instances. One machine, one study per modality: a measurement, not a
benchmark.

The brain run needs the SegResNet checkpoint (git lfs pull in
_external/brainmri). Without it the brain column shows the step that failed.
"""
from __future__ import annotations

import argparse
import datetime
import os
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

STEPS = ["deidentify", "blob_put", "import", "infer", "adapt", "triage", "persist",
         "blob_delete"]
OUT = ROOT / "docs" / "LATENCY.md"


def _cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def machine() -> dict[str, str]:
    return {"Platform": platform.platform(), "CPU": _cpu_model(),
            "Logical CPUs": str(os.cpu_count()), "Python": platform.python_version()}


def run_events(table, verdict) -> list[dict]:
    """This run's audit events, in order."""
    from core.providers.aws._dynamodb import NO_STUDY
    rows = []
    for study in {verdict.ref.study_uid if verdict.ref else None, NO_STUDY} - {None}:
        rows += table.query("audit", study=study)
    return sorted((r for r in rows if r["detail"].get("run_id") == verdict.run_id),
                  key=lambda r: r["event_id"])


def render(columns: list[tuple[str, dict | None]], info: dict[str, str] | None) -> str:
    """columns: [(heading, {"status": str, "events": [audit rows]} or None)].

    None renders an empty column. With info None the page says it is awaiting a run.
    """
    lines = ["# Pipeline latency per step, from the audit trail", ""]
    if info is None:
        lines += ["**Awaiting a local run of `scripts/measure_latency.py`. No figure on this "
                  "page has been measured yet.** The previous single figure (about 70 s) was "
                  "an estimate for one chest image, not a measurement.", ""]
    else:
        lines += [f"Measured by `scripts/measure_latency.py` on {info.pop('Date')}. "
                  "Every duration is read from the audit event the pipeline wrote for that "
                  "step, in milliseconds.", ""]
        lines += [f"- {k}: {v}" for k, v in info.items()] + [""]

    lines.append("| step | " + " | ".join(h for h, _ in columns) + " |")
    lines.append("|---|" + "---:|" * len(columns))

    def cell(col, step):
        if col is None:
            return "not measured"
        ev = [e for e in col["events"] if e["action"] == step]
        if not ev:
            return "not reached"
        e = ev[-1]
        return f"{e['duration_ms']:,.1f}" + ("" if e["outcome"] == "ok" else " (failed)")

    for step in STEPS:
        lines.append(f"| {step} | " + " | ".join(cell(c, step) for _, c in columns) + " |")
    totals = []
    for _, c in columns:
        totals.append("not measured" if c is None else
                      f"{sum(e['duration_ms'] for e in c['events']):,.1f}")
    lines.append("| **total** | " + " | ".join(totals) + " |")
    lines.append("| outcome | " + " | ".join(
        "not measured" if c is None else c["status"] for _, c in columns) + " |")
    lines += ["", "Run 1 includes loading the model into memory. Later runs re-ingest the "
              "same study, so the datastore already holds its instances. `infer` includes "
              "assembling the model inputs (for brain, rebuilding four NIfTI volumes from "
              "DICOM). One machine and one study per modality: a measurement, not a "
              "benchmark.", ""]
    return "\n".join(lines)


def empty_page(runs: int = 2) -> str:
    return render([(h, None) for h in headings(runs)], None)


def headings(runs: int) -> list[str]:
    return [f"{m} run {i}{' (cold)' if i == 1 else ''} ms"
            for m in ("chest", "brain") for i in range(1, runs + 1)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chest", required=True, help="one chest study directory")
    ap.add_argument("--brain", required=True, help="one brain study directory")
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--ocr-workers", type=int, default=None)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)

    from core.pipeline import _workers, ingest
    from core.registry import Registry
    from core.run import _identity, providers

    p = providers()
    if p["runtime"] != "local":
        sys.exit("measure_latency.py measures the local runtime")
    registry, ident = Registry(), _identity()
    columns, counts = [], {}
    for modality, path in (("chest", Path(args.chest)), ("brain", Path(args.brain))):
        files = sorted(path.rglob("*.dcm"))
        if not files:
            sys.exit(f"no .dcm files under {path}")
        counts[modality] = len(files)
        for i in range(1, args.runs + 1):
            v = ingest(files, blob=p["blob"], datastore=p["datastore"], table=p["table"],
                       inference=p["inference"], registry=registry, identity=ident,
                       ocr_workers=args.ocr_workers)
            status = v.status if v.status == "FAILED" else f"{v.status}, {v.lane}"
            columns.append((headings(args.runs)[len(columns)],
                            {"status": status, "events": run_events(p["table"], v)}))
            print(f"{modality} run {i}: {status}" + (f" ({v.error})" if v.error else ""))

    info = {"Date": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            **machine(), "OCR workers": str(_workers(args.ocr_workers)),
            "Runtime": "local: Orthanc, DynamoDB Local, in-process CPU inference",
            "Studies": f"chest {counts['chest']} instances ({args.chest}), "
                       f"brain {counts['brain']} instances ({args.brain})"}
    Path(args.out).write_text(render(columns, info))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
