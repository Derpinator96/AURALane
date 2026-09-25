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
NO_STUDY = "-"


class FixtureTable(TablePort):
    """In-memory worklist seeded from the fixture file. Audit is append only."""

    def __init__(self, path: Path = WORKLIST):
        rows = json.loads(Path(path).read_text())
        self._worklist = {r["study"]: r for r in rows}
        self._audit: list[dict] = []

    def put_item(self, table, item):
        if table == "audit":
            raise PermissionError("audit is append only; use append_audit")
        if table != "worklist":
            raise KeyError(table)
        self._worklist[item["study"]] = copy.deepcopy(item)

    def get_item(self, table, key):
        if table != "worklist":
            raise KeyError(table)
        row = self._worklist.get(key["study"])
        return copy.deepcopy(row) if row else None

    def query(self, table, **conditions):
        if set(conditions) != {"study"}:
            raise ValueError("query by study only")
        if table == "audit":
            return [copy.deepcopy(e) for e in self._audit if e["study"] == conditions["study"]]
        row = self.get_item(table, conditions)
        return [row] if row else []

    def scan(self, table):
        if table == "audit":
            raise PermissionError("audit is read per study with query, never scanned")
        return [copy.deepcopy(r) for r in self._worklist.values()]

    def append_audit(self, event: AuditEvent) -> None:
        item = event.to_dict()
        item["study"] = event.study or NO_STUDY
        item["event_id"] = f"{event.at}#{uuid.uuid4().hex[:12]}"
        self._audit.append(item)


class FixtureDatastore(DatastorePort):
    """Series lists from the fixture rows; frame URLs to static files the web
    server serves. Read only. Never returns pixels."""

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

    def import_study(self, dicom_paths):
        raise NotImplementedError("fixture datastore is read only")

    def search(self, **filters):
        raise NotImplementedError("fixture datastore is read only")

    def get_frame(self, *a, **k) -> bytes:
        raise NotImplementedError("fixture datastore has no pixel access; use frame_url")


__all__ = ["FixtureTable", "FixtureDatastore"]
