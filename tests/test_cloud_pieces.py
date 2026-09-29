"""Smoke tests for the pieces added for the end-to-end AWS path: the regional
prior, the head CT adapter, the aws runtime's variable requirements and the
API's signed frame stream. No AWS call is made (moto)."""
import json
import secrets

import numpy as np
import pytest
from fastapi.testclient import TestClient

import core.run as run
from core import regional
from core.api import create_app
from core.pipeline import _regional
from core.providers.fixture import BLOB, WORKLIST, FixtureDatastore, FixtureTable
from core.providers.local import DevAuth, FileBlob, TemplateLLM
from core.registry import Registry, rank
from core.types import Findings

# Generated per run: no password is written in this repository (as in test_api.py).
DEV_PASSWORD = secrets.token_hex(8)
# Meets Cognito's default policy: upper, lower, digit, symbol, 8 or more.
REQUESTER_PASSWORD = f"Aa1!{secrets.token_urlsafe(12)}"
# Usernames and emails generated too; ".invalid" is reserved so no real
# address can exist on it (RFC 2606).
REQUESTER = f"user-{secrets.token_hex(4)}"
REQUESTER_EMAIL = f"{REQUESTER}@{secrets.token_hex(4)}.invalid"
ACTOR = f"admin-{secrets.token_hex(4)}@{secrets.token_hex(4)}.invalid"


# -- regional prior ----------------------------------------------------------
def test_regional_prior_is_bounded_and_never_overrides_the_image():
    priors = regional.load()
    for state in regional.states(priors):
        adjusted, ev = regional.apply({"Pneumonia": 0.5, "Mass": 0.0, "Edema": 0.7}, state, priors)
        assert all(0.8 <= f["factor"] <= 1.25 for f in ev["factors"].values())
        assert adjusted["Mass"] == 0.0            # nothing from nothing
        assert adjusted["Edema"] == 0.7           # no GBD cause behind it: unchanged
    backed = [f for fs in priors["causes"].values() for f in fs]
    assert len(priors["causes"]) == 4 and len(backed) == 11


def test_regional_prior_switch_off_changes_nothing_and_says_so():
    f = Findings(findings={"Pneumonia": 0.5}, evidence={}, meta={})
    out = _regional(f, regional.RegionalSetting(state="Kerala", enabled=False), {})
    assert out.findings == {"Pneumonia": 0.5}
    assert out.evidence["regional"] == {"state": "Kerala", "applied": False,
                                        "reason": "off (AURALANE_REGIONAL_PRIOR=off)"}
    on = _regional(f, regional.RegionalSetting(state="Kerala", enabled=True), {})
    assert on.evidence["regional"]["factors"]["Pneumonia"]["signal_before"] == 0.5


def test_unknown_state_is_refused(monkeypatch):
    monkeypatch.setenv("AURALANE_SITE_STATE", "Atlantis")
    with pytest.raises(ValueError, match="unknown state"):
        regional.setting()


# -- head CT ------------------------------------------------------------------
@pytest.mark.parametrize("likelihood, lane", [(0.2, "ROUTINE"), (0.6, "ABSTAIN"), (0.95, "CRITICAL")])
def test_ct_adapter_converts_her_scale_and_our_triage_assigns_the_lane(likelihood, lane):
    reg = Registry()
    entry = reg.get("ct-ich-vit-v1")
    assert entry["reading_pool"] == "Neuro" and entry["runtime"] == "sagemaker-async"
    out = {"raw_score": likelihood, "study_score": likelihood, "dominant_subtype": "epidural",
           "k_used": 3, "n_slices": 9, "top_slice_index": 4, "subtype_scores": {}}
    findings = reg.adapter(entry).adapt(out, {"entry": entry})
    assert list(findings.findings) == ["epidural_hemorrhage"]
    assert rank(findings, entry)["lane"] == lane


# -- aws runtime: serve needs no model, ingest needs the chest function -------
AWS_BASE = {"AURALANE_BUCKET": "b", "AURALANE_IMPORT_ROLE_ARN": "arn:aws:iam::1:role/r",
            "AURALANE_COGNITO_POOL_ID": "us-east-1_x", "AURALANE_COGNITO_CLIENT_ID": "c"}


@pytest.fixture
def aws_env(monkeypatch):
    moto = pytest.importorskip("moto")
    monkeypatch.setenv("AURALANE_RUNTIME", "aws")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    for k in ("AURALANE_CHEST_FUNCTION", "AURALANE_BRAIN_ENDPOINT", "AURALANE_CT_ENDPOINT",
              "AURALANE_FRAME_MODE", "AURALANE_PUBLIC_URL"):
        monkeypatch.delenv(k, raising=False)
    for k, v in AWS_BASE.items():
        monkeypatch.setenv(k, v)
    with moto.mock_aws():
        yield monkeypatch


