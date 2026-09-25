"""The clinician API, on the fixture providers (no Docker, no data/).

Role separation is tested in both directions: a radiologist gets 403 on every
admin route, an admin gets 403 on every study route. frame-url must return a
URL and never image bytes.
"""
import json
from pathlib import Path

import secrets

import pytest
from fastapi.testclient import TestClient

from core.api import DISCLAIMER, LANE_ORDER, create_app
from core.providers.fixture import BLOB, WORKLIST, FixtureDatastore, FixtureTable
from core.providers.local import DevAuth, FileBlob, TemplateLLM

FIXTURE = json.loads(Path(WORKLIST).read_text())
CHEST = next(r for r in FIXTURE if r["modality"] == "CR")
ADMIN_ROUTES = [("get", "/api/admin/audit"), ("get", "/api/admin/lane-mix"),
                ("get", "/api/admin/models")]
STUDY_ROUTES = [("get", "/api/worklist"), ("get", f"/api/studies/{CHEST['study']}"),
                ("get", f"/api/studies/{CHEST['study']}/frame-url?series="
                        f"{CHEST['series'][0]['series_uid']}&instance="
                        f"{CHEST['series'][0]['instance_uids'][0]}"),
                ("get", f"/api/studies/{CHEST['study']}/series/{CHEST['series'][0]['series_uid']}"),
                ("post", f"/api/studies/{CHEST['study']}/verdict")]

PASSWORD = secrets.token_hex(8)    # no password is written in the repository


@pytest.fixture
def client(tmp_path):
    table = FixtureTable()
    app = create_app({"runtime": "fixture", "blob": FileBlob(BLOB, url_base="/api/blob"),
                      "table": table,
                      "datastore": FixtureDatastore(table), "auth": DevAuth(password=PASSWORD),
                      "llm": TemplateLLM()})
    c = TestClient(app)

    def login(user):
        r = c.post("/api/auth/login", json={"username": user, "password": PASSWORD})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['token']}"}

    c.radiologist, c.admin = login("radiologist"), login("admin")
    return c


def _call(c, method, url, headers):
    if method == "post":
        return c.post(url, headers=headers, json={"verdict": "agree"})
    return c.get(url, headers=headers)


def test_health_is_open_and_carries_disclaimer(client):
    assert client.get("/api/health").json()["disclaimer"] == DISCLAIMER


def test_login_refuses_wrong_password(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "guess"})
    assert r.status_code == 401


@pytest.mark.parametrize("method, url", ADMIN_ROUTES + STUDY_ROUTES)
def test_every_route_needs_a_token(client, method, url):
    assert _call(client, method, url, {}).status_code == 401
    assert _call(client, method, url, {"Authorization": "Bearer nonsense"}).status_code == 401


@pytest.mark.parametrize("method, url", ADMIN_ROUTES)
def test_radiologist_gets_403_on_admin_routes(client, method, url):
    assert _call(client, method, url, client.radiologist).status_code == 403
    assert _call(client, method, url, client.admin).status_code == 200


@pytest.mark.parametrize("method, url", STUDY_ROUTES)
def test_admin_gets_403_on_study_routes(client, method, url):
    assert _call(client, method, url, client.admin).status_code == 403
    assert _call(client, method, url, client.radiologist).status_code == 200


def test_worklist_is_in_lane_order_with_values_copied_from_rows(client):
    rows = client.get("/api/worklist", headers=client.radiologist).json()["studies"]
    assert len(rows) == len(FIXTURE)
    keys = [(LANE_ORDER[r["lane"]], -(r["acuity"] or 0)) for r in rows]
    assert keys == sorted(keys)
    stored = {r["study"]: r["triage"]["acuity"] for r in FIXTURE}
    assert all(r["acuity"] == stored[r["study"]] for r in rows)
    abstain = [r for r in rows if r["lane"] == "ABSTAIN"]
    assert abstain and all(r["lane_label"] == "NEEDS HUMAN TRIAGE" for r in abstain)
    assert {r["clock"] for r in rows if r["lane"] == "CRITICAL"} == {"under 15 min"}
    lanes = client.get("/api/worklist", headers=client.radiologist).json()["lanes"]
    assert [l["lane"] for l in lanes] == ["CRITICAL", "URGENT", "ABSTAIN", "FAILED",
                                           "EXPEDITED", "ROUTINE"]
    assert [l["lane"] for l in lanes if l["pinned"]] == ["ABSTAIN", "FAILED"]


