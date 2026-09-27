"""AWS settings, in one place. Region is us-east-1 throughout: HealthImaging is
not offered in Mumbai (ap-south-1), so for an Indian deployment only
de-identified data would be stored outside the country.

Every value here comes from the environment core/run.py passes in, which the
CDK stack's outputs supply (infra/README.md). Nothing reads the environment
anywhere else in the AWS providers.
"""
REGION = "us-east-1"

# The datastore created by hand for the HealthImaging smoke test. Reused, never
# created by the stack, never deleted by the teardown script.
EXISTING_DATASTORE_ID = "293abea3292b4e888cbdf60e3a9ff283"

ENV = {
    "bucket": "AURALANE_BUCKET",
    "table_prefix": "AURALANE_TABLE_PREFIX",
    "datastore_id": "AURALANE_DATASTORE_ID",
    "import_role_arn": "AURALANE_IMPORT_ROLE_ARN",
    "user_pool_id": "AURALANE_COGNITO_POOL_ID",
    "client_id": "AURALANE_COGNITO_CLIENT_ID",
    "chest_function": "AURALANE_CHEST_FUNCTION",
    "brain_endpoint": "AURALANE_BRAIN_ENDPOINT",
}
