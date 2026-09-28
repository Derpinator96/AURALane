"""infra/: the stack synthesises with no AWS credentials and creates only what
the providers talk to; the teardown script never touches the datastore.

Synth runs in a subprocess with every AWS credential source removed. Nothing
is deployed and no AWS call is made.
"""
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
from botocore.stub import Stubber

ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra"
KEPT_DATASTORE = "293abea3292b4e888cbdf60e3a9ff283"

pytest.importorskip("aws_cdk", reason="aws-cdk-lib not installed (pip install -r infra/requirements.txt). "
                                      "NOT VERIFIED: that the stack synthesises")


def _synth(tmp_path, *context) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    env.update(AWS_CONFIG_FILE=os.devnull, AWS_SHARED_CREDENTIALS_FILE=os.devnull,
               CDK_OUTDIR=str(tmp_path / "cdk.out"))
    if context:
        env["CDK_CONTEXT_JSON"] = json.dumps(dict(c.split("=") for c in context))
    r = subprocess.run([sys.executable, "app.py"], cwd=INFRA, env=env, capture_output=True,
                       text=True, timeout=600)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads((tmp_path / "cdk.out" / "Auralane.template.json").read_text())


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    return _synth(tmp_path_factory.mktemp("synth"))


def _of(t, kind):
    return [r["Properties"] for r in t["Resources"].values() if r["Type"] == kind]


def test_synthesises_without_credentials_and_never_creates_a_datastore(template):
    types = Counter(r["Type"] for r in template["Resources"].values())
    assert not any(k.startswith("AWS::HealthImaging") for k in types)
    assert types["AWS::S3::Bucket"] == 1 and types["AWS::DynamoDB::Table"] == 4
    # 2 functions: the chest model, and CDK's handler that turns on the bucket's
    # EventBridge notifications.
    assert types["AWS::Lambda::Function"] == 2 and types["AWS::SageMaker::Endpoint"] == 2
    policy = json.dumps(_of(template, "AWS::IAM::ManagedPolicy"))
    assert f"datastore/{KEPT_DATASTORE}" in policy and "us-east-1" in policy


def test_tables_match_what_the_provider_expects(template):
    from core.providers.aws._dynamodb import SCHEMA
    tables = {t["TableName"]: t for t in _of(template, "AWS::DynamoDB::Table")}
    for name, (pk, sk) in SCHEMA.items():
        keys = {k["KeyType"]: k["AttributeName"] for k in tables[f"auralane-{name}"]["KeySchema"]}
        assert keys == ({"HASH": pk, "RANGE": sk} if sk else {"HASH": pk})
        assert tables[f"auralane-{name}"]["BillingMode"] == "PAY_PER_REQUEST"


def test_working_prefixes_expire_and_evidence_is_kept(template):
    (bucket,) = _of(template, "AWS::S3::Bucket")
    rules = {r["Prefix"]: r["ExpirationInDays"] for r in bucket["LifecycleConfiguration"]["Rules"]}
    assert rules == {"transient/": 1, "import/": 1, "inference/": 1, "upload/": 1, "intake/": 7}
    assert bucket["PublicAccessBlockConfiguration"]["BlockPublicPolicy"] is True


def test_cognito_has_the_two_groups_and_password_auth(template):
    assert {g["GroupName"] for g in _of(template, "AWS::Cognito::UserPoolGroup")} == {
        "radiologist", "admin", "superadmin"}
    (client,) = _of(template, "AWS::Cognito::UserPoolClient")
    assert "ALLOW_USER_PASSWORD_AUTH" in client["ExplicitAuthFlows"]
    (pool,) = _of(template, "AWS::Cognito::UserPool")
    assert pool["UserPoolTier"] == "LITE"


def test_brain_and_ct_endpoints_are_async_and_scale_to_zero(template):
    configs = _of(template, "AWS::SageMaker::EndpointConfig")
    assert all("AsyncInferenceConfig" in c for c in configs)
    assert sorted(c["ProductionVariants"][0]["InstanceType"] for c in configs) == [
        "ml.m5.2xlarge", "ml.m5.xlarge"]                           # brain, CT: CPU images
    targets = _of(template, "AWS::ApplicationAutoScaling::ScalableTarget")
    assert [(x["MinCapacity"], x["MaxCapacity"]) for x in targets] == [(0, 1), (0, 1)]
    kinds = [p["PolicyType"] for p in _of(template, "AWS::ApplicationAutoScaling::ScalingPolicy")]
    assert sorted(kinds) == ["StepScaling"] * 2 + ["TargetTrackingScaling"] * 2
    alarms = _of(template, "AWS::CloudWatch::Alarm")
    assert [a["MetricName"] for a in alarms] == ["HasBacklogWithoutCapacity"] * 2


