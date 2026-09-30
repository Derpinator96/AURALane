"""Upload your own studies: the files are sorted into studies, each goes through the pipeline and lands
on the uploading reader's own worklist, and the raw files do not stay. On the fixture providers and a
fake pipeline (no Docker, no AWS, no model); the one AWS piece runs against moto."""
import datetime
import json
import os
import random
import time
from types import SimpleNamespace

import numpy as np
import pydicom
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from core import assign, own_uploads
from core.api import create_app
from core.own_uploads import CloudUpload, Uploads, classify, wrap_image
from core.providers.fixture import BLOB, FixtureDatastore, FixtureTable
from core.providers.local import DevAuth, FileBlob, TemplateLLM
from core.types import Verdict
from sim.generator import make_dicom as md

R1, R2 = "radiologist-1@dev.auralane.local", "radiologist-2@dev.auralane.local"
READER = {"id": "a@dev", "name": "A", "pools": ["Chest", "Neuro"]}
CHEST_ONLY = {"id": "c@dev", "name": "C", "pools": ["Chest"]}


def dicom(folder, name, study_uid, modality="CR"):
    """One small DICOM file of the study, with the modality asked for."""
    when = datetime.datetime(2026, 1, 1)
    ident = md.make_identity(random.randrange(10**5), random.Random(), when, False)
    ident["study_uid"] = study_uid
    ds = md.build_instance(np.full((8, 8), 7, np.uint8), 255, ident, when, "a test")
    ds.Modality = modality
    path = folder / name
    ds.save_as(path, enforce_file_format=True)
    return path


def png(folder, name):
    path = folder / name
    Image.fromarray(np.tile(np.arange(64, dtype=np.uint8), (64, 1))).save(path)
    return path


def junk(folder, name):
    path = folder / name
    path.write_bytes(b"\0" * 300)
    return path


def wait(up, upload, owner, seconds=10):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        s = up.status(upload, owner)
        if not s["running"]:
            return s
        time.sleep(0.02)
    raise AssertionError("the upload did not finish")


def fake_pipeline(table, lane="URGENT", status="SCORED", seen=None):
    """ingest_one(paths, model_id=): what the local runtime's pipeline does, to the table."""
    def ingest_one(paths, *, model_id):
        ds = [pydicom.dcmread(p) for p in paths]
        study = str(ds[0].StudyInstanceUID)
        if seen is not None:
            seen.append({"paths": list(paths), "model_id": model_id, "modality": ds[0].Modality,
                         "patient_name": str(ds[0].PatientName)})
        table.put_item("worklist", {"study": study, "lane": lane, "modality": ds[0].Modality,
                                    "patient_id": "PSEUDO-1"})
        return Verdict(ref=SimpleNamespace(study_uid=study), model_id=model_id, status=status, lane=lane)
    return ingest_one


def on_study(table):
    return lambda row, reader, actor: assign.assign_row(table, row, reader, actor, "t")


def receive(up, reader, files):
    """What the API does with each file it is sent."""
    upload = up.open(reader)["upload"]
    for n, f in enumerate(files):
        path, _ = up.begin(upload, reader["id"], n)
        path.write_bytes(f.read_bytes())
        up.commit(upload, reader["id"], n, path.stat().st_size)
    return upload


# -- sorting what arrived ---------------------------------------------------------
def test_classify_makes_one_study_per_uid_and_one_per_image_and_skips_what_is_not_a_study(tmp_path):
    a, b = "1.2.826.0.1.3680043.10.1421.1", "1.2.826.0.1.3680043.10.1421.2"
    files = [dicom(tmp_path, "1", a, "CT"), dicom(tmp_path, "2", a, "CT"), dicom(tmp_path, "3", b, "CR"),
             dicom(tmp_path, "4", a, "SR"),                       # a report object inside the CT study
             png(tmp_path, "5.png"), junk(tmp_path, "6")]
    studies, skipped, problems = classify(files)
    assert problems == [] and skipped == 2
    assert sorted((s["type"], s["modality"], s["kind"], len(s["files"])) for s in studies) == [
        ("chest", "CR", "dicom", 1), ("chest", "CR", "image", 1), ("ct", "CT", "dicom", 2)]