def test_aws_serve_needs_no_model_and_drafts_from_the_template(aws_env):
    p = run.providers()
    assert p["inference"] is None and isinstance(p["llm"], TemplateLLM)
    assert p["frame_proxy"] is None                # presigned by default: the API never reads pixels
    aws_env.setenv("AURALANE_FRAME_MODE", "proxy")
    assert run.providers()["frame_proxy"] == ""    # the fallback; relative in development
    aws_env.delenv("AURALANE_FRAME_MODE")
    with pytest.raises(SystemExit, match="AURALANE_CHEST_FUNCTION"):
        run.providers(for_ingest=True)
    aws_env.setenv("AURALANE_CHEST_FUNCTION", "fn:live")
    assert run.providers(for_ingest=True)["inference"].ct_endpoint is None


def test_aws_serve_names_a_missing_base_variable(aws_env):
    aws_env.delenv("AURALANE_COGNITO_POOL_ID")
    with pytest.raises(SystemExit, match="AURALANE_COGNITO_POOL_ID"):
        run.providers()


# -- frames streamed by the API ------------------------------------------------
class _FrameStore(FixtureDatastore):
    pixels = np.arange(12, dtype=np.uint16).reshape(3, 4)

    def frame_pixels(self, ref, series_uid, instance_uid, frame=1):
        return self.pixels


def test_api_streams_signed_frames_and_refuses_tampered_links():
    table = FixtureTable()
    study = next(r for r in json.loads(open(WORKLIST).read()) if r["modality"] == "CR")
    # This test is about signed frame links, not whose worklist a study is on.
    app = create_app({"runtime": "aws", "worklist_scope": "all", "blob": FileBlob(BLOB, url_base="/api/blob"),
                      "table": table, "datastore": _FrameStore(table),
                      "auth": DevAuth(password=DEV_PASSWORD), "llm": TemplateLLM(),
                      "frame_proxy": "http://testserver"})
    c = TestClient(app)
    token = c.post("/api/auth/login", json={"username": "radiologist", "password": DEV_PASSWORD}).json()["token"]
    s = study["series"][0]
    url = c.get(f"/api/studies/{study['study']}/frame-url?series={s['series_uid']}"
                f"&instance={s['instance_uids'][0]}",
                headers={"Authorization": f"Bearer {token}"}).json()["url"]
    assert url.startswith("http://testserver/api/frames/") and "sig=" in url
    r = c.get(url)                                           # no bearer token: the URL signs
    assert r.status_code == 200 and r.content == _FrameStore.pixels.tobytes()
    assert r.headers["content-type"] == "application/octet-stream"
    assert c.get(url.replace("sig=", "sig=0")).status_code == 403


# -- simulated intake ----------------------------------------------------------
def test_intake_picks_every_mr_and_ct_then_chest_in_a_shuffled_order(tmp_path):
    import random
    from core.intake import pick
    studies = {"CR": [tmp_path / f"c{i}" for i in range(40)],
               "MR": [tmp_path / "m1", tmp_path / "m2"], "CT": [tmp_path / "t1", tmp_path / "t2"]}
    order = pick(studies, 30, random.Random(1))
    kinds = [m for m, _ in order]
    assert len(order) == 30 and kinds.count("MR") == 2 and kinds.count("CT") == 2
    assert len({p for _, p in order}) == 30                     # no study twice
    assert kinds != sorted(kinds)                               # mixed, not grouped


