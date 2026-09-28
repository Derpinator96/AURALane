"""AuralaneStack: what the AWS providers talk to. us-east-1 only.

Creates:
  - one S3 bucket: evidence overlays (kept), and transient/, import/,
    inference/ working prefixes (expire after one day)
  - two DynamoDB tables, on demand: <prefix>-worklist, <prefix>-audit
  - a Cognito user pool (Lite plan), groups radiologist and admin, one app
    client allowing USER_PASSWORD_AUTH
  - the HealthImaging import role, assumable by medical-imaging.amazonaws.com
  - the chest inference Lambda, a container image built from
    infra/lambda/chest/Dockerfile
  - two SageMaker asynchronous endpoints, each with its model and execution
    role, scaling between 0 and 1 instances: brain MR (ml.m5.2xlarge, CPU
    image) and head CT (ml.m5.xlarge, CPU image)
  - one managed policy with exactly what core/ needs, to attach to whoever runs
    the API with AURALANE_RUNTIME=aws

Does not create: the HealthImaging datastore. The existing one
(293abea3292b4e888cbdf60e3a9ff283) is referenced by ID and never touched by
this stack or infra/teardown.py.

Synthesises with no AWS credentials: the account stays unresolved and no
lookups are made. Container images are hashed at synth and built only at
deploy time. Every billable resource is in docs/AWS-COSTS.md.

Context flags (cdk synth/deploy -c key=value):
  brain=false               leave the brain SageMaker endpoint out entirely
  ct=false                  leave the head CT SageMaker endpoint out entirely
  brain_instance=TYPE       default ml.m5.2xlarge
  ct_instance=TYPE          default ml.m5.xlarge
  chest_provisioned=N       provisioned concurrency for the chest Lambda
                            (default 0: the cold-start trade-off is a decision,
                            see docs/AWS-COSTS.md)
"""
from __future__ import annotations

from pathlib import Path

from aws_cdk import (CfnOutput, Duration, IgnoreMode, RemovalPolicy, Stack, aws_applicationautoscaling as aas,
                     aws_cloudwatch as cw, aws_cognito as cognito, aws_dynamodb as ddb,
                     aws_ec2 as ec2, aws_ecr_assets as ecr_assets, aws_ecs as ecs,
                     aws_events as events, aws_events_targets as targets,
                     aws_iam as iam, aws_lambda as lambda_,
                     aws_logs as logs,
                     aws_s3 as s3, aws_sagemaker as sm, aws_sns as sns,
                     aws_sns_subscriptions as subs)
from constructs import Construct

REPO = Path(__file__).resolve().parents[1]
REGION = "us-east-1"
EXISTING_DATASTORE_ID = "293abea3292b4e888cbdf60e3a9ff283"
TABLE_PREFIX = "auralane"
# CPU: see infra/containers/brain/Dockerfile for why the brain image is CPU.
BRAIN_INSTANCE = "ml.m5.2xlarge"
CT_INSTANCE = "ml.m5.xlarge"
WORKING_PREFIXES = ("transient/", "import/", "inference/", "upload/")
INGEST_CONTEXT = ["*", "!core", "!adapters", "!models", "!sim/edge", "!imaging.py", "!triage.py",
                  "!reference.json", "!infra/containers/ingest", "**/__pycache__", "sim/edge/test_*"]

# Build contexts are the repository root; these keep them to what the images
# copy (Docker ignore syntax: exclude everything, then re-include).
CHEST_CONTEXT = ["*", "!core", "!adapters", "!models", "!imaging.py", "!triage.py",
                 "!reference.json", "!infra/lambda/chest", "**/__pycache__"]
BRAIN_CONTEXT = ["*", "!core", "!adapters", "!models", "!imaging.py", "!triage.py",
                 "!reference.json", "!infra/containers/brain", "!infra/containers/sagemaker_http.py",
                 "!_external/brainmri/backend", "!_external/brainmri/brats_mri_segmentation",
                 "**/__pycache__"]
