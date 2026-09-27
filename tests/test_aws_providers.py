"""The AWS providers, with no AWS call and no credentials.

S3, DynamoDB and Cognito run on moto. Lambda and SageMaker Runtime use
botocore's Stubber (moto would need Docker to run a function). HealthImaging
runs against tests/fakes/healthimaging.py, and its full port contract is in
tests/test_datastore_contract.py alongside Orthanc.
"""
import io
import json
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import boto3
import jwt
import numpy as np
import pytest
import requests
from botocore.response import StreamingBody
from botocore.stub import ANY, Stubber

from core.providers.aws import (CognitoAuth, DynamoTable, HealthImagingDatastore,
                                LambdaSageMakerInference, S3Blob)
from core.providers.local import FileBlob
from core.types import StudyRef

BUCKET = "auralane-test"


@pytest.fixture
def aws_env(monkeypatch):
    for var in ("AWS_PROFILE", "AWS_SESSION_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    from moto import mock_aws
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)
        yield


# -- BlobPort contract: FileBlob and S3Blob, same behaviour --------------------
@pytest.fixture(params=["file", "s3"])
def blob(request, tmp_path, aws_env):
    if request.param == "file":
        b = FileBlob(tmp_path, url_base="/api/blob")

        def fetch(url):
            q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
            key = urlsplit(url).path.removeprefix("/api/blob/")
            return b.open_signed(key, int(q["expires"]), q["sig"]).read_bytes()
    else:
        b = S3Blob(BUCKET)

        def fetch(url):                      # moto answers presigned URLs through requests
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            return r.content
    b.fetch = fetch
    return b


def test_blob_round_trip_delete_and_missing(blob):
    assert blob.put("evidence/1.2.3/gradcam.png", b"png") == "evidence/1.2.3/gradcam.png"
    assert blob.get("evidence/1.2.3/gradcam.png") == b"png"
    blob.delete("evidence/1.2.3/gradcam.png")
    with pytest.raises(FileNotFoundError):
        blob.get("evidence/1.2.3/gradcam.png")
    blob.delete("evidence/1.2.3/gradcam.png")           # deleting twice is not an error


def test_blob_refuses_keys_that_escape(blob):
    for bad in ("../outside", "a/../../outside"):
        with pytest.raises(ValueError):
            blob.put(bad, b"x")


def test_blob_presigned_url_serves_the_bytes_and_refuses_missing(blob):
    blob.put("evidence/x.png", b"overlay")
    assert blob.fetch(blob.presigned_url("evidence/x.png", ttl=60)) == b"overlay"
    with pytest.raises(FileNotFoundError):
        blob.presigned_url("evidence/none.png")


def test_s3_presigned_url_expires(aws_env):
    b = S3Blob(BUCKET)
    b.put("evidence/x.png", b"overlay")
    q = parse_qs(urlsplit(b.presigned_url("evidence/x.png", ttl=120)).query)
    assert q["X-Amz-Expires"] == ["120"] and q["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]


# -- DynamoTable: never creates tables -----------------------------------------
def test_dynamo_table_refuses_to_create_a_missing_table(aws_env):
    with pytest.raises(RuntimeError, match="CDK stack creates it"):
        DynamoTable(prefix="missing").scan("worklist")
    assert boto3.client("dynamodb", region_name="us-east-1").list_tables()["TableNames"] == []


# -- CognitoAuth ---------------------------------------------------------------
@pytest.fixture
def cognito(aws_env):
    from tests.test_api import PASSWORD, _cognito_auth
    return _cognito_auth(), PASSWORD


def test_cognito_maps_groups_onto_the_devauth_principal_shape(cognito):
    auth, password = cognito
    p = auth.verify(auth.login("admin", password))
    assert p.groups == ("admin",) and isinstance(p.groups, tuple)
    assert p.subject and p.email


def test_cognito_refuses_wrong_password_unknown_user_and_foreign_tokens(cognito):
    auth, password = cognito
    with pytest.raises(PermissionError):
        auth.login("radiologist", password + "x")
    with pytest.raises(PermissionError):
        auth.login("nobody", password)
    token = auth.login("radiologist", password)
    other = CognitoAuth(auth.pool, "some-other-client", jwks={"keys": list(
        k._jwk_data for k in auth._keys.values())}, client=auth.idp)
    with pytest.raises(jwt.InvalidAudienceError):
        other.verify(token)
    with pytest.raises(jwt.InvalidTokenError):
        auth.verify(token[:-4] + "AAAA")                 # signature no longer matches


# -- LambdaSageMakerInference, Stubber for the service calls --------------------
def _stream(data: bytes) -> StreamingBody:
    return StreamingBody(io.BytesIO(data), len(data))


def test_chest_goes_to_lambda_and_returns_the_in_process_shape(aws_env):
    lam = boto3.client("lambda", region_name="us-east-1")
    answer = {"preds": {"Edema": 0.7}, "evidence": {"gradcam_png": "evidence/1.2.3/g.png"}}
    with Stubber(lam) as stub:
        stub.add_response("invoke", {"StatusCode": 200, "Payload": _stream(json.dumps(answer).encode())},
                          {"FunctionName": "chest-fn", "InvocationType": "RequestResponse",
                           "Payload": ANY})
        inf = LambdaSageMakerInference(BUCKET, "chest-fn", "brain-ep", lambda_client=lam)
        out = inf.score(StudyRef("1.2.3", "x"), {"id": "cxr-densenet-v1", "runtime": "lambda"},
                        pixels=np.zeros((8, 8), np.uint16))
    assert out == answer
    assert boto3.client("s3", region_name="us-east-1").list_objects_v2(
        Bucket=BUCKET).get("KeyCount") == 0            # the staged input PNG is removed


def test_chest_function_error_is_raised_not_swallowed(aws_env):
    lam = boto3.client("lambda", region_name="us-east-1")
    with Stubber(lam) as stub:
        stub.add_response("invoke", {"StatusCode": 200, "FunctionError": "Unhandled",
                                     "Payload": _stream(b'{"errorMessage": "boom"}')})
        inf = LambdaSageMakerInference(BUCKET, "chest-fn", "brain-ep", lambda_client=lam)
        with pytest.raises(RuntimeError, match="boom"):
            inf.score(StudyRef("1.2.3", "x"), {"id": "cxr", "runtime": "lambda"},
                      pixels=np.zeros((8, 8), np.uint8))


def test_brain_goes_to_sagemaker_async_and_waits_for_the_answer(aws_env, tmp_path):
    s3 = boto3.client("s3", region_name="us-east-1")
    smr = boto3.client("sagemaker-runtime", region_name="us-east-1")
    nifti = {}
    for ch in ("T1c", "T1", "T2", "FLAIR"):
        nifti[ch] = tmp_path / f"{ch}.nii.gz"
        nifti[ch].write_bytes(ch.encode())
    out_key, pred_key = "inference/async-out/abc.out", "inference/pred/prediction.nii.gz"
    s3.put_object(Bucket=BUCKET, Key=pred_key, Body=b"label map")
    s3.put_object(Bucket=BUCKET, Key=out_key, Body=json.dumps(
        {"wt_volume_cm3": 12.0, "_prediction_s3": f"s3://{BUCKET}/{pred_key}"}).encode())
    with Stubber(smr) as stub:
        stub.add_response("invoke_endpoint_async",
                          {"InferenceId": "abc", "OutputLocation": f"s3://{BUCKET}/{out_key}",
                           "FailureLocation": f"s3://{BUCKET}/inference/async-failed/abc.out"},
                          {"EndpointName": "brain-ep", "ContentType": "application/json",
                           "InputLocation": ANY, "InvocationTimeoutSeconds": 900})
        inf = LambdaSageMakerInference(BUCKET, "chest-fn", "brain-ep", sagemaker_runtime=smr,
                                       poll_seconds=0.01)
        m = inf.score(StudyRef("1.2.3", "x"), {"id": "brain", "runtime": "sagemaker-async"},
                      nifti=nifti)
    assert m["wt_volume_cm3"] == 12.0
    assert Path(m["_prediction_path"]).read_bytes() == b"label map"
    request_key = next(o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET)["Contents"]
                       if o["Key"].endswith("request.json"))
    req = json.loads(s3.get_object(Bucket=BUCKET, Key=request_key)["Body"].read())
    assert set(req["inputs"]) == {"T1c", "T1", "T2", "FLAIR"}