def test_intake_route_runs_real_ingests_is_admin_only_and_audited(tmp_path):
    import time as _time
    from types import SimpleNamespace
    from core.intake import IntakeSimulator
    seen = []

    def ingest_one(path):
        seen.append(path.name)
        return SimpleNamespace(status="SCORED", lane="ROUTINE", error=None,
                               ref=SimpleNamespace(study_uid=f"uid-{path.name}"))

    sim = IntakeSimulator(ingest_one, {"CR": [tmp_path / "a", tmp_path / "b"], "MR": [], "CT": []})
    table = FixtureTable()
    app = create_app({"runtime": "local", "blob": FileBlob(BLOB, url_base="/api/blob"), "table": table,
                      "datastore": FixtureDatastore(table), "auth": DevAuth(password=DEV_PASSWORD),
                      "llm": TemplateLLM(), "intake": sim})
    c = TestClient(app)
    tok = {u: c.post("/api/auth/login", json={"username": u, "password": DEV_PASSWORD}).json()["token"]
           for u in ("admin", "radiologist")}
    h = {u: {"Authorization": f"Bearer {t}"} for u, t in tok.items()}
    assert c.post("/api/admin/intake", json={"count": 2}, headers=h["radiologist"]).status_code == 403
    r = c.post("/api/admin/intake", json={"count": 2}, headers=h["admin"])
    assert r.status_code == 202 and r.json()["total"] == 2
    for _ in range(50):
        s = c.get("/api/admin/intake", headers=h["admin"]).json()
        if not s["running"]:
            break
        _time.sleep(0.05)
    assert (s["done"], s["failed"]) == (2, 0) and sorted(seen) == ["a", "b"]
    assert [i["lane"] for i in s["items"]] == ["ROUTINE", "ROUTINE"]
    events = c.get("/api/admin/audit", headers=h["admin"]).json()["events"]
    assert any(e["action"] == "intake_simulation" and e["actor"] == "admin@dev.auralane.local"
               for e in events)


def test_intake_without_a_corpus_says_why():
    from core.intake import IntakeSimulator
    s = IntakeSimulator(None, {"CR": [], "MR": [], "CT": []}).status()
    assert s["available"] is False and s["reason"] == "no study corpus on this host"


# -- cloud ingest: identity map, uploader, cloud intake (moto) -------------------
@pytest.fixture
def moto_aws(monkeypatch):
    moto = pytest.importorskip("moto")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(k, "testing")
    with moto.mock_aws():
        yield