def test_a_modality_no_model_reads_is_refused_naming_the_modality_and_nothing_else(tmp_path):
    study = "1.2.826.0.1.3680043.10.1421.3"
    studies, _, problems = classify([dicom(tmp_path, "1", study, "DX")])
    assert studies == [] and len(problems) == 1
    assert "DX" in problems[0] and "CR" in problems[0] and "CT" in problems[0] and "MR" in problems[0]
    assert classify([junk(tmp_path, "x")])[2] == ["none of the files is a DICOM image or a PNG or JPEG"]


def test_an_image_becomes_a_cr_study_that_carries_no_patient_and_no_claim_about_burned_in_text(tmp_path):
    out = wrap_image(png(tmp_path, "scan.png"), tmp_path / "out.dcm")
    ds = pydicom.dcmread(out)
    assert ds.Modality == "CR" and ds.ViewPosition == "PA" and (ds.Rows, ds.Columns) == (64, 64)
    # No name, birth date, sex or referrer: an image is not a record of a person. The identifier is only
    # what the pseudonym map needs, and is not the corpus generator's placeholder patient.
    assert str(ds.PatientName) == "" and str(ds.PatientBirthDate) == "" and str(ds.PatientSex) == ""
    assert str(ds.ReferringPhysicianName) == "" and str(ds.PatientID).startswith("UPLOAD-")
    assert "SIM" not in str(ds.PatientID) and "SIM^" not in str(ds)
    assert "BurnedInAnnotation" not in ds          # it is not known, so it is not said
    assert "NIH" not in ds.DerivationDescription and "scan" not in str(ds)   # no file name, no NIH claim
    assert np.array_equal(ds.pixel_array, np.tile(np.arange(64, dtype=np.uint8), (64, 1)))


# -- the run ------------------------------------------------------------------------
def test_each_study_runs_the_pipeline_lands_on_the_uploaders_worklist_and_the_raw_files_go(tmp_path):
    table, seen = FixtureTable(), []
    up = Uploads(table, "local", ingest_one=fake_pipeline(table, seen=seen), on_study=on_study(table),
                 spool=tmp_path / "spool")
    a, b = "1.2.826.0.1.3680043.10.1421.4", "1.2.826.0.1.3680043.10.1421.5"
    src = tmp_path / "src"
    src.mkdir()
    upload = receive(up, READER, [dicom(src, "1", a, "CT"), dicom(src, "2", a, "CT"),
                                  dicom(src, "3", b, "CR"), png(src, "4.png")])
    state = up.submit(upload, READER["id"], "actor")
    assert state["state"] == "submitted" and [i["status"] for i in state["items"]] == ["queued"] * 3
    done = wait(up, upload, READER["id"])

    assert sorted((i["type"], i["status"], i["lane"], i["patient_id"]) for i in done["items"]) == [
        ("chest", "done", "URGENT", "PSEUDO-1"), ("chest", "done", "URGENT", "PSEUDO-1"),
        ("ct", "done", "URGENT", "PSEUDO-1")]
    assert sorted(s["model_id"] for s in seen) == ["ct-ich-vit-v1", "cxr-densenet-v1", "cxr-densenet-v1"]
    rows = table.scan("worklist")
    mine = [r for r in rows if r.get("assigned_to") == READER["id"]]
    assert len(mine) == 3 and all(r["assigned_name"] == "A" for r in mine)
    # What reached the pipeline for the wrapped image carried no name at all.
    assert next(s for s in seen if s["paths"][0].name.startswith("image"))["patient_name"] == ""
    # Nothing raw is left, and the status carries no file name or path.
    assert not (tmp_path / "spool" / upload).exists()
    assert "_files" not in json.dumps(done) and str(tmp_path) not in json.dumps(done)