def test_study_detail(client):
    body = client.get(f"/api/studies/{CHEST['study']}", headers=client.radiologist).json()
    assert body["study"]["lane"] == CHEST["lane"]
    assert body["series"][0]["instance_count"] == 1
    assert body["draft"].startswith("NON-DIAGNOSTIC")
    assert [f["signal"] for f in body["findings"]] == sorted(
        (f["signal"] for f in body["findings"]), reverse=True)
    assert client.get("/api/studies/nope", headers=client.radiologist).status_code == 404


def test_frame_url_is_a_url_never_image_bytes(client):
    s = CHEST["series"][0]
    r = client.get(f"/api/studies/{CHEST['study']}/frame-url?series={s['series_uid']}"
                   f"&instance={s['instance_uids'][0]}&frame=1", headers=client.radiologist)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert set(r.json()) == {"url"} and r.json()["url"] == s["frame_url"]
    assert len(r.content) < 200 and b"DICM" not in r.content


def test_verdict_writes_audit_and_updates_the_row(client):
    url = f"/api/studies/{CHEST['study']}/verdict"
    assert client.post(url, headers=client.radiologist, json={"verdict": "maybe"}).status_code == 422
    r = client.post(url, headers=client.radiologist, json={"verdict": "disagree"})
    assert r.json()["study"]["verdict"]["value"] == "disagree"
    row = next(x for x in client.get("/api/worklist", headers=client.radiologist).json()["studies"]
               if x["study"] == CHEST["study"])
    assert row["verdict"]["by"] == "radiologist@dev.auralane.local"
    events = client.get("/api/admin/audit", headers=client.admin).json()["events"]
    assert [(e["action"], e["study"], e["detail"]["verdict"]) for e in events] == [
        ("verdict", CHEST["study"], "disagree")]
    assert events[0]["actor"] == "radiologist@dev.auralane.local"


def test_lane_mix_counts_real_rows(client):
    body = client.get("/api/admin/lane-mix", headers=client.admin).json()
    counts = {l["lane"]: l["count"] for l in body["lanes"]}
    for lane in counts:
        assert counts[lane] == sum(r["lane"] == lane for r in FIXTURE)
    assert body["total"] == len(FIXTURE)


def test_models_lists_the_registry(client):
    body = client.get("/api/admin/models", headers=client.admin).json()
    assert {m["id"] for m in body["models"]} == {"cxr-densenet-v1", "brain-brats-monai-v0.5.4"}
    assert body["abstain_band"] == [0.35, 0.60]


def test_series_gives_frame_urls_and_headers_never_pixels(client):
    s = CHEST["series"][0]
    body = client.get(f"/api/studies/{CHEST['study']}/series/{s['series_uid']}",
                      headers=client.radiologist).json()
    inst = body["instances"]
    assert [i["sop"] for i in inst] == s["instance_uids"]
    assert inst[0]["frame_url"] == s["frame_url"]
    assert inst[0]["metadata"]["00280010"]["Value"] == [s["metadata"][0]["00280010"]["Value"][0]]
    assert "7FE00010" not in inst[0]["metadata"]


def test_evidence_is_served_by_signed_url_only(client):
    body = client.get(f"/api/studies/{CHEST['study']}", headers=client.radiologist).json()
    url = body["evidence_urls"]["gradcam_layer_png"]
    assert url.startswith("/api/blob/") and "sig=" in url and "expires=" in url
    r = client.get(url)                                  # no bearer token: the URL is the credential
    assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get(url.replace("sig=", "sig=0")).status_code == 403
    path, _ = url.split("?")
    assert client.get(f"{path}?expires=1&sig=x").status_code == 403
    assert client.get("/api/blob/../worklist.json?expires=9999999999&sig=x").status_code in (403, 404)
