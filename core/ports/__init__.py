"""Abstract ports. The pipeline sees only these.

No AWS SDK and no provider is imported anywhere in this package.
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from core.types import Findings, Principal, StudyMeta, StudyRef, AuditEvent  # noqa: F401


class DatastorePort(ABC):
    """DICOM store with a DICOMweb-shaped surface.

    frame_url exists so the browser fetches pixels from the datastore directly.
    The API never proxies pixel data.
    """

    @abstractmethod
    def import_study(self, dicom_paths: list[Path]) -> StudyRef: ...

    @abstractmethod
    def search(self, **filters) -> list[StudyMeta]:
        """Filters: modality, study_date (YYYYMMDD), study_uid."""

    @abstractmethod
    def get_metadata(self, ref: StudyRef) -> StudyMeta: ...

    @abstractmethod
    def get_frame(self, ref: StudyRef, series_uid: str, instance_uid: str,
                  frame: int = 1) -> bytes:
        """Frame pixel bytes as stored (may be compressed)."""

    @abstractmethod
    def frame_url(self, ref: StudyRef, series_uid: str, instance_uid: str,
                  frame: int = 1, ttl: int = 300) -> str: ...


class BlobPort(ABC):
    @abstractmethod
    def put(self, key: str, data: bytes) -> str: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def presigned_url(self, key: str, ttl: int = 300) -> str: ...


class TablePort(ABC):
    """Worklist rows and the audit trail.

    Deliberately no update or delete for audit. Audit is append only.
    """

    @abstractmethod
    def put_item(self, table: str, item: dict[str, Any]) -> None: ...

    @abstractmethod
    def get_item(self, table: str, key: dict[str, Any]) -> dict[str, Any] | None: ...

    @abstractmethod
    def query(self, table: str, **conditions) -> list[dict[str, Any]]:
        """Equality match on the table's partition key, e.g. study="1.2.3"."""

    @abstractmethod
    def append_audit(self, event: AuditEvent) -> None: ...


class AuthPort(ABC):
    @abstractmethod
    def verify(self, token: str) -> Principal: ...


class InferencePort(ABC):
    @abstractmethod
    def score(self, ref: StudyRef, model_cfg: dict[str, Any], **inputs) -> Any:
        """Raw model output, in whatever shape model_cfg["output_type"] names."""


class LLMPort(ABC):
    @abstractmethod
    def draft(self, context: dict[str, Any]) -> str: ...


__all__ = ["DatastorePort", "BlobPort", "TablePort", "AuthPort", "InferencePort",
           "LLMPort"]
