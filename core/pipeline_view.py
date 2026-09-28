"""The pipeline view, computed from the audit trail and nothing else.

Every pipeline step writes one audit event with its measured duration and the
service that ran it (core/pipeline.py). This module groups those events by run
and by stage. No number here is estimated: a stage with no events shows no
figure.

Pure functions over event dicts, so the admin screen, GET /metrics and the tests
read the same arithmetic.
"""
from __future__ import annotations

import datetime
import statistics
from collections import Counter, defaultdict
from typing import Any, Iterable

# (key, label, audit actions). The order the pipeline runs them. The transient
# blob copy (blob_put, blob_delete) is in every timeline but not in the flow.
STAGES = [
    ("receive", "Receive", ("receive",)),
    ("deidentify", "De-identify", ("deidentify",)),
    ("store", "Store", ("import",)),
    ("prepare", "Prepare inputs", ("prepare_inputs",)),
    ("infer", "Infer", ("infer",)),
    ("adapt", "Adapt", ("adapt",)),
    ("regional", "Regional prior", ("regional_prior",)),
    ("triage", "Triage", ("triage",)),
    ("evidence", "Evidence", ("evidence",)),
    ("persist", "Persist", ("persist",)),
]
STAGE_OF = {a: key for key, _, actions in STAGES for a in actions}
PIPELINE_ACTIONS = set(STAGE_OF) | {"blob_put", "blob_delete"}
BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600)


