"""A structured radiology report draft, written from stored findings only.

No language model: every sentence is a fixed phrase filled with a number or a
name the pipeline stored for the study. The reading radiologist confirms,
edits or replaces all of it.

    EXAMINATION   what was read
    TECHNIQUE     what the system did with it (from the study's own record)
    COMPARISON    "None available."
    FINDINGS      each finding in words, graded from its signal:
                    below 0.35    "no convincing evidence of"
                    0.35 to 0.60  "possible"
                    above 0.60    "findings suggestive of"
                  brain MR adds the measured volumes (mL) and the eccentricity,
                  head CT the dominant subtype and its likelihood
    IMPRESSION    the top findings by weighted value (signal x urgency, the
                  quantity the queue is ordered by), one line each
    TRIAGE NOTE   the lane and its reading clock, the driving finding and, for
                  an abstained study, why no lane was assigned

NON-DIAGNOSTIC; DECISION SUPPORT ONLY.
"""
from __future__ import annotations

from typing import Any

LOW, HIGH = 0.35, 0.60          # the grading bands; also the abstention band (triage.py)
IMPRESSION_LINES = 3

LANE_NAME = {"CRITICAL": "Critical", "URGENT": "Urgent", "EXPEDITED": "Expedited",
             "ROUTINE": "Routine", "ABSTAIN": "Needs human triage", "FAILED": "Pipeline failed",
             "REPEAT": "Repeat imaging"}

PHRASE = {"mass_effect": "mass effect", "enhancing_tumor": "enhancing tumour",
          "tumor_burden": "tumour burden", "edema_volume": "peritumoral edema"}

DISCLAIMER = ("NON-DIAGNOSTIC; DECISION SUPPORT ONLY. Assembled from the system's structured "
              "output. The reading radiologist confirms, edits or replaces every statement.")


def phrase(name: str) -> str:
    return PHRASE.get(name) or name.replace("_", " ").lower()


def grade(signal: float) -> str:
    if signal < LOW:
        return "no convincing evidence of"
    if signal <= HIGH:
        return "possible"
    return "findings suggestive of"


def sentence(name: str, signal: float) -> str:
    g = grade(signal)
    text = f"{g} {phrase(name)}"
    return text[0].upper() + text[1:]


def _examination(modality: str, exam: str, evidence: dict) -> tuple[str, str]:
    if modality == "MR":
        return ("MRI of the brain, four sequences (T1 contrast enhanced, T1, T2, FLAIR).",
                "Brain MRI read as four model channels; the segmentation is the model's own.")
    if modality == "CT":
        n = (evidence.get("ct") or {}).get("n_slices")
        return ("CT of the head, non-contrast.",
                "Axial non-contrast head CT" + (f", {n} slices scored" if n else "") + ".")
    return ("Chest radiograph.",
            "Chest radiograph (de-identified copy). Each finding is scored against its own "
            "operating point, not a flat threshold.")


def _findings_lines(ctx: dict) -> list[str]:
    modality, ev = ctx.get("modality") or "CR", ctx.get("evidence") or {}
    signals: dict[str, float] = ctx.get("findings") or {}
    lines: list[str] = []
    if modality == "MR":
        vol = ev.get("volumes_cm3")
        if vol:
            lines.append(
                f"Segmentation: whole tumour {vol['whole_tumour']:.1f} mL, tumour core "
                f"{vol['tumour_core']:.1f} mL, enhancing tumour {vol['enhancing']:.1f} mL, "
                f"peritumoral edema {vol['edema']:.1f} mL (the model's own mask).")
        if ev.get("eccentricity") is not None:
            lines.append(f"Lesion eccentricity from the midline {ev['eccentricity']:.2f} "
                         f"(0 central, 1 at the edge of the volume).")
    elif modality == "CT":
        ct = ev.get("ct") or {}
        if ct.get("dominant_subtype"):
            likelihood = ct.get("raw_score")
            lines.append(
                f"Dominant subtype {ct['dominant_subtype']} hemorrhage"
                + (f", study likelihood {likelihood:.2f}" if likelihood is not None else "")
                + (f", on slice {ct['top_slice_index'] + 1} of {ct['n_slices']}"
                   if ct.get("n_slices") and ct.get("top_slice_index") is not None else "") + ".")
            others = {k: v for k, v in (ct.get("subtype_scores") or {}).items()
                      if k != ct["dominant_subtype"]}
            if others:
                lines.append("Other subtypes, aggregated probability: " + ", ".join(
                    f"{k} {v:.2f}" for k, v in sorted(others.items(), key=lambda kv: -kv[1])) + ".")
    if not signals:
        lines.append("No finding was scored for this study (see the triage note).")
        return lines
    ordered = sorted(signals.items(), key=lambda kv: -kv[1])
    flagged = [(k, v) for k, v in ordered if v >= LOW]
    quiet = [k for k, v in ordered if v < LOW]
    for k, v in flagged:
        lines.append(f"{sentence(k, v)} (signal {v:.2f}).")
    if quiet:
        lines.append("No convincing evidence of " + ", ".join(phrase(k) for k in quiet) + ".")
    return lines


