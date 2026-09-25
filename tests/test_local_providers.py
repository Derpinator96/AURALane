"""Local providers, one behaviour each. DynamoDB tests need the local stack:

    docker compose -f docker-compose.local.yml up -d
"""
import uuid

import jwt
import numpy as np
import pytest

from core.providers import aws
from core.providers.local import DevAuth, DynamoLocalTable, FileBlob, InProcessInference, TemplateLLM
from core.types import AuditEvent, StudyRef


def test_fileblob_round_trip_and_refuses_escape(tmp_path):
    b = FileBlob(tmp_path)
    b.put("a/b.bin", b"xyz")
    assert b.get("a/b.bin") == b"xyz"
    assert b.presigned_url("a/b.bin").startswith("file://")
    b.delete("a/b.bin")
    with pytest.raises(FileNotFoundError):
        b.get("a/b.bin")
    with pytest.raises(ValueError):
        b.put("../outside", b"x")


def test_devauth_issues_and_verifies_seeded_users():
    a = DevAuth()
    p = a.verify(a.issue("radiologist"))
    assert p.groups == ("radiologist",) and p.email.endswith("@dev.auralane.local")
    assert a.verify(a.issue("admin")).groups == ("admin",)
    with pytest.raises(jwt.InvalidTokenError):
        DevAuth().verify(a.issue("admin"))            # different key
    with pytest.raises(jwt.ExpiredSignatureError):
        a.verify(a.issue("admin", ttl=-10))


@pytest.fixture
def table():
    t = DynamoLocalTable(prefix=f"test-{uuid.uuid4().hex[:8]}")
    try:
        t.ddb.meta.client.list_tables()
    except Exception as e:
        pytest.fail(f"DynamoDB Local is not answering on :8001 ({e}). Start the local stack.")
    return t


def test_dynamo_worklist_round_trip(table):
    table.put_item("worklist", {"study": "1.2.3", "lane": "URGENT", "acuity": 77.2})
    assert table.get_item("worklist", {"study": "1.2.3"}) == {
        "study": "1.2.3", "lane": "URGENT", "acuity": 77.2}
    assert [r["lane"] for r in table.query("worklist", study="1.2.3")] == ["URGENT"]


def test_dynamo_audit_is_append_only(table):
    ev = AuditEvent("pipeline", "deidentify", "1.2.3", "2026-09-24T00:00:00Z", "ok", 12.5)
    table.append_audit(ev)
    table.append_audit(ev)                         # same content, still two events
    rows = table.query("audit", study="1.2.3")
    assert len(rows) == 2 and rows[0]["duration_ms"] == 12.5
    with pytest.raises(PermissionError):
        table.put_item("audit", {"study": "1.2.3", "event_id": rows[0]["event_id"]})
    assert not hasattr(table, "delete_item") and not hasattr(table, "update_item")


def test_inference_dispatches_on_output_type():
    inf = InProcessInference()
    inf.handlers["multilabel"] = lambda cfg, **k: ("chest", k["pixels"].shape)
    ref = StudyRef("1.2.3", "x")
    assert inf.score(ref, {"output_type": "multilabel"},
                     pixels=np.zeros((4, 4), np.uint8)) == ("chest", (4, 4))
    with pytest.raises(ValueError):
        inf.score(ref, {"output_type": "no-such-type"})


def test_template_llm_leaves_impression_to_radiologist():
    text = TemplateLLM().draft({"study": "1.2.3", "model_id": "cxr", "lane": "URGENT",
                                "triage": {"driver": "Edema", "signal": 0.9, "sla": "< 1 hr"},
                                "findings": {"Edema": 0.9, "Mass": 0.1}})
    assert text.startswith("NON-DIAGNOSTIC")
    assert "Edema" in text and "to be written by the reading radiologist" in text


@pytest.mark.parametrize("cls, call", [
    (aws.HealthImagingDatastore, lambda o: o.get_metadata(None)),
    (aws.S3Blob, lambda o: o.get("k")),
    (aws.DynamoTable, lambda o: o.query("worklist", study="1")),
    (aws.CognitoAuth, lambda o: o.verify("t")),
    (aws.LambdaSageMakerInference, lambda o: o.score(None, {})),
    (aws.BedrockLLM, lambda o: o.draft({})),
])
def test_aws_stubs_name_their_service(cls, call):
    with pytest.raises(NotImplementedError, match="Prompt 3"):
        call(cls())


def test_fileblob_signed_urls_expire_and_resist_tampering(tmp_path):
    from urllib.parse import parse_qs, urlsplit
    b = FileBlob(tmp_path, url_base="/api/blob")
    b.put("evidence/x.png", b"png")
    u = urlsplit(b.presigned_url("evidence/x.png", ttl=60))
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    assert u.path == "/api/blob/evidence/x.png"
    assert b.open_signed("evidence/x.png", int(q["expires"]), q["sig"]).read_bytes() == b"png"
    with pytest.raises(PermissionError):
        b.open_signed("evidence/y.png", int(q["expires"]), q["sig"])        # other key
    with pytest.raises(PermissionError):
        b.open_signed("evidence/x.png", int(q["expires"]) + 1, q["sig"])    # longer expiry
    u = urlsplit(b.presigned_url("evidence/x.png", ttl=-5))
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    with pytest.raises(PermissionError, match="expired"):
        b.open_signed("evidence/x.png", int(q["expires"]), q["sig"])
