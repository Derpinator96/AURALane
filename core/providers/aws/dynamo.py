"""DynamoTable: TablePort on Amazon DynamoDB.

The same class as the local provider (_dynamodb.DynamoDBTable, run against
DynamoDB Local), with one difference: on AWS the CDK stack owns the tables, so
this provider never creates one. A missing table is an error naming it, not a
silent CreateTable with whatever permissions the caller happens to have.
"""
from __future__ import annotations

from core.providers.aws._dynamodb import DynamoDBTable
from core.providers.aws.config import REGION


class DynamoTable(DynamoDBTable):
    service = "Amazon DynamoDB"
    def __init__(self, prefix: str = "auralane", region: str = REGION, **boto_kwargs):
        from core.providers.aws import session as shared
        boto_kwargs.setdefault("config", shared.config())
        super().__init__(prefix=prefix, region_name=region, **boto_kwargs)

    def _ensure(self, full, pk, sk):
        try:
            self.ddb.meta.client.describe_table(TableName=full)
        except self.ddb.meta.client.exceptions.ResourceNotFoundException as e:
            raise RuntimeError(f"DynamoDB table {full!r} does not exist; the CDK stack "
                               f"creates it (infra/). This provider never creates tables.") from e