def _impression_lines(ctx: dict) -> list[str]:
    signals: dict[str, float] = ctx.get("findings") or {}
    if not signals:
        return ["No finding could be scored. See the triage note."]
    urgency = ctx.get("urgency") or {}
    weighted = {k: v * urgency.get(k, 0.15) for k, v in signals.items()}
    top = sorted(weighted, key=lambda k: -weighted[k])[:IMPRESSION_LINES]
    return [f"{i}. {sentence(k, signals[k])} (signal {signals[k]:.2f}, weighted {weighted[k]:.2f})."
            for i, k in enumerate(top, 1)]


def _triage_lines(ctx: dict) -> list[str]:
    t = ctx.get("triage") or {}
    lane = ctx.get("lane") or "unknown"
    clock = ctx.get("clock")
    human = ctx.get("human_lane")
    lines = []
    if human:
        lines.append(f"Queue lane: {LANE_NAME.get(lane, lane)}."
                     + (f" Reading clock: {clock}." if clock else "")
                     + f" Lane set by {human.get('by_name') or human.get('by')}: {human.get('reason')}.")
        lines.append("The system had abstained: " + (t.get("reason") or "no lane assigned") + ".")
    elif t.get("abstained") or lane == "ABSTAIN":
        lines.append("Queue lane: Needs human triage. The system did not assign a lane.")
        why = t.get("reason") or "no reason recorded"
        driver = t.get("driver")
        if driver and t.get("signal") is not None and LOW <= t["signal"] <= HIGH:
            why = (f"the driving finding, {phrase(driver)}, has a signal of {t['signal']:.2f}, inside "
                   f"the {LOW:.2f} to {HIGH:.2f} band where the model does not commit")
        lines.append(f"Reason: {why}.")
    else:
        lines.append(f"Queue lane: {LANE_NAME.get(lane, lane)}."
                     + (f" Reading clock: {clock}." if clock else ""))
        if t.get("driver"):
            lines.append(f"Driving finding: {phrase(t['driver'])} (signal {t.get('signal')}"
                         + (f", acuity {t['acuity']}" if t.get("acuity") is not None else "") + ").")
    return lines


def build(ctx: dict[str, Any]) -> str:
    modality = ctx.get("modality") or "CR"
    exam, technique = _examination(modality, ctx.get("exam") or "", ctx.get("evidence") or {})
    parts = [
        "NON-DIAGNOSTIC; DECISION SUPPORT ONLY. DRAFT FOR RADIOLOGIST REVIEW.",
        f"Study: {ctx.get('study', 'unknown')}   Model: {ctx.get('model_id', 'unknown')}",
        "",
        "EXAMINATION", exam, "",
        "TECHNIQUE", technique, "",
        "COMPARISON", "None available.", "",
        "FINDINGS", *_findings_lines(ctx), "",
        "IMPRESSION", *_impression_lines(ctx), "",
        "TRIAGE NOTE", *_triage_lines(ctx), "",
        DISCLAIMER,
    ]
    return "\n".join(parts)