def test_dynamo_identity_map_is_consistent_and_issues_one_pseudonym_per_patient(moto_aws):
    import boto3
    from core.providers.aws.identity import DynamoIdentityMap
    boto3.client("dynamodb", region_name="us-east-1").create_table(
        TableName="t", KeySchema=[{"AttributeName": "k", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "k", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST")
    a, b = DynamoIdentityMap("t"), DynamoIdentityMap("t")      # two tasks, one table
    uid = a.map_uid("1.2.3.4")
    assert uid.startswith("1.2.826.0.1.3680043.10.1422.") and b.map_uid("1.2.3.4") == uid
    assert a.map_patient("P1", name="SIM^PATIENT^0001") == "AUR-000001" == b.map_patient("P1")
    assert b.map_patient("P2") == "AUR-000002"
    assert a.record_study("1.2.3.4", uid, "P1").startswith("ACC")


BKT = "auralane-test"


def test_upload_writes_the_files_then_the_manifest_and_the_intake_reads_results(moto_aws, tmp_path):
    import json as _json
    import time as _time
    import boto3
    from core.intake import CloudIntake
    from core.upload import corpus_catalogue, upload_corpus, upload_study
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BKT)
    study = tmp_path / "study"
    study.mkdir()
    for i in range(3):
        (study / f"{i}.dcm").write_bytes(b"DICM" + bytes([i]))
    key = upload_study(s3, BKT, sorted(study.glob("*.dcm")), "batch1", "000", site_state="Kerala")
    manifest = _json.loads(s3.get_object(Bucket=BKT, Key=key)["Body"].read())
    assert key == "upload/batch1/000/_ready.json" and len(manifest["keys"]) == 3
    assert manifest["site_state"] == "Kerala"

    assert upload_corpus(s3, BKT, {"CR": [study], "MR": [], "CT": []}) == {"CR": 1, "MR": 0, "CT": 0}
    assert corpus_catalogue(s3, BKT)["CR"] == ["corpus/CR/000/"]
    intake = CloudIntake(s3, BKT)
    state = intake.start(1, ACTOR)
    for _ in range(100):                                        # the copy runs in a thread
        if not intake.status().get("uploading"):
            break
        _time.sleep(0.05)
    batch = state["batch"]
    assert s3.get_object(Bucket=BKT, Key=f"upload/{batch}/000/_ready.json")
    s3.put_object(Bucket=BKT, Key=f"intake/{batch}/000.json", Body=_json.dumps(
        {"status": "SCORED", "lane": "ROUTINE", "study": "1.2.826.0.1.3680043.10.1422.9",
         "seconds": 30.0}).encode())                            # what the ingest task writes
    s = intake.status()
    assert (s["done"], s["failed"], s["running"]) == (1, 0, False)
    assert s["items"][0]["lane"] == "ROUTINE" and s["items"][0]["source"] == "arrival 1"


# -- access requests ------------------------------------------------------------
class _AccessTable(FixtureTable):
    def __init__(self):
        super().__init__()
        self.access = {}

    def put_item(self, table, item):
        if table == "access":
            self.access[item["username"]] = dict(item)
        else:
            super().put_item(table, item)

    def get_item(self, table, key):
        return dict(self.access[key["username"]]) if table == "access" and key["username"] in \
            self.access else (None if table == "access" else super().get_item(table, key))

    def scan(self, table, fields=None):
        return ([dict(v) for v in self.access.values()] if table == "access"
                else super().scan(table, fields))


class _RequestAuth(DevAuth):
    """DevAuth plus the Cognito access-request calls, recording what they got."""
    def __init__(self):
        super().__init__(password=DEV_PASSWORD)
        self.calls = []

    def request_access(self, username, email, password):
        self.calls.append(("sign_up", username, email, password))

    def approve(self, username, group):
        self.calls.append(("approve", username, group))

    def reject(self, username):
        self.calls.append(("reject", username))

    def verify(self, token):
        from core.types import Principal
        p = super().verify(token)
        # the seeded admin acts as super admin here; the radiologist does not
        return Principal(p.subject, p.email, p.groups + (("superadmin",) if "admin" in p.groups else ()))


def test_access_request_goes_to_the_identity_provider_and_waits_for_the_super_admin():
    table, auth, sent = _AccessTable(), _RequestAuth(), []
    app = create_app({"runtime": "aws", "blob": FileBlob(BLOB, url_base="/api/blob"), "table": table,
                      "datastore": FixtureDatastore(table), "auth": auth, "llm": TemplateLLM(),
                      "notify": lambda subject, message: sent.append((subject, message))})
    c = TestClient(app)
    body = {"username": REQUESTER, "email": REQUESTER_EMAIL, "password": REQUESTER_PASSWORD,
            "role": "radiologist"}
    r = c.post("/api/access-requests", json=body)
    assert r.status_code == 202 and r.json()["status"] == "pending"
    assert auth.calls == [("sign_up", REQUESTER, REQUESTER_EMAIL, REQUESTER_PASSWORD)]
    assert REQUESTER_PASSWORD not in json.dumps(table.access) and REQUESTER_PASSWORD not in json.dumps(sent)
    assert sent and REQUESTER in sent[0][0]
    assert c.post("/api/access-requests", json=body).status_code == 409      # no duplicate

    h = {u: {"Authorization": f"Bearer {c.post('/api/auth/login', json={'username': u, 'password': DEV_PASSWORD}).json()['token']}"}
         for u in ("admin", "radiologist")}
    assert c.get("/api/admin/access-requests", headers=h["radiologist"]).status_code == 403
    rows = c.get("/api/admin/access-requests", headers=h["admin"]).json()["requests"]
    assert [(r["username"], r["status"]) for r in rows] == [(REQUESTER, "pending")]
    r = c.post(f"/api/admin/access-requests/{REQUESTER}", json={"decision": "approve"}, headers=h["admin"])
    assert r.status_code == 200 and r.json()["request"]["status"] == "approved"
    assert auth.calls[-1] == ("approve", REQUESTER, "radiologist")
    assert c.post(f"/api/admin/access-requests/{REQUESTER}", json={"decision": "reject"},
                  headers=h["admin"]).status_code == 409                       # decided once
    events = c.get("/api/admin/audit", headers=h["admin"]).json()["events"]
    assert {"access_request", "access_approved"} <= {e["action"] for e in events}


def test_access_requests_are_refused_where_there_is_no_identity_provider():
    table = FixtureTable()
    c = TestClient(create_app({"runtime": "fixture", "blob": FileBlob(BLOB, url_base="/api/blob"),
                               "table": table, "datastore": FixtureDatastore(table),
                               "auth": DevAuth(password=DEV_PASSWORD), "llm": TemplateLLM()}))
    r = c.post("/api/access-requests", json={"username": REQUESTER, "email": REQUESTER_EMAIL,
                                              "password": REQUESTER_PASSWORD, "role": "admin"})
    assert r.status_code == 409


def test_cognito_access_request_cannot_sign_in_until_approved(moto_aws):
    import boto3
    from core.providers.aws import CognitoAuth
    idp = boto3.client("cognito-idp", region_name="us-east-1")
    pool = idp.create_user_pool(PoolName="p")["UserPool"]["Id"]
    client = idp.create_user_pool_client(UserPoolId=pool, ClientName="c",
                                         ExplicitAuthFlows=["ALLOW_USER_PASSWORD_AUTH",
                                                            "ALLOW_REFRESH_TOKEN_AUTH"])["UserPoolClient"]["ClientId"]
    for g in ("radiologist", "admin"):
        idp.create_group(UserPoolId=pool, GroupName=g)
    auth = CognitoAuth(pool, client, client=idp)
    auth.request_access(REQUESTER, REQUESTER_EMAIL, REQUESTER_PASSWORD)
    with pytest.raises(Exception):
        auth.login(REQUESTER, REQUESTER_PASSWORD)                                     # unconfirmed
    auth.approve(REQUESTER, "radiologist")
    assert auth.login(REQUESTER, REQUESTER_PASSWORD)
    groups = idp.admin_list_groups_for_user(UserPoolId=pool, Username=REQUESTER)["Groups"]
    assert [g["GroupName"] for g in groups] == ["radiologist"]


def test_simulate_on_aws_hands_studies_to_ingest_tasks_and_runs_nothing_in_the_api(moto_aws):
    """Pool study -> upload/ with a predeidentified manifest -> (task) -> result
    in intake/ -> the batch shows the lane. The API process fetches no pixels."""
    import json as _json
    import threading
    import time as _time
    import boto3
    from core.providers.fixture import FixtureTable
    from core.simulate import CloudDispatch, S3Pool, Simulator
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BKT)
    for i in range(2):
        s3.put_object(Bucket=BKT, Key=f"pool/chest/S{i}/a.dcm", Body=b"x")
        s3.put_object(Bucket=BKT, Key=f"pool/chest/S{i}/deid_report.json", Body=b"{}")
    sim = Simulator(S3Pool(s3, BKT), None, FixtureTable(), "aws", workers=2,
                    dispatch=CloudDispatch(s3, BKT, poll_s=0.05, timeout_s=20))

    def task():
        # What core/cloud_ingest.py does when a manifest lands.
        done = set()
        end = _time.monotonic() + 15
        while len(done) < 2 and _time.monotonic() < end:
            for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BKT, Prefix="upload/"):
                for o in page.get("Contents", []):
                    if o["Key"].endswith("_ready.json") and o["Key"] not in done:
                        m = _json.loads(s3.get_object(Bucket=BKT, Key=o["Key"])["Body"].read())
                        assert m["predeidentified"] and m["model_id"] == "cxr-densenet-v1"
                        assert m["report_key"].endswith("deid_report.json")
                        s3.put_object(Bucket=BKT, Key=f"intake/{m['batch']}/{m['item']}.json",
                                      Body=_json.dumps({"status": "SCORED", "lane": "URGENT"}).encode())
                        done.add(o["Key"])
            _time.sleep(0.05)

    t = threading.Thread(target=task)
    t.start()
    state = sim.start({"chest": 2}, [], "test")
    end = _time.monotonic() + 20
    while sim.status(state["batch"])["running"] and _time.monotonic() < end:
        _time.sleep(0.1)
    t.join()
    items = sim.status(state["batch"])["items"]
    assert [i["status"] for i in items] == ["done", "done"], items
    assert {i["lane"] for i in items} == {"URGENT"}