def test_chest_lambda_has_no_provisioned_concurrency_by_default(template):
    (alias,) = _of(template, "AWS::Lambda::Alias")         # invoked through "live" always
    assert alias["Name"] == "live" and "ProvisionedConcurrencyConfig" not in alias
    (fn,) = [f for f in _of(template, "AWS::Lambda::Function") if f.get("PackageType") == "Image"]
    assert fn["MemorySize"] == 3008 and fn["PackageType"] == "Image"


def test_outputs_are_the_environment_core_run_reads(template):
    from core.providers.aws.config import ENV
    described = {o["Description"] for o in template["Outputs"].values()}
    assert set(ENV.values()) <= described


def test_brain_and_ct_can_be_left_out(tmp_path):
    t = _synth(tmp_path, "brain=false", "ct=false")
    assert not _of(t, "AWS::SageMaker::Endpoint")
    assert not _of(t, "AWS::ApplicationAutoScaling::ScalableTarget")


def test_teardown_refuses_a_stack_that_holds_the_datastore():
    import boto3
    sys.path.insert(0, str(INFRA))
    import teardown
    cfn = boto3.client("cloudformation", region_name="us-east-1",
                       aws_access_key_id="testing", aws_secret_access_key="testing")
    with Stubber(cfn) as stub:
        stub.add_response("describe_stacks", {"Stacks": [{
            "StackName": "Auralane", "CreationTime": "2026-09-27T00:00:00Z",
            "StackStatus": "CREATE_COMPLETE", "Outputs": []}]})
        stub.add_response("list_stack_resources", {"StackResourceSummaries": [{
            "LogicalResourceId": "X", "PhysicalResourceId": KEPT_DATASTORE,
            "ResourceType": "AWS::HealthImaging::Datastore",
            "LastUpdatedTimestamp": "2026-09-27T00:00:00Z", "ResourceStatus": "CREATE_COMPLETE"}]})
        with pytest.raises(RuntimeError, match="not the stack's to delete"):
            teardown.plan(cfn)


def test_teardown_never_creates_a_healthimaging_client():
    source = (INFRA / "teardown.py").read_text()
    assert '"medical-imaging"' not in source and "'medical-imaging'" not in source


def test_an_upload_manifest_starts_a_fargate_ingest_task_and_the_api_cannot_read_uploads(template):
    (rule,) = _of(template, "AWS::Events::Rule")
    assert rule["EventPattern"]["detail"]["object"]["key"] == [{"wildcard": "upload/*/_ready.json"}]
    assert "EcsParameters" in rule["Targets"][0]
    (task,) = _of(template, "AWS::ECS::TaskDefinition")
    assert task["RequiresCompatibilities"] == ["FARGATE"]
    assert not _of(template, "AWS::EC2::NatGateway")              # no NAT charge
    denies = [s for p in _of(template, "AWS::IAM::ManagedPolicy")
              for s in p["PolicyDocument"]["Statement"] if s.get("Effect") == "Deny"]
    assert len(denies) == 1 and denies[0]["Action"] == "s3:GetObject"
    assert "upload/*" in json.dumps(denies[0]["Resource"])


def test_people_can_request_access_but_get_nothing_until_approved(template):
    (pool,) = _of(template, "AWS::Cognito::UserPool")
    assert pool["AdminCreateUserConfig"]["AllowAdminCreateUserOnly"] is False   # sign-up is open
    assert not pool.get("AutoVerifiedAttributes")                               # the super admin is the gate
    (topic,) = _of(template, "AWS::SNS::Topic")
    actions = {a for p in _of(template, "AWS::IAM::ManagedPolicy")
               for s in p["PolicyDocument"]["Statement"]
               for a in ([s["Action"]] if isinstance(s["Action"], str) else s["Action"])}
    assert {"cognito-idp:AdminConfirmSignUp", "cognito-idp:AdminAddUserToGroup", "sns:Publish",
            "cognito-idp:ListUsersInGroup",              # readers, for distribution
            "sagemaker:InvokeEndpointAsync"} <= actions   # simulated ingest from the API