def _ts(at: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(at)


def runs(events: Iterable[dict]) -> dict[str, list[dict]]:
    """{run_id: pipeline events in order}. Events without a run id (verdicts,
    assignments) are not pipeline steps and are left out."""
    out: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        rid = (e.get("detail") or {}).get("run_id")
        if rid and e["action"] in PIPELINE_ACTIONS:
            out[rid].append(e)
    for evs in out.values():
        evs.sort(key=lambda e: e["event_id"])
    return dict(out)


def latest_run(events: Iterable[dict]) -> list[dict]:
    rs = runs(events)
    if not rs:
        return []
    return max(rs.values(), key=lambda evs: evs[-1]["event_id"])


def _service(e: dict) -> str | None:
    d = e.get("detail") or {}
    return d.get("service")


def timeline(events: list[dict]) -> dict[str, Any]:
    """One run, step by step, with its duration and the service that ran it."""
    run = list(events)
    steps = [{"action": e["action"], "stage": STAGE_OF.get(e["action"]),
              "outcome": e["outcome"], "duration_ms": e["duration_ms"], "at": e["at"],
              "service": _service(e),
              "detail": {k: v for k, v in (e.get("detail") or {}).items()
                         if k in ("model_id", "lane", "acuity", "driver", "instances",
                                  "where", "error", "keys", "applied", "series",
                                  "datastore_id", "source")}}
             for e in run]
    return {"run_id": (run[0].get("detail") or {}).get("run_id") if run else None,
            "steps": steps, "end_to_end_ms": end_to_end_ms(run),
            "failed": any(e["outcome"] != "ok" for e in run)}


def end_to_end_ms(run: list[dict]) -> float | None:
    """Wall time from the start of the first step to the end of the last. An
    event's `at` is written when its step ends, so the first step's start is its
    `at` minus its duration."""
    if not run:
        return None
    first, last = run[0], run[-1]
    start = _ts(first["at"]) - datetime.timedelta(milliseconds=first["duration_ms"])
    return round((_ts(last["at"]) - start).total_seconds() * 1000, 1)


def stages(all_runs: Iterable[list[dict]]) -> list[dict[str, Any]]:
    """Per stage: runs that passed through it, failures, median and last
    duration, and the service named by its latest event."""
    by_stage: dict[str, list[dict]] = defaultdict(list)
    for run in all_runs:
        for e in run:
            s = STAGE_OF.get(e["action"])
            if s:
                by_stage[s].append(e)
    out = []
    for key, label, _ in STAGES:
        evs = sorted(by_stage.get(key, []), key=lambda e: e["event_id"])
        ok = [e for e in evs if e["outcome"] == "ok"]
        services = [s for s in (_service(e) for e in evs) if s]
        out.append({"stage": key, "label": label, "count": len(ok),
                    "failed": len(evs) - len(ok),
                    "median_ms": round(statistics.median(e["duration_ms"] for e in ok), 1)
                    if ok else None,
                    "last_ms": round(ok[-1]["duration_ms"], 1) if ok else None,
                    "service": services[-1] if services else None,
                    "services": sorted(set(services))})
    return out


def position(run: list[dict]) -> dict[str, Any]:
    """Where one run is now: the last stage it finished, and whether it ended."""
    if not run:
        return {"stage": None, "done": False, "failed": False}
    staged = [e for e in run if STAGE_OF.get(e["action"])]
    last = staged[-1] if staged else None
    failed = any(e["outcome"] != "ok" for e in run)
    done = any(e["action"] == "blob_delete" for e in run)
    return {"stage": STAGE_OF.get(last["action"]) if last else None,
            "done": done, "failed": failed,
            "lane": next((e["detail"].get("lane") for e in reversed(run)
                          if e["action"] == "triage"), None)}


def totals(rows: list[dict], study_runs: dict[str, list[dict]], day: str) -> dict[str, Any]:
    """Studies that arrived on `day` (UTC, YYYY-MM-DD) by modality and lane, and
    end-to-end median per modality over their latest runs."""
    today = [r for r in rows if (r.get("created_at") or "").startswith(day)]
    by = Counter((r.get("modality") or "?", r["lane"]) for r in today)
    e2e: dict[str, list[float]] = defaultdict(list)
    for r in today:
        ms = end_to_end_ms(study_runs.get(r["study"], []))
        if ms is not None:
            e2e[r.get("modality") or "?"].append(ms)
    return {"day": day, "studies": len(today),
            "by_modality_lane": [{"modality": m, "lane": l, "count": n}
                                 for (m, l), n in sorted(by.items())],
            "end_to_end_median_ms": {m: round(statistics.median(v), 1)
                                     for m, v in sorted(e2e.items())},
            "end_to_end_n": {m: len(v) for m, v in sorted(e2e.items())}}


def _esc(v: str) -> str:
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def prometheus(all_runs: Iterable[list[dict]], rows: list[dict]) -> str:
    """Prometheus text exposition: stage durations as histograms (seconds), and
    worklist studies by modality and lane."""
    samples: dict[tuple[str, str], list[float]] = defaultdict(list)
    for run in all_runs:
        for e in run:
            s = STAGE_OF.get(e["action"])
            if s and e["outcome"] == "ok":
                samples[(s, _service(e) or "unknown")].append(e["duration_ms"] / 1000)
    lines = ["# HELP auralane_stage_duration_seconds Pipeline stage duration, from the audit trail.",
             "# TYPE auralane_stage_duration_seconds histogram"]
    for (stage, svc), vals in sorted(samples.items()):
        lab = f'stage="{_esc(stage)}",service="{_esc(svc)}"'
        for b in BUCKETS:
            lines.append(f'auralane_stage_duration_seconds_bucket{{{lab},le="{b}"}} '
                         f"{sum(v <= b for v in vals)}")
        lines.append(f'auralane_stage_duration_seconds_bucket{{{lab},le="+Inf"}} {len(vals)}')
        lines.append(f"auralane_stage_duration_seconds_sum{{{lab}}} {round(sum(vals), 6)}")
        lines.append(f"auralane_stage_duration_seconds_count{{{lab}}} {len(vals)}")
    lines += ["# HELP auralane_worklist_studies Studies on the worklist, by modality and lane.",
              "# TYPE auralane_worklist_studies gauge"]
    for (m, l), n in sorted(Counter((r.get("modality") or "unknown", r["lane"])
                                    for r in rows).items()):
        lines.append(f'auralane_worklist_studies{{modality="{_esc(m)}",lane="{_esc(l)}"}} {n}')
    return "\n".join(lines) + "\n"