def test_brain_failure_location_is_raised(aws_env, tmp_path):
    s3 = boto3.client("s3", region_name="us-east-1")
    smr = boto3.client("sagemaker-runtime", region_name="us-east-1")
    s3.put_object(Bucket=BUCKET, Key="inference/async-failed/abc.out", Body=b"monai missing")
    (tmp_path / "t.nii.gz").write_bytes(b"x")
    with Stubber(smr) as stub:
        stub.add_response("invoke_endpoint_async", {
            "InferenceId": "abc", "OutputLocation": f"s3://{BUCKET}/inference/async-out/abc.out",
            "FailureLocation": f"s3://{BUCKET}/inference/async-failed/abc.out"})
        inf = LambdaSageMakerInference(BUCKET, "c", "brain-ep", sagemaker_runtime=smr,
                                       poll_seconds=0.01)
        with pytest.raises(RuntimeError, match="monai missing"):
            inf.score(StudyRef("1.2.3", "x"), {"id": "b", "runtime": "sagemaker-async"},
                      nifti={"T1c": tmp_path / "t.nii.gz"})


# -- HealthImagingDatastore specifics (the port contract is elsewhere) ---------
@pytest.fixture
def healthimaging():
    from tests.test_datastore_contract import _healthimaging
    store = _healthimaging()
    yield store


def test_frame_url_is_a_short_lived_presigned_dicomweb_url(healthimaging):
    ref = StudyRef("1.2.3", "a" * 32)
    u = urlsplit(healthimaging.frame_url(ref, "4.5", "6.7", frame=1, ttl=300))
    q = parse_qs(u.query)
    assert u.path.endswith("/studies/1.2.3/series/4.5/instances/6.7/frames/1")
    assert q["imageSetId"] == ["a" * 32] and q["X-Amz-Expires"] == ["300"]
    assert q["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"] and "X-Amz-Signature" in q
    assert "/medical-imaging/aws4_request" in q["X-Amz-Credential"][0]


def test_import_job_failure_surfaces_its_message(healthimaging, tmp_path):
    corpus = Path(__file__).resolve().parents[1] / "data" / "chest" / "studies"
    manifest = corpus / "manifest.json"
    if not manifest.exists():
        pytest.skip("needs the chest corpus. NOT VERIFIED: import failure reporting")
    entry = json.loads(manifest.read_text())[0]
    with Stubber(healthimaging.mi) as stub:
        stub.add_response("start_dicom_import_job", {
            "datastoreId": "d", "jobId": "j", "jobStatus": "SUBMITTED", "submittedAt": time.time()})
        stub.add_response("get_dicom_import_job", {"jobProperties": {
            "jobId": "j", "jobName": "n", "jobStatus": "FAILED", "datastoreId": "d",
            "dataAccessRoleArn": "arn:aws:iam::000000000000:role/r", "inputS3Uri": "s3://b/i/",
            "outputS3Uri": "s3://b/o/", "message": "access denied to input"}})
        with pytest.raises(RuntimeError, match="access denied to input"):
            healthimaging.import_study([corpus / entry["path"]])
