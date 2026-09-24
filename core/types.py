"""Shapes shared by ports, providers, adapters and the pipeline.

Nothing here is provider specific. Both datastore providers must produce an
identical StudyMeta for the same study; tests/test_datastore_contract.py holds
them to it.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class StudyRef:
    """A study as the datastore knows it.

    study_uid is the DICOM StudyInstanceUID (after de-identification remapping).
    datastore_id is whatever handle the provider uses to address the study: the
    Orthanc study id locally, the HealthImaging ImageSetID on AWS. They are not
    the same value and code must never substitute one for the other.
    """
    study_uid: str
    datastore_id: str


@dataclass(frozen=True)
class SeriesMeta:
    series_uid: str
    number: Optional[int]
    description: str
    instance_count: int
    instance_uids: tuple[str, ...]       # ordered by InstanceNumber


@dataclass(frozen=True)
class StudyMeta:
    ref: StudyRef
    modality: str
    study_date: str                      # DICOM DA, YYYYMMDD
    study_time: str                      # DICOM TM, as stored
    series: tuple[SeriesMeta, ...]       # ordered by SeriesNumber
    patient_id: str                      # the pseudonym, never an original ID


@dataclass
class Findings:
    """What every adapter returns and the only thing triage reads.

    findings: {name: signal in [0, 1]}. Empty means the model abstains.
    evidence: explanation artefacts, e.g. a blob key for an overlay PNG.
    meta:     provenance and intermediate values, for audit and display.
    """
    findings: dict[str, float]
    evidence: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        for name, v in self.findings.items():
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"finding {name!r} signal {v} is outside [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Verdict:
    """One study's place in the queue, or the reason it has none.

    status is SCORED when triage ran and FAILED when any pipeline step raised.
    A FAILED study stays visible on the worklist; it does not disappear.
    triage holds triage.score's output unchanged, so the numbers shown are the
    numbers computed.
    """
    ref: Optional[StudyRef]
    model_id: Optional[str]
    status: str                          # "SCORED" | "FAILED"
    lane: str                            # a triage lane, "ABSTAIN" or "FAILED"
    triage: dict[str, Any] = field(default_factory=dict)
    findings: Optional[Findings] = None
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AuditEvent:
    actor: str
    action: str
    study: Optional[str]                 # StudyRef.study_uid when known
    at: str                              # ISO 8601 UTC
    outcome: str                         # "ok" | "failed"
    duration_ms: float
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Principal:
    subject: str
    email: str
    groups: tuple[str, ...]
