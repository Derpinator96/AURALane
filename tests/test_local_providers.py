"""Local providers, one behaviour each. DynamoDB tests need the local stack:

    docker compose -f docker-compose.local.yml up -d
"""
import secrets
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


def test_devauth_password_has_no_default(tmp_path, monkeypatch):
    monkeypatch.delenv("AURALANE_DEV_PASSWORD", raising=False)
    with pytest.raises(PermissionError):
        DevAuth().login("radiologist", "")
    f = tmp_path / "dev" / "devauth.password"
    a = DevAuth(password_file=f)
    assert f.stat().st_mode & 0o777 == 0o600
    assert a.verify(a.login("radiologist", f.read_text())).groups == ("radiologist",)
    assert DevAuth(password_file=f)._password == a._password          # stable across processes
    env = secrets.token_hex(8)
    monkeypatch.setenv("AURALANE_DEV_PASSWORD", env)
    assert DevAuth(password_file=f).login("admin@dev.auralane.local", env)


@pytest.fixture(params=["dynamodb-local", "dynamodb-aws-moto"])
def table(request, monkeypatch):
    """The same TablePort tests against DynamoDB Local and against the AWS
    provider on moto, whose tables are created here the way the stack creates
    them (DynamoTable never creates tables itself)."""
    if request.param == "dynamodb-local":
        t = DynamoLocalTable(prefix=f"test-{uuid.uuid4().hex[:8]}")
        try:
            t.ddb.meta.client.list_tables()
        except Exception as e:
            pytest.fail(f"DynamoDB Local is not answering on :8001 ({e}). Start the local stack.")
        yield t
        return
    import boto3
    from moto import mock_aws
    from core.providers.aws._dynamodb import SCHEMA
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
        for name, (pk, sk) in SCHEMA.items():
            keys = [{"AttributeName": pk, "KeyType": "HASH"}]
            attrs = [{"AttributeName": pk, "AttributeType": "S"}]
            if sk:
                keys.append({"AttributeName": sk, "KeyType": "RANGE"})
                attrs.append({"AttributeName": sk, "AttributeType": "S"})
            ddb.create_table(TableName=f"auralane-{name}", KeySchema=keys,
                             AttributeDefinitions=attrs, BillingMode="PAY_PER_REQUEST")
        yield aws.DynamoTable(prefix="auralane")


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
    # delete_item exists for notes (annotations); it refuses the audit table.
    with pytest.raises(PermissionError):
        table.delete_item("audit", {"study": "1.2.3", "event_id": rows[0]["event_id"]})
    assert not hasattr(table, "update_item")


def test_inference_dispatches_on_output_type():
    inf = InProcessInference()
    inf.handlers["multilabel"] = lambda cfg, **k: ("chest", k["pixels"].shape)
    ref = StudyRef("1.2.3", "x")
    assert inf.score(ref, {"output_type": "multilabel"},
                     pixels=np.zeros((4, 4), np.uint8)) == ("chest", (4, 4))
    with pytest.raises(ValueError):
        inf.score(ref, {"output_type": "no-such-type"})


def test_template_llm_writes_a_structured_report_from_the_findings():
    text = TemplateLLM().draft({"study": "1.2.3", "model_id": "cxr", "lane": "URGENT",
                                "modality": "CR", "clock": "under 1 hr",
                                "triage": {"driver": "Edema", "signal": 0.9, "sla": "< 1 hr"},
                                "findings": {"Edema": 0.9, "Mass": 0.1}})
    assert text.startswith("NON-DIAGNOSTIC")
    for section in ("EXAMINATION", "TECHNIQUE", "COMPARISON", "FINDINGS", "IMPRESSION", "TRIAGE NOTE"):
        assert section in text
    assert "None available." in text and "Findings suggestive of edema" in text


def test_bedrock_stays_a_stub_that_names_its_service():
    """Bedrock is blocked at the account level; drafting ships on TemplateLLM."""
    with pytest.raises(NotImplementedError, match="Bedrock"):
        aws.BedrockLLM().draft({})


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
