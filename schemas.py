"""AURALane data contracts.

Canonical schema definitions for every object that flows through the platform.
Used by the triage engine, modality adapters, API layer and frontend.

These are plain dataclasses with an .to_dict() helper so they serialise to JSON
without pulling in Pydantic (which the existing project does not use directly
in its data layer).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


# ── Inference ────────────────────────────────────────────────────────────

@dataclass
class Finding:
    """A single pathology finding from a modality-specific model."""
    name: str
    raw_probability: float
    calibrated_probability: Optional[float] = None
    signal: Optional[float] = None
    urgency_weight: Optional[float] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}


@dataclass
class InferenceResult:
    """Normalised output from any modality adapter.

    Every adapter — CXR, CT, MRI — must produce one of these.  The triage
    engine consumes this schema exclusively; it never touches model-specific
    Python objects.
    """
    study_id: str
    modality: str                    # "CXR" | "CT" | "MRI"
    body_part: str                   # "CHEST" | "HEAD" | "BRAIN"
    model_name: str
    model_version: str
    findings: list[Finding]
    status: str = "SUCCESS"          # "SUCCESS" | "PROTOTYPE" | "EXPERIMENTAL" | "ERROR"
    inference_ms: Optional[int] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["findings"] = [f.to_dict() for f in self.findings]
        return {k: v for k, v in d.items() if v is not None}

    @property
    def preds_dict(self) -> dict[str, float]:
        """Convenience: {finding_name: raw_probability} for the triage engine."""
        return {f.name: f.raw_probability for f in self.findings}


# ── Triage ───────────────────────────────────────────────────────────────

@dataclass
class TriageResult:
    """Output of the common triage engine for a single study."""
    study_id: str
    modality: str
    acuity: float
    lane: str                        # "CRITICAL" | "URGENT" | "EXPEDITED" | "ROUTINE" | "ABSTAIN"
    sla: str
    sla_minutes: Optional[int]
    abstained: bool
    driver: str
    confidence: float
    signal: float
    raw: float
    top_findings: list[dict]
    model_status: str = "LIVE"       # "LIVE" | "PROTOTYPE" | "EXPERIMENTAL"

    def to_dict(self) -> dict:
        return asdict(self)


# ── Study ────────────────────────────────────────────────────────────────

@dataclass
class Study:
    """A medical imaging study entering the platform."""
    study_id: str
    patient_id: str
    modality: str                    # "CXR" | "CT" | "MRI"
    body_part: str                   # "CHEST" | "HEAD" | "BRAIN"
    filename: str
    image_path: str
    arrival_index: int = 0
    arrival_minute: float = 0.0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ── Worklist ─────────────────────────────────────────────────────────────

@dataclass
class WorklistItem:
    """Composite of Study + TriageResult, ready for the frontend worklist."""
    # Study fields
    study_id: str
    patient_id: str
    modality: str
    body_part: str
    filename: str
    image_path: str
    arrival_index: int
    arrival_minute: float
    # Triage fields
    acuity: float
    lane: str
    sla: str
    sla_minutes: Optional[int]
    abstained: bool
    driver: str
    confidence: float
    signal: float
    raw: float
    top_findings: list[dict]
    model_status: str = "LIVE"
    # Human review state
    human_lane: Optional[str] = None
    review_status: Optional[str] = None   # "AGREE" | "DISAGREE" | "OVERRIDE"
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}

    @classmethod
    def from_study_and_triage(cls, study: Study, triage: TriageResult) -> WorklistItem:
        return cls(
            study_id=study.study_id,
            patient_id=study.patient_id,
            modality=study.modality,
            body_part=study.body_part,
            filename=study.filename,
            image_path=study.image_path,
            arrival_index=study.arrival_index,
            arrival_minute=study.arrival_minute,
            acuity=triage.acuity,
            lane=triage.lane,
            sla=triage.sla,
            sla_minutes=triage.sla_minutes,
            abstained=triage.abstained,
            driver=triage.driver,
            confidence=triage.confidence,
            signal=triage.signal,
            raw=triage.raw,
            top_findings=triage.top_findings,
            model_status=triage.model_status,
        )


# ── Human Review ─────────────────────────────────────────────────────────

@dataclass
class HumanReview:
    """A radiologist's response to an AI triage decision."""
    study_id: str
    ai_lane: str
    human_lane: str
    action: str                      # "AGREE" | "DISAGREE" | "OVERRIDE"
    reason: Optional[str] = None
    reviewer: str = "anonymous"
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return asdict(self)


# ── Audit ────────────────────────────────────────────────────────────────

@dataclass
class AuditEvent:
    """An auditable event in the platform lifecycle."""
    event_type: str                  # "STUDY_ARRIVED" | "INFERENCE_COMPLETE" |
                                     # "TRIAGE_COMPLETE" | "HUMAN_REVIEW" |
                                     # "LANE_OVERRIDE" | "STUDY_READ"
    study_id: str
    payload: dict = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return asdict(self)