def test_a_study_the_pipeline_fails_is_still_assigned_and_says_why(tmp_path):
    table = FixtureTable()
    up = Uploads(table, "local", ingest_one=fake_pipeline(table, lane="FAILED", status="FAILED"),
                 on_study=on_study(table), spool=tmp_path / "spool")
    src = tmp_path / "src"
    src.mkdir()
    upload = receive(up, READER, [png(src, "a.png")])
    up.submit(upload, READER["id"], "actor")
    item = wait(up, upload, READER["id"])["items"][0]
    assert (item["status"], item["lane"]) == ("failed", "FAILED")
    assert any(r.get("assigned_to") == READER["id"] for r in table.scan("worklist"))


def test_an_exception_in_the_pipeline_fails_that_study_only(tmp_path):
    table = FixtureTable()
    good = fake_pipeline(table)

    def ingest_one(paths, *, model_id):
        if model_id.startswith("ct"):
            raise RuntimeError("the model did not load")
        return good(paths, model_id=model_id)
    up = Uploads(table, "local", ingest_one=ingest_one, on_study=on_study(table), spool=tmp_path / "spool")
    src = tmp_path / "src"
    src.mkdir()
    upload = receive(up, READER, [dicom(src, "1", "1.2.826.0.1.3680043.10.1421.6", "CT"), png(src, "2.png")])
    up.submit(upload, READER["id"], "actor")
    by_type = {i["type"]: i for i in wait(up, upload, READER["id"])["items"]}
    assert by_type["ct"]["status"] == "failed" and "did not load" in by_type["ct"]["error"]
    assert by_type["chest"]["status"] == "done"


def test_a_pool_the_reader_does_not_read_is_refused_before_anything_runs(tmp_path):
    table, seen = FixtureTable(), []
    up = Uploads(table, "local", ingest_one=fake_pipeline(table, seen=seen), spool=tmp_path / "spool")
    src = tmp_path / "src"
    src.mkdir()
    upload = receive(up, CHEST_ONLY, [dicom(src, "1", "1.2.826.0.1.3680043.10.1421.7", "CT")])
    with pytest.raises(ValueError, match="Neuro pool"):
        up.submit(upload, CHEST_ONLY["id"], "actor")
    assert seen == [] and up.status(upload, CHEST_ONLY["id"])["state"] == "open"


def test_an_upload_belongs_to_the_reader_who_opened_it(tmp_path):
    up = Uploads(FixtureTable(), "local", ingest_one=lambda *a, **k: None, spool=tmp_path / "spool")
    upload = up.open(READER)["upload"]
    for call in (lambda: up.status(upload, "other@dev"), lambda: up.begin(upload, "other@dev", 0),
                 lambda: up.discard(upload, "other@dev")):
        with pytest.raises(KeyError):
            call()


def test_limits_hold_and_a_discarded_upload_leaves_nothing(tmp_path, monkeypatch):
    up = Uploads(FixtureTable(), "local", ingest_one=lambda *a, **k: None, spool=tmp_path / "spool")
    upload = up.open(READER)["upload"]
    path, room = up.begin(upload, READER["id"], 0)
    assert room == own_uploads.MAX_FILE_MB * 2**20
    with pytest.raises(ValueError):
        up.begin(upload, READER["id"], own_uploads.MAX_FILES)
    path.write_bytes(b"x")
    up.commit(upload, READER["id"], 0, 1)
    monkeypatch.setattr(own_uploads, "MAX_TOTAL_MB", 0)
    with pytest.raises(ValueError, match="MB in one upload"):
        up.begin(upload, READER["id"], 1)
    monkeypatch.undo()
    for _ in range(own_uploads.OPEN_PER_READER - 1):
        up.open(READER)
    with pytest.raises(RuntimeError, match="already open"):
        up.open(READER)
    up.discard(upload, READER["id"])
    assert not (tmp_path / "spool" / upload).exists()
    with pytest.raises(KeyError):
        up.status(upload, READER["id"])


def test_raw_files_left_by_a_process_that_died_are_removed_at_start(tmp_path):
    (tmp_path / "spool" / "old").mkdir(parents=True)
    (tmp_path / "spool" / "old" / "00000.part").write_bytes(b"raw")
    Uploads(FixtureTable(), "local", spool=tmp_path / "spool")
    assert not (tmp_path / "spool" / "old").exists()


