"""DynamoLocalTable: DynamoDB Local on host port 8001, dummy credentials.

Creates its tables on first use. The implementation is shared with the AWS
provider (providers/aws/_dynamodb.py) so there is one DynamoDB code path.
"""
from core.providers.aws._dynamodb import DynamoDBTable


class DynamoLocalTable(DynamoDBTable):
    def __init__(self, endpoint: str = "http://localhost:8001", prefix: str = "auralane"):
        # DynamoDB Local accepts any credentials; these never leave the host.
        super().__init__(prefix=prefix, endpoint_url=endpoint, region_name="us-east-1",
                         aws_access_key_id="local", aws_secret_access_key="local")