def test_dynamodb_projection_reads_reserved_words_and_recent_audit_uses_the_day_index(moto_aws):
    from core.providers.aws._dynamodb import DynamoDBTable
    from core.types import AuditEvent
    import datetime as _dt
    t = DynamoDBTable(prefix="perf", region_name="us-east-1")
    t.put_item("worklist", {"study": "s1", "status": "SCORED", "lane": "URGENT", "findings": {"a": 0.5},
                            "evidence": {"big": "x" * 50}})
    # `status` is a DynamoDB reserved word; the projection aliases it.
    assert t.scan("worklist", fields=["study", "status", "lane"]) == [
        {"study": "s1", "status": "SCORED", "lane": "URGENT"}]
    now = _dt.datetime.now(_dt.timezone.utc)
    for i, study in enumerate(("s1", "s2", "-")):
        t.append_audit(AuditEvent(actor="a", action="open", study=study,
                                  at=(now + _dt.timedelta(seconds=i)).isoformat(timespec="microseconds"),
                                  outcome="ok", duration_ms=1.0))
    recent = t.recent_audit(days=2)
    assert [e["study"] for e in recent] == ["-", "s2", "s1"]           # newest first
    assert all(e["day"] == e["at"][:10] for e in recent)
    assert t.recent_audit(days=2, limit=2) == recent[:2]