def test_the_fixture_preview_says_why_it_cannot_upload():
    from core.run import _uploads
    up = _uploads({"runtime": "fixture", "table": FixtureTable()})
    assert up.info()["available"] is False and "no pipeline" in up.info()["reason"]
    with pytest.raises(RuntimeError):
        up.open(READER)


# -- the API ------------------------------------------------------------------------
@pytest.fixture
def api(tmp_path):
    auth = DevAuth(secret=os.urandom(32).hex(), password=os.urandom(8).hex())
    table = FixtureTable()
    up = Uploads(table, "local", ingest_one=fake_pipeline(table), on_study=on_study(table),
                 spool=tmp_path / "spool")
    p = {"runtime": "fixture", "blob": FileBlob(BLOB, url_base="/api/blob"),
         "datastore": FixtureDatastore(table), "table": table, "auth": auth, "llm": TemplateLLM(),
         "worklist_scope": "own", "uploads": up}
    client = TestClient(create_app(p))
    client.h = lambda user: {"Authorization": f"Bearer {auth.issue(user)}"}
    client.up, client.table, client.src = up, table, tmp_path
    return client


def put(api, upload, n, data, who="radiologist-1"):
    return api.post(f"/api/uploads/{upload}/files/{n}", content=data,
                    headers={**api.h(who), "Content-Type": "application/octet-stream"})


def test_upload_through_the_api_end_to_end(api):
    h = api.h("radiologist-1")
    info = api.get("/api/uploads", headers=h).json()
    assert info["available"] is True and info["limits"]["files"] == own_uploads.MAX_FILES
    assert info["pools"] == ["Chest", "Neuro"] and len(info["accepts"]) == 2

    upload = api.post("/api/uploads", headers=h).json()["upload"]
    study = "1.2.826.0.1.3680043.10.1421.8"
    data = [dicom(api.src, f"{i}.dcm", study, "CT").read_bytes() for i in range(3)]
    for n, d in enumerate(data):
        r = put(api, upload, n, d)
        assert r.status_code == 201 and r.json()["files"] == n + 1
    assert put(api, upload, 1, data[1]).json()["files"] == 3          # the same n replaces

    state = api.post(f"/api/uploads/{upload}/submit", headers=h)
    assert state.status_code == 202 and state.json()["items"][0]["files"] == 3
    end = time.monotonic() + 10
    while api.get(f"/api/uploads/{upload}", headers=h).json()["running"] and time.monotonic() < end:
        time.sleep(0.02)
    done = api.get(f"/api/uploads/{upload}", headers=h).json()
    assert [(i["status"], i["type"]) for i in done["items"]] == [("done", "ct")]

    # On the uploader's worklist, and only there.
    mine = [s["study"] for s in api.get("/api/worklist", headers=h).json()["studies"]]
    assert done["items"][0]["study"] in mine
    assert api.get("/api/worklist", headers=api.h("radiologist-2")).json()["studies"] == []

    # Audited with counts, and neither a file name nor an identifier.
    events = [e for e in api.table.query("audit", study="-") if e["action"] == "upload_studies"]
    assert len(events) == 1 and events[0]["actor"] == R1
    assert events[0]["detail"] == {"upload": upload, "files": 3, "studies": 1, "skipped": 0,
                                   "types": {"ct": 1}}


def test_another_reader_cannot_see_send_to_or_submit_someone_elses_upload(api):
    upload = api.post("/api/uploads", headers=api.h("radiologist-1")).json()["upload"]
    h2 = api.h("radiologist-2")
    assert api.get(f"/api/uploads/{upload}", headers=h2).status_code == 404
    assert put(api, upload, 0, b"x", who="radiologist-2").status_code == 404
    assert api.post(f"/api/uploads/{upload}/submit", headers=h2).status_code == 404
    assert api.delete(f"/api/uploads/{upload}", headers=h2).status_code == 404
    assert api.get("/api/uploads").status_code == 401


