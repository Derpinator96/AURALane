"""Fixture providers: the web app without the corpus, Docker or AWS.

AURALANE_RUNTIME=fixture serves fixtures/worklist.json (built by
scripts/make_fixtures.py; every number in it traces to scores.json or a
recorded metrics.json, and each row's "source" says which). The API and the
browser use the same ports and routes as the local and AWS runtimes; nothing
outside core/run.py knows which is running.

State is in memory: verdicts and audit events last until the process stops.
"""
from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from typing import Any

from core.ports import DatastorePort, TablePort
from core.types import AuditEvent, SeriesMeta, StudyMeta, StudyRef

ROOT = Path(__file__).resolve().parents[3]
WORKLIST = ROOT / "fixtures" / "worklist.json"
BLOB = ROOT / "fixtures" / "blob"          # Grad-CAM overlays, built by make_fixtures.py
ANNOTATIONS = ROOT / "fixtures" / "annotations.json"
NO_STUDY = "-"


class FixtureTable(TablePort):
    """In-memory worklist seeded from the fixture file. Audit is append only."""

    def __init__(self, path: Path = WORKLIST, annotations_path: Path = ANNOTATIONS):
        rows = json.loads(Path(path).read_text())
        self._worklist = {r["study"]: r for r in rows}
        self._audit: list[dict] = []
        self._annotations_path = Path(annotations_path)
        self._annotations: dict[str, dict] = {}
        if self._annotations_path.exists():
            try:
                anns = json.loads(self._annotations_path.read_text())
                self._annotations = {a.get("annotation_id", a.get("id")): a for a in anns}
            except Exception:
                self._annotations = {}

    def _persist_annotations(self):
        try:
            self._annotations_path.parent.mkdir(parents=True, exist_ok=True)
            self._annotations_path.write_text(json.dumps(list(self._annotations.values()), indent=2))
        except Exception:
            pass

    def put_item(self, table, item):
        if table == "audit":
            raise PermissionError("audit is append only; use append_audit")
        if table == "worklist":
            self._worklist[item["study"]] = copy.deepcopy(item)
        elif table == "annotations":
            ann_id = item.get("annotation_id") or item.get("id")
            if not ann_id:
                raise ValueError("annotation must have annotation_id or id")
            self._annotations[ann_id] = copy.deepcopy(item)
            self._persist_annotations()
        else:
            raise KeyError(table)

    def get_item(self, table, key):
        if table == "worklist":
            row = self._worklist.get(key["study"])
            return copy.deepcopy(row) if row else None
        elif table == "annotations":
            ann_id = key.get("annotation_id") or key.get("id")
            if ann_id:
                item = self._annotations.get(ann_id)
                return copy.deepcopy(item) if item else None
            elif "study" in key:
                for item in self._annotations.values():
                    if item.get("study") == key["study"] or item.get("study_id") == key["study"]:
                        return copy.deepcopy(item)
            return None
        else:
            raise KeyError(table)

    def delete_item(self, table, key):
        if table == "audit":
            raise PermissionError("audit is append only")
        elif table == "annotations":
            ann_id = key.get("annotation_id") or key.get("id")
            if ann_id and ann_id in self._annotations:
                del self._annotations[ann_id]
                self._persist_annotations()
        elif table == "worklist":
            study = key.get("study")
            if study and study in self._worklist:
                del self._worklist[study]
        else:
            raise KeyError(table)

    def query(self, table, **conditions):
        if table == "audit":
            if set(conditions) != {"study"}:
                raise ValueError("query by study only")
            return [copy.deepcopy(e) for e in self._audit if e["study"] == conditions["study"]]
        elif table == "annotations":
            study = conditions.get("study") or conditions.get("study_id")
            if study:
                return [copy.deepcopy(a) for a in self._annotations.values()
                        if a.get("study") == study or a.get("study_id") == study]
            return [copy.deepcopy(a) for a in self._annotations.values()]
        elif table == "worklist":
            if set(conditions) != {"study"}:
                raise ValueError("query by study only")
            row = self.get_item(table, conditions)
            return [row] if row else []
        raise KeyError(table)

    def scan(self, table):
        if table == "audit":
            raise PermissionError("audit is read per study with query, never scanned")
        elif table == "worklist":
            return [copy.deepcopy(r) for r in self._worklist.values()]
        elif table == "annotations":
            return [copy.deepcopy(a) for a in self._annotations.values()]
        raise KeyError(table)

    def append_audit(self, event: AuditEvent) -> None:
        item = event.to_dict()
        item["study"] = event.study or NO_STUDY
        item["event_id"] = f"{event.at}#{uuid.uuid4().hex[:12]}"
        self._audit.append(item)


class FixtureDatastore(DatastorePort):
    """Series lists from the fixture rows; frame URLs to static files the web
    server serves. Read only. Never returns pixels."""

    # Shown in the study viewer. Every word is true of this provider: the chest
    # frame is fixtures' one public sample, and the brain rows have no instances.
    note = ("No DICOM datastore is connected to this preview. Chest studies show one "
            "public sample image, not the study's own, and brain studies have no images "
            "here. The live pipeline, from de-identification through the datastore to "
            "scoring, runs locally.")

    def __init__(self, table: FixtureTable):
        self.table = table

    def get_metadata(self, ref: StudyRef) -> StudyMeta:
        row = self.table.get_item("worklist", {"study": ref.study_uid})
        if row is None:
            raise LookupError(ref.study_uid)
        series = tuple(SeriesMeta(s["series_uid"], s["number"], s["description"],
                                  s["instance_count"], tuple(s["instance_uids"]))
                       for s in row.get("series", []))
        return StudyMeta(ref, row["modality"], row.get("study_date", ""), "", series,
                         row.get("patient_id", ""))

    def frame_url(self, ref, series_uid, instance_uid, frame=1, ttl=300) -> str:
        row = self.table.get_item("worklist", {"study": ref.study_uid}) or {}
        for s in row.get("series", []):
            if s["series_uid"] == series_uid and instance_uid in s["instance_uids"]:
                return s["frame_url"]
        raise LookupError(f"no fixture frame for {series_uid}/{instance_uid}")

    def series_metadata(self, ref, series_uid) -> list[dict]:
        row = self.table.get_item("worklist", {"study": ref.study_uid}) or {}
        for s in row.get("series", []):
            if s["series_uid"] == series_uid:
                return s.get("metadata", [])
        raise LookupError(f"no fixture series {series_uid}")

    def import_study(self, dicom_paths):
        raise NotImplementedError("fixture datastore is read only")

    def search(self, **filters):
        raise NotImplementedError("fixture datastore is read only")

    def get_frame(self, *a, **k) -> bytes:
        raise NotImplementedError("fixture datastore has no pixel access; use frame_url")


__all__ = ["FixtureTable", "FixtureDatastore"]
