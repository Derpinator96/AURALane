"""Smoke tests for the integrate-frontend work: readers and distribution,
simulated ingest, the pipeline view and /metrics, drafts, the 3D volume routes.
One or two per piece, on the fixture providers (no Docker, no AWS)."""
import datetime
import json
import os

import pydicom
import pytest
from fastapi.testclient import TestClient

from core import assign, pipeline_view
from core.api import create_app, overdue
from core.pipeline import check_edge_deid
from core.providers.fixture import BLOB, FixtureDatastore, FixtureTable
from core.providers.local import DevAuth, FileBlob, TemplateLLM
from core.simulate import LocalPool, Simulator, estimate
from core.types import AuditEvent, Verdict

R1, R2 = "radiologist-1@dev.auralane.local", "radiologist-2@dev.auralane.local"


@pytest.fixture
def app(tmp_path):
    auth = DevAuth(secret=os.urandom(32).hex(), password=os.urandom(8).hex())
    table = FixtureTable()
    p = {"runtime": "fixture", "blob": FileBlob(BLOB, url_base="/api/blob"),
         "datastore": FixtureDatastore(table), "table": table, "auth": auth,
         "llm": TemplateLLM()}
    client = TestClient(create_app(p))
    client.h = lambda user: {"Authorization": f"Bearer {auth.issue(user)}"}
    client.p = p
    return client


# -- readers and distribution ------------------------------------------------------
def test_deal_is_round_robin_in_priority_order_and_respects_pools():
    readers = [{"id": "a", "name": "A", "pools": ["Chest", "Neuro"]},
               {"id": "b", "name": "B", "pools": ["Chest", "Neuro"]},
               {"id": "c", "name": "C", "pools": ["Chest"]}]
    rows = ([{"study": f"c{i}", "pool": "Chest", "lane": "CRITICAL"} for i in range(3)]
            + [{"study": f"r{i}", "pool": "Chest", "lane": "ROUTINE"} for i in range(3)]
            + [{"study": "n0", "pool": "Neuro", "lane": "URGENT"}])
    dealt = assign.deal(rows, readers)
    got = {row["study"]: r["id"] for row, r in dealt}
    assert [got[f"c{i}"] for i in range(3)] == ["a", "b", "c"]      # one critical each
    assert got["n0"] in {"a", "b"}                                    # c does not read Neuro
    counts = [sum(1 for v in got.values() if v == x) for x in "abc"]
    assert max(counts) - min(counts) <= 1
    with pytest.raises(LookupError, match="Neuro"):
        assign.deal(rows, readers[2:])


def test_distribute_assigns_audits_and_admin_sees_it(app):
    r = app.post("/api/distribute", json={"readers": [R1, R2]}, headers=app.h("radiologist-1"))
    assert r.status_code == 200, r.text
    per = {x["id"]: x for x in r.json()["readers"]}
    assert abs(per[R1]["studies"] - per[R2]["studies"]) <= 1
    assert abs(per[R1]["critical"] - per[R2]["critical"]) <= 1

    wl = app.get("/api/worklist", headers=app.h("radiologist-1")).json()
    assert wl["me"] == R1 and {x["id"] for x in wl["readers"]} >= {R1, R2}
    assert all(s["assigned_to"] in (R1, R2) for s in wl["studies"])

    a = app.get("/api/admin/assignments", headers=app.h("admin")).json()
    assert sum(x["total"] for x in a["readers"]) == len(wl["studies"])
    study = wl["studies"][0]["study"]
    events = app.p["table"].query("audit", study=study)
    assert any(e["action"] == "assign" for e in events)

    moved = app.post(f"/api/admin/assignments/{study}", json={"reader": R2}, headers=app.h("admin"))
    assert moved.status_code == 200 and moved.json()["assigned_to"] == R2
    assert any(e["action"] == "reassign" for e in app.p["table"].query("audit", study=study))
    # RBAC both ways.
    assert app.get("/api/admin/assignments", headers=app.h("radiologist-1")).status_code == 403
    assert app.post("/api/distribute", json={"readers": [R1]}, headers=app.h("admin")).status_code == 403