def test_the_api_refuses_an_empty_file_a_big_one_and_a_submit_with_nothing_or_twice(api, monkeypatch):
    h = api.h("radiologist-1")
    upload = api.post("/api/uploads", headers=h).json()["upload"]
    assert api.post(f"/api/uploads/{upload}/submit", headers=h).status_code == 400      # no files
    assert put(api, upload, 0, b"").status_code == 400
    monkeypatch.setattr(own_uploads, "MAX_FILE_MB", 1)
    assert put(api, upload, 0, b"\0" * (2 * 2**20)).status_code == 413
    assert api.up.status(upload, R1)["files"] == 0                                      # nothing kept
    monkeypatch.undo()
    assert put(api, upload, 0, png(api.src, "a.png").read_bytes()).status_code == 201
    assert api.post(f"/api/uploads/{upload}/submit", headers=h).status_code == 202
    assert api.post(f"/api/uploads/{upload}/submit", headers=h).status_code == 400      # twice
    assert put(api, upload, 1, b"x").status_code == 409                                 # after submit


def test_a_bad_upload_is_refused_whole_with_the_reason(api):
    h = api.h("radiologist-1")
    upload = api.post("/api/uploads", headers=h).json()["upload"]
    put(api, upload, 0, dicom(api.src, "1", "1.2.826.0.1.3680043.10.1421.9", "DX").read_bytes())
    r = api.post(f"/api/uploads/{upload}/submit", headers=h)
    assert r.status_code == 400 and "DX" in r.json()["detail"]
    assert api.delete(f"/api/uploads/{upload}", headers=h).status_code == 200


def test_the_fixture_runtime_reports_uploads_unavailable_not_broken():
    auth = DevAuth(secret=os.urandom(32).hex(), password=os.urandom(8).hex())
    table = FixtureTable()
    from core.run import _uploads
    p = {"runtime": "fixture", "blob": FileBlob(BLOB, url_base="/api/blob"),
         "datastore": FixtureDatastore(table), "table": table, "auth": auth, "llm": TemplateLLM()}
    p["uploads"] = _uploads(p)
    c = TestClient(create_app(p))
    h = {"Authorization": f"Bearer {auth.issue('radiologist-1')}"}
    assert c.get("/api/uploads", headers=h).json()["available"] is False
    assert c.post("/api/uploads", headers=h).status_code == 409
    p2 = TestClient(create_app({k: v for k, v in p.items() if k != "uploads"}))
    assert p2.get("/api/uploads", headers=h).json()["available"] is False


# -- AWS ------------------------------------------------------------------------------
def test_on_aws_the_files_go_to_upload_with_a_manifest_and_the_tasks_result_comes_back(monkeypatch, tmp_path):
    moto = pytest.importorskip("moto")
    import boto3
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(k, "testing")
    with moto.mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="bkt")
        files = [dicom(tmp_path, f"{i}.dcm", "1.2.826.0.1.3680043.10.1421.10", "MR") for i in range(2)]
        item = {"modality": "MR"}
        s3.put_object(Bucket="bkt", Key="intake/own-abc/000.json", Body=json.dumps(
            {"status": "SCORED", "lane": "CRITICAL", "study": "1.2.826.0.1.3680043.10.1422.1"}).encode())
        seen = {}
        v = CloudUpload(s3, "bkt", site_state="Kerala", poll_s=0.01)(
            files, item, "abc", 0, lambda **f: seen.update(f))
        assert (v.status, v.lane, v.study) == ("SCORED", "CRITICAL", "1.2.826.0.1.3680043.10.1422.1")
        assert seen == {"status": "running"}
        manifest = json.loads(s3.get_object(Bucket="bkt", Key="upload/own-abc/000/_ready.json")["Body"].read())
        assert len(manifest["keys"]) == 2 and manifest["modality"] == "MR"
        assert manifest["site_state"] == "Kerala" and "predeidentified" not in manifest   # the task cleans it

        # No result in time: the error says where to look.
        with pytest.raises(TimeoutError, match="IngestTask"):
            CloudUpload(s3, "bkt", timeout_s=0.05, poll_s=0.01)(files, item, "xyz", 0, lambda **f: None)