CT_CONTEXT = ["*", "!core", "!adapters", "!models", "!imaging.py", "!triage.py",
              "!reference.json", "!infra/containers/ct", "!infra/containers/sagemaker_http.py",
              "!_external/triagelane-ct/src", "!_external/triagelane-ct/configs",
              "**/__pycache__"]


CLIENT_ORIGINS = ["https://aura-lane.vercel.app", "http://localhost:5173",
                  "http://localhost:4173", "http://localhost:4174"]


class AuralaneStack(Stack):
    def __init__(self, scope: Construct, cid: str, **kwargs) -> None:
        super().__init__(scope, cid, **kwargs)
        with_brain = str(self.node.try_get_context("brain") or "true").lower() != "false"
        with_ct = str(self.node.try_get_context("ct") or "true").lower() != "false"
        chest_provisioned = int(self.node.try_get_context("chest_provisioned") or 0)

        # -- S3 ----------------------------------------------------------------
        bucket = s3.Bucket(
            self, "Bucket", encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL, enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            # upload/ holds raw studies until the ingest task deletes them; the
            # one-day expiry is the backstop. intake/ holds per-arrival results.
            lifecycle_rules=[s3.LifecycleRule(prefix=p, expiration=Duration.days(1))
                             for p in WORKING_PREFIXES]
                            + [s3.LifecycleRule(prefix="intake/", expiration=Duration.days(7))],
            event_bridge_enabled=True,
            # The 3D viewer (NiiVue) fetches evidence NIfTI through presigned
            # URLs with fetch(), which needs CORS; <img> tags did not. GET only,
            # from the hosted client and the local dev and preview servers.
            cors=[s3.CorsRule(allowed_methods=[s3.HttpMethods.GET, s3.HttpMethods.HEAD],
                              allowed_origins=CLIENT_ORIGINS, allowed_headers=["*"],
                              max_age=3000)])

        # -- DynamoDB: the schema core/providers/aws/_dynamodb.py expects -------
        worklist = ddb.Table(
            self, "Worklist", table_name=f"{TABLE_PREFIX}-worklist",
            partition_key=ddb.Attribute(name="study", type=ddb.AttributeType.STRING),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST, removal_policy=RemovalPolicy.DESTROY)
        audit = ddb.Table(
            self, "Audit", table_name=f"{TABLE_PREFIX}-audit",
            partition_key=ddb.Attribute(name="study", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="event_id", type=ddb.AttributeType.STRING),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST, removal_policy=RemovalPolicy.DESTROY)

        # The identity map for de-identification in AWS (core/providers/aws/
        # identity.py). Only the ingest task's role can read it; the API cannot.
        access = ddb.Table(
            self, "Access", table_name=f"{TABLE_PREFIX}-access",
            partition_key=ddb.Attribute(name="username", type=ddb.AttributeType.STRING),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST, removal_policy=RemovalPolicy.DESTROY)
        # Radiologists' notes pinned to images (core/api.py, annotations routes).
        annotations = ddb.Table(
            self, "Annotations", table_name=f"{TABLE_PREFIX}-annotations",
            partition_key=ddb.Attribute(name="study", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="annotation_id", type=ddb.AttributeType.STRING),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST, removal_policy=RemovalPolicy.DESTROY)
        identity = ddb.Table(
            self, "Identity", table_name=f"{TABLE_PREFIX}-identity",
            partition_key=ddb.Attribute(name="k", type=ddb.AttributeType.STRING),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST, removal_policy=RemovalPolicy.DESTROY)

        # -- Cognito -----------------------------------------------------------
        pool = cognito.UserPool(
            # Self sign-up is how people request access (core/api.py): the new
            # account is unconfirmed and in no group until a super admin
            # approves it, so it can neither sign in nor reach a route.
            # Cognito's own verification emails are off; the super admin is
            # the gate, not an email code.
            self, "Users", feature_plan=cognito.FeaturePlan.LITE, self_sign_up_enabled=True,
            sign_in_aliases=cognito.SignInAliases(username=True, email=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=False),
            removal_policy=RemovalPolicy.DESTROY)
        for group in ("radiologist", "admin", "superadmin"):
            cognito.CfnUserPoolGroup(self, f"Group-{group}", user_pool_id=pool.user_pool_id,
                                     group_name=group)
        client = pool.add_client("Web", auth_flows=cognito.AuthFlow(user_password=True),
                                 generate_secret=False)

        # -- HealthImaging import role -----------------------------------------
        datastore_arn = (f"arn:aws:medical-imaging:{REGION}:{self.account}:"
                         f"datastore/{EXISTING_DATASTORE_ID}")
        import_role = iam.Role(
            self, "ImportRole",
            assumed_by=iam.ServicePrincipal("medical-imaging.amazonaws.com", conditions={
                "StringEquals": {"aws:SourceAccount": self.account}}),
            description="HealthImaging reads staged DICOM from import/ and writes the job "
                        "output back")
        import_role.add_to_policy(iam.PolicyStatement(
            actions=["s3:ListBucket"], resources=[bucket.bucket_arn],
            # No s3:prefix condition: with one, StartDICOMImportJob refused with
            # "data access role does not have proper read permission to the input
            # s3 prefix". AWS's documented import role grants ListBucket on the
            # bucket as a whole; object access stays limited to import/*.
            ))
        import_role.add_to_policy(iam.PolicyStatement(
            actions=["s3:GetObject", "s3:PutObject"], resources=[bucket.arn_for_objects("import/*")]))

        # -- Chest inference: Lambda container image ---------------------------
        chest = lambda_.DockerImageFunction(
            self, "ChestInference",
            code=lambda_.DockerImageCode.from_image_asset(
                str(REPO), file="infra/lambda/chest/Dockerfile",
                exclude=CHEST_CONTEXT, ignore_mode=IgnoreMode.DOCKER,
                platform=ecr_assets.Platform.LINUX_AMD64),
            # 300 s: the first run after a deploy loads the 3 GB image lazily and
            # exceeded 120 s (measured 2026-09-28). Billed only while running.
            memory_size=3008, timeout=Duration.seconds(300),
            architecture=lambda_.Architecture.X86_64,
            environment={"AURALANE_BUCKET": bucket.bucket_name},
            log_group=logs.LogGroup(self, "ChestLogs", retention=logs.RetentionDays.ONE_WEEK,
                                    removal_policy=RemovalPolicy.DESTROY))
        bucket.grant_read_write(chest)
        # Invocations go to the alias "live", so provisioned concurrency, when
        # chosen (-c chest_provisioned=1 on presentation day), is what answers.
        live = chest.add_alias("live", provisioned_concurrent_executions=chest_provisioned or None)

        # -- Brain MR and head CT: SageMaker asynchronous endpoints ------------
        endpoints = {}
        if with_brain:
            endpoints["AURALANE_BRAIN_ENDPOINT"] = self._async_endpoint(
                "Brain", "infra/containers/brain/Dockerfile", BRAIN_CONTEXT, bucket,
                self.node.try_get_context("brain_instance") or BRAIN_INSTANCE)
        if with_ct:
            endpoints["AURALANE_CT_ENDPOINT"] = self._async_endpoint(
                "Ct", "infra/containers/ct/Dockerfile", CT_CONTEXT, bucket,
                self.node.try_get_context("ct_instance") or CT_INSTANCE)

        # -- What core/ needs, as one policy -----------------------------------
        common = [
            iam.PolicyStatement(actions=["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
                                resources=[bucket.arn_for_objects("*")]),
            iam.PolicyStatement(actions=["s3:ListBucket"], resources=[bucket.bucket_arn]),
            iam.PolicyStatement(actions=["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query",
                                         "dynamodb:Scan", "dynamodb:DescribeTable"],
                                resources=[worklist.table_arn, audit.table_arn]),
            iam.PolicyStatement(actions=["medical-imaging:StartDICOMImportJob",
                                         "medical-imaging:GetDICOMImportJob",
                                         "medical-imaging:SearchImageSets",
                                         "medical-imaging:GetImageSetMetadata",
                                         "medical-imaging:GetImageFrame",
                                         "medical-imaging:GetDICOMInstanceFrames",
                                         "medical-imaging:GetDICOMSeriesMetadata"],
                                resources=[datastore_arn, f"{datastore_arn}/*"]),
            iam.PolicyStatement(actions=["iam:PassRole"], resources=[import_role.role_arn]),
            iam.PolicyStatement(actions=["lambda:InvokeFunction"],
                                resources=[chest.function_arn, live.function_arn]),
        ] + ([iam.PolicyStatement(
            actions=["sagemaker:InvokeEndpointAsync"],
            resources=[f"arn:aws:sagemaker:{REGION}:{self.account}:endpoint/*"])]
             if endpoints else [])
        # The API may start arrivals (write upload/) but never read a raw upload.
        # Simulated ingest (core/simulate.py) uses exactly `common` from the API:
        # it reads the de-identified pool/ prefix, imports into HealthImaging,
        # invokes the chest Lambda and the async endpoints (InvokeEndpointAsync,
        # above) and writes evidence/ and the tables.
        # Access requests: a topic that emails the super admin (-c admin_email=...),
        # and what the API needs to record and decide requests.
        topic = sns.Topic(self, "AccessRequests", display_name="AURALANE access requests")
        # From -c admin_email or AURALANE_ADMIN_EMAIL; never committed (the repo
        # is public). A deploy without either drops the subscription.
        admin_email = (self.node.try_get_context("admin_email")
                       or __import__("os").environ.get("AURALANE_ADMIN_EMAIL"))
        if admin_email:
            topic.add_subscription(subs.EmailSubscription(str(admin_email)))
        app_policy = iam.ManagedPolicy(self, "AppPolicy", statements=common + [
            iam.PolicyStatement(effect=iam.Effect.DENY, actions=["s3:GetObject"],
                                resources=[bucket.arn_for_objects("upload/*")]),
            iam.PolicyStatement(actions=["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Scan",
                                         "dynamodb:DescribeTable"], resources=[access.table_arn]),
            iam.PolicyStatement(actions=["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query",
                                         "dynamodb:Scan", "dynamodb:DeleteItem",
                                         "dynamodb:DescribeTable"], resources=[annotations.table_arn]),
            iam.PolicyStatement(actions=["cognito-idp:AdminConfirmSignUp",
                                         "cognito-idp:AdminAddUserToGroup",
                                         "cognito-idp:AdminDeleteUser",
                                         # The reader list for distributing the worklist.
                                         "cognito-idp:ListUsersInGroup"],
                                resources=[pool.user_pool_arn]),
            iam.PolicyStatement(actions=["sns:Publish"], resources=[topic.topic_arn])])

        # -- Cloud ingest: an upload manifest starts one Fargate task ------------
        # upload/<batch>/<item>/_ready.json -> EventBridge -> ECS RunTask. The
        # task de-identifies, imports, calls the models and writes the worklist
        # (core/cloud_ingest.py). Public subnets and no NAT gateway: nothing
        # listens, and there is no NAT charge.
        vpc = ec2.Vpc(self, "IngestVpc", max_azs=2, nat_gateways=0, subnet_configuration=[
            ec2.SubnetConfiguration(name="public", subnet_type=ec2.SubnetType.PUBLIC)])
        cluster = ecs.Cluster(self, "IngestCluster", vpc=vpc)
        task = ecs.FargateTaskDefinition(self, "IngestTask", cpu=2048, memory_limit_mib=4096)
        ingest_policy = iam.ManagedPolicy(self, "IngestPolicy", statements=common + [
            iam.PolicyStatement(actions=["dynamodb:GetItem", "dynamodb:PutItem",
                                         "dynamodb:UpdateItem", "dynamodb:DescribeTable"],
                                resources=[identity.table_arn])])
        task.task_role.add_managed_policy(ingest_policy)
        env = {"AWS_REGION": REGION, "AURALANE_RUNTIME": "aws",
               "AURALANE_BUCKET": bucket.bucket_name, "AURALANE_TABLE_PREFIX": TABLE_PREFIX,
               "AURALANE_DATASTORE_ID": EXISTING_DATASTORE_ID,
               "AURALANE_IMPORT_ROLE_ARN": import_role.role_arn,
               "AURALANE_COGNITO_POOL_ID": pool.user_pool_id,
               "AURALANE_COGNITO_CLIENT_ID": client.user_pool_client_id,
               "AURALANE_CHEST_FUNCTION": f"{chest.function_name}:live",
               "AURALANE_IDENTITY_TABLE": identity.table_name,
               "AURALANE_SITE_STATE": str(self.node.try_get_context("site_state") or ""),
               **endpoints}
        task.add_container(
            "ingest",
            image=ecs.ContainerImage.from_asset(
                str(REPO), file="infra/containers/ingest/Dockerfile", exclude=INGEST_CONTEXT,
                ignore_mode=IgnoreMode.DOCKER, platform=ecr_assets.Platform.LINUX_AMD64),
            environment=env,
            logging=ecs.LogDrivers.aws_logs(stream_prefix="ingest", log_group=logs.LogGroup(
                self, "IngestLogs", retention=logs.RetentionDays.ONE_WEEK,
                removal_policy=RemovalPolicy.DESTROY)))
        events.Rule(
            self, "UploadReady",
            event_pattern=events.EventPattern(
                source=["aws.s3"], detail_type=["Object Created"],
                detail={"bucket": {"name": [bucket.bucket_name]},
                        "object": {"key": events.Match.wildcard("upload/*/_ready.json")}}),
            targets=[targets.EcsTask(
                cluster=cluster, task_definition=task, assign_public_ip=True,
                subnet_selection=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
                container_overrides=[targets.ContainerOverride(
                    container_name="ingest",
                    environment=[targets.TaskEnvironmentVariable(
                        name="AURALANE_MANIFEST_KEY",
                        value=events.EventField.from_path("$.detail.object.key"))])])])

        # -- The environment core/run.py reads ----------------------------------
        outputs = {"AURALANE_BUCKET": bucket.bucket_name,
                   "AURALANE_TABLE_PREFIX": TABLE_PREFIX,
                   "AURALANE_DATASTORE_ID": EXISTING_DATASTORE_ID,
                   "AURALANE_IMPORT_ROLE_ARN": import_role.role_arn,
                   "AURALANE_COGNITO_POOL_ID": pool.user_pool_id,
                   "AURALANE_COGNITO_CLIENT_ID": client.user_pool_client_id,
                   "AURALANE_CHEST_FUNCTION": f"{chest.function_name}:live",
                   "AURALANE_APP_POLICY_ARN": app_policy.managed_policy_arn}
        outputs.update(endpoints)
        outputs["AURALANE_IDENTITY_TABLE"] = identity.table_name
        outputs["AURALANE_ACCESS_TOPIC"] = topic.topic_arn
        outputs["AURALANE_INGEST_CLUSTER"] = cluster.cluster_name
        for name, value in outputs.items():
            CfnOutput(self, name.replace("_", ""), key=name.replace("_", ""), value=value,
                      description=name)

    def _async_endpoint(self, name: str, dockerfile: str, context: list[str], bucket: s3.Bucket,
                        instance_type: str) -> str:
        """A SageMaker asynchronous endpoint for one model image, scaling between
        0 and 1 instances. Returns the endpoint name."""
        low = name.lower()
        # SageMaker accepts only Docker v2 manifests. Docker with the containerd
        # image store writes OCI ones, which CreateModel rejects ("Unsupported
        # manifest media type application/vnd.oci.image.manifest.v1+json").
        # The CDK CLI already turns build attestations off, which this needs.
        image = ecr_assets.DockerImageAsset(
            self, f"{name}Image", directory=str(REPO), file=dockerfile,
            exclude=context, ignore_mode=IgnoreMode.DOCKER,
            platform=ecr_assets.Platform.LINUX_AMD64,
            outputs=["type=image,oci-mediatypes=false"])
        role = iam.Role(self, f"{name}Role",
                        assumed_by=iam.ServicePrincipal("sagemaker.amazonaws.com"))
        image.repository.grant_pull(role)
        bucket.grant_read_write(role, "inference/*")
        # The CT endpoint writes its Grad-CAM images to evidence/ (core/ct_gradcam.py).
        bucket.grant_put(role, "evidence/*")
        role.add_to_policy(iam.PolicyStatement(
            actions=["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents",
                     "cloudwatch:PutMetricData"], resources=["*"]))
        model = sm.CfnModel(self, f"{name}Model", execution_role_arn=role.role_arn,
                            primary_container=sm.CfnModel.ContainerDefinitionProperty(
                                image=image.image_uri))
        model.node.add_dependency(role)
        config = sm.CfnEndpointConfig(
            self, f"{name}EndpointConfig",
            production_variants=[sm.CfnEndpointConfig.ProductionVariantProperty(
                variant_name="AllTraffic", model_name=model.attr_model_name,
                instance_type=instance_type, initial_instance_count=1)],
            async_inference_config=sm.CfnEndpointConfig.AsyncInferenceConfigProperty(
                output_config=sm.CfnEndpointConfig.AsyncInferenceOutputConfigProperty(
                    s3_output_path=f"s3://{bucket.bucket_name}/inference/async-out/",
                    s3_failure_path=f"s3://{bucket.bucket_name}/inference/async-failed/"),
                client_config=sm.CfnEndpointConfig.AsyncInferenceClientConfigProperty(
                    max_concurrent_invocations_per_instance=1)))
        endpoint = sm.CfnEndpoint(self, f"{name}Endpoint",
                                  endpoint_config_name=config.attr_endpoint_config_name)
        endpoint_name = endpoint.attr_endpoint_name

        # Scale to zero when idle, back to one when work is waiting. Target
        # tracking on backlog per instance handles scale-in to 0; it cannot
        # scale out from 0, so a step policy on HasBacklogWithoutCapacity
        # adds the first instance.
        target = aas.CfnScalableTarget(
            self, f"{name}Scaling", service_namespace="sagemaker",
            resource_id=f"endpoint/{endpoint_name}/variant/AllTraffic",
            scalable_dimension="sagemaker:variant:DesiredInstanceCount",
            min_capacity=0, max_capacity=1)
        target.add_resource_dependency(endpoint)
        aas.CfnScalingPolicy(
            self, f"{name}BacklogTracking", policy_name=f"auralane-{low}-backlog",
            policy_type="TargetTrackingScaling", scaling_target_id=target.ref,
            target_tracking_scaling_policy_configuration=aas.CfnScalingPolicy.TargetTrackingScalingPolicyConfigurationProperty(
                target_value=1.0, scale_in_cooldown=600, scale_out_cooldown=60,
                customized_metric_specification=aas.CfnScalingPolicy.CustomizedMetricSpecificationProperty(
                    metric_name="ApproximateBacklogSizePerInstance", namespace="AWS/SageMaker",
                    statistic="Average",
                    dimensions=[aas.CfnScalingPolicy.MetricDimensionProperty(
                        name="EndpointName", value=endpoint_name)])))
        wake = aas.CfnScalingPolicy(
            self, f"{name}WakeFromZero", policy_name=f"auralane-{low}-wake",
            policy_type="StepScaling", scaling_target_id=target.ref,
            step_scaling_policy_configuration=aas.CfnScalingPolicy.StepScalingPolicyConfigurationProperty(
                adjustment_type="ChangeInCapacity", cooldown=300,
                metric_aggregation_type="Average",
                step_adjustments=[aas.CfnScalingPolicy.StepAdjustmentProperty(
                    metric_interval_lower_bound=0, scaling_adjustment=1)]))
        cw.CfnAlarm(
            self, f"{name}BacklogWithoutCapacity", metric_name="HasBacklogWithoutCapacity",
            namespace="AWS/SageMaker", statistic="Average", period=60, evaluation_periods=1,
            threshold=1, comparison_operator="GreaterThanOrEqualToThreshold",
            dimensions=[cw.CfnAlarm.DimensionProperty(name="EndpointName", value=endpoint_name)],
            treat_missing_data="notBreaching", alarm_actions=[wake.attr_arn])
        return endpoint_name