def test_critical_turns_overdue_until_its_reader_opens_it(app):
    old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=20)).isoformat()
    row = {"study": "x", "lane": "CRITICAL", "assigned_to": R1, "created_at": old}
    assert overdue(row)
    assert not overdue({**row, "opened_at": "now"})
    assert not overdue({**row, "lane": "URGENT"})
    assert not overdue({**row, "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()})

    crit = next(s for s in app.p["table"].scan("worklist") if s["lane"] == "CRITICAL")
    assign.assign_row(app.p["table"], crit, {"id": R1, "name": "Reader 1"}, "t", old)
    app.p["table"].put_item("worklist", {**app.p["table"].get_item("worklist", {"study": crit["study"]}),
                                         "created_at": old})
    assert app.get("/api/admin/pipeline", headers=app.h("admin")).json()["overdue"]
    app.get(f"/api/studies/{crit['study']}", headers=app.h("radiologist-2"))    # not the assignee
    assert overdue(app.p["table"].get_item("worklist", {"study": crit["study"]}))
    app.get(f"/api/studies/{crit['study']}", headers=app.h("radiologist-1"))
    assert not overdue(app.p["table"].get_item("worklist", {"study": crit["study"]}))
    assert any(e["action"] == "open" for e in app.p["table"].query("audit", study=crit["study"]))


# -- drafts, history, volumes ------------------------------------------------------------
def test_draft_edit_is_saved_and_audited_without_the_text(app):
    study = app.p["table"].scan("worklist")[0]["study"]
    r = app.post(f"/api/studies/{study}/draft", json={"text": "Impression: edited", "reviewed": True},
                 headers=app.h("radiologist-1"))
    assert r.status_code == 200 and r.json()["draft_review"]["reviewed"] is True
    d = app.get(f"/api/studies/{study}", headers=app.h("radiologist-1")).json()
    assert d["draft_review"]["text"] == "Impression: edited" and d["draft"]
    ev = [e for e in app.p["table"].query("audit", study=study) if e["action"] == "draft_reviewed"]
    assert ev and "edited" not in json.dumps(ev)
    mine = app.get("/api/me/history", headers=app.h("radiologist-1")).json()["events"]
    assert {e["actor"] for e in mine} == {R1}
    assert app.get("/api/me/history", headers=app.h("radiologist-2")).json()["total"] == 0


def test_volume_routes_answer_presigned_urls_or_say_there_is_none(app, tmp_path):
    blob = FileBlob(tmp_path / "blob", url_base="/api/blob")
    for key in ("evidence/x/t1c.nii.gz", "evidence/x/segmentation.nii.gz"):
        blob.put(key, b"nifti bytes")
    app.p["blob"] = blob
    table = app.p["table"]
    row = table.scan("worklist")[0]
    table.put_item("worklist", {**row, "evidence": {"volumes": {"T1c": "evidence/x/t1c.nii.gz"},
                                                     "segmentation": "evidence/x/segmentation.nii.gz",
                                                     "volumes_cm3": {"whole_tumour": 10.0}}})
    v = app.get(f"/api/studies/{row['study']}/volume/t1ce", headers=app.h("radiologist")).json()
    assert v["url"].startswith("/api/blob/evidence/x/t1c.nii.gz?") and v["name"] == "t1c.nii.gz"
    assert app.get(f"/api/studies/{row['study']}/segmentation", headers=app.h("radiologist")).json()["url"]
    assert app.get(f"/api/studies/{row['study']}/volume/flair", headers=app.h("radiologist")).status_code == 404
    assert app.get(f"/api/studies/{row['study']}/volume/t1c").status_code == 401


# -- pipeline view and /metrics -----------------------------------------------------------
def _event(action, ms, at, run="r1", **detail):
    return {"action": action, "outcome": "ok", "duration_ms": ms, "at": at,
            "event_id": f"{at}#{action}", "detail": {"run_id": run, **detail}}


def test_pipeline_view_counts_stages_from_audit_events():
    t0 = datetime.datetime(2026, 9, 28, 10, 0, 0, tzinfo=datetime.timezone.utc)
    at = lambda s: (t0 + datetime.timedelta(seconds=s)).isoformat()        # noqa: E731
    run = [_event("receive", 1000, at(1)), _event("deidentify", 500, at(2)),
           _event("import", 3000, at(5), service="AWS HealthImaging"),
           _event("infer", 4000, at(9), service="AWS Lambda"), _event("triage", 10, at(9.5), lane="URGENT"),
           _event("evidence", 20, at(9.6)), _event("persist", 30, at(10)), _event("blob_delete", 5, at(10.1))]
    runs = pipeline_view.runs(run + [{"action": "verdict", "detail": {}, "event_id": "z"}])
    assert list(runs) == ["r1"]
    stages = {s["stage"]: s for s in pipeline_view.stages(runs.values())}
    assert stages["store"]["service"] == "AWS HealthImaging" and stages["store"]["median_ms"] == 3000
    assert stages["regional"]["count"] == 0 and stages["regional"]["median_ms"] is None
    assert pipeline_view.end_to_end_ms(runs["r1"]) == 10100.0
    assert pipeline_view.position(runs["r1"]) == {"stage": "persist", "done": True, "failed": False,
                                                  "lane": "URGENT"}
    text = pipeline_view.prometheus(runs.values(), [{"modality": "CR", "lane": "URGENT"}])
    assert 'auralane_stage_duration_seconds_count{stage="infer",service="AWS Lambda"} 1' in text
    assert 'auralane_worklist_studies{modality="CR",lane="URGENT"} 1' in text


def test_metrics_needs_admin_or_the_token(app, monkeypatch):
    assert app.get("/metrics").status_code == 401
    assert app.get("/metrics", headers=app.h("radiologist")).status_code == 403
    assert app.get("/metrics", headers=app.h("admin")).text.startswith("# HELP")
    monkeypatch.setenv("AURALANE_METRICS_TOKEN", "scrape-" + os.urandom(8).hex())
    p = app.p
    c = TestClient(create_app(p))
    tok = os.environ["AURALANE_METRICS_TOKEN"]
    assert c.get("/metrics", headers={"Authorization": f"Bearer {tok}"}).status_code == 200


# -- simulated ingest ----------------------------------------------------------------------
def _staged(tmp_path, kind, uid, marked=True):
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian
    d = tmp_path / "pool" / kind / uid
    d.mkdir(parents=True)
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.1"
    ds.file_meta.MediaStorageSOPInstanceUID = uid + ".1"
    ds.SOPInstanceUID, ds.StudyInstanceUID = uid + ".1", uid
    if marked:
        ds.PatientIdentityRemoved, ds.DeidentificationMethod = "YES", "AURALANE edge"
    ds.save_as(d / "a.dcm", enforce_file_format=True)
    (d / "deid_report.json").write_text(json.dumps({uid + ".1": 2}))
    return d


def test_edge_deidentified_studies_are_checked_not_trusted(tmp_path):
    good = pydicom.dcmread(_staged(tmp_path, "chest", "1.2.3") / "a.dcm")
    check_edge_deid([good])
    bad = pydicom.dcmread(_staged(tmp_path, "chest", "1.2.4", marked=False) / "a.dcm")
    with pytest.raises(ValueError, match="not marked de-identified"):
        check_edge_deid([good, bad])


def test_simulate_runs_the_pipeline_per_study_and_assigns_as_each_finishes(tmp_path):
    for uid in ("1.2.3", "1.2.5"):
        _staged(tmp_path, "chest", uid)
    table = FixtureTable()
    seen = []

    def ingest_one(paths, *, edge_reports, model_id, run_id):
        uid = str(pydicom.dcmread(paths[0]).StudyInstanceUID)
        seen.append((uid, edge_reports, model_id))
        table.put_item("worklist", {"study": uid, "lane": "URGENT", "modality": "CR"})
        return Verdict(ref=None, model_id=model_id, status="SCORED", lane="URGENT")

    def on_study(row, reader, actor):
        assign.assign_row(table, row, reader, actor, "t")

    sim = Simulator(LocalPool(tmp_path / "pool"), ingest_one, table, "local", on_study=on_study)
    readers = [{"id": "a", "name": "A", "pools": ["Chest"]}, {"id": "b", "name": "B", "pools": ["Chest"]}]
    with pytest.raises(ValueError, match="Neuro"):
        sim.start({"chest": 0, "brain": 1, "ct": 0}, readers, "r")
    b = sim.start({"chest": 2, "brain": 0, "ct": 0}, readers, "r", seed=1)
    for _ in range(200):
        b = sim.status(b["batch"])
        if not b["running"]:
            break
        import time
        time.sleep(0.02)
    assert [i["status"] for i in b["items"]] == ["done", "done"]
    assert sorted(i["assigned_to"] for i in b["items"]) == ["a", "b"]
    assert all(m == "cxr-densenet-v1" and r for _, r, m in seen)
    assert any(e["action"] == "receive" for e in table.query("audit", study="1.2.3"))


def test_simulate_estimate_labels_every_line_and_fixture_says_why_not():
    e = estimate({"chest": 3, "brain": 1, "ct": 1}, "aws")
    assert {l["type"] for l in e["lines"]} == {"chest", "brain", "ct"}
    assert all(l["basis"] for l in e["lines"]) and e["total_usd"] == round(sum(l["usd"] for l in e["lines"]), 4)
    assert estimate({"chest": 3}, "local")["total_usd"] == 0.0
    from core.run import _simulator
    info = _simulator({"runtime": "fixture", "table": FixtureTable()}).info()
    assert info["available"] is False and "no pipeline" in info["reason"]
