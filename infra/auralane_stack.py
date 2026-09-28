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
                     aws_ecr_assets as ecr_assets, aws_iam as iam, aws_lambda as lambda_,
                     aws_logs as logs,
                     aws_s3 as s3, aws_sagemaker as sm)
from constructs import Construct

REPO = Path(__file__).resolve().parents[1]
REGION = "us-east-1"
EXISTING_DATASTORE_ID = "293abea3292b4e888cbdf60e3a9ff283"
TABLE_PREFIX = "auralane"
# CPU: see infra/containers/brain/Dockerfile for why the brain image is CPU.
BRAIN_INSTANCE = "ml.m5.2xlarge"
CT_INSTANCE = "ml.m5.xlarge"
WORKING_PREFIXES = ("transient/", "import/", "inference/")

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
            lifecycle_rules=[s3.LifecycleRule(prefix=p, expiration=Duration.days(1))
                             for p in WORKING_PREFIXES])

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

        # -- Cognito -----------------------------------------------------------
        pool = cognito.UserPool(
            self, "Users", feature_plan=cognito.FeaturePlan.LITE, self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(username=True, email=True),
            removal_policy=RemovalPolicy.DESTROY)
        for group in ("radiologist", "admin"):
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
            conditions={"StringLike": {"s3:prefix": ["import/*"]}}))
        import_role.add_to_policy(iam.PolicyStatement(
            actions=["s3:GetObject", "s3:PutObject"], resources=[bucket.arn_for_objects("import/*")]))

        # -- Chest inference: Lambda container image ---------------------------
        chest = lambda_.DockerImageFunction(
            self, "ChestInference",
            code=lambda_.DockerImageCode.from_image_asset(
                str(REPO), file="infra/lambda/chest/Dockerfile",
                exclude=CHEST_CONTEXT, ignore_mode=IgnoreMode.DOCKER,
                platform=ecr_assets.Platform.LINUX_AMD64),
            memory_size=3008, timeout=Duration.seconds(120),
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
        app_policy = iam.ManagedPolicy(self, "AppPolicy", statements=[
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
             if endpoints else []))

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
