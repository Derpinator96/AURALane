"""DynamoDB table access, shared by DynamoDB Local and DynamoDB.

Lives under providers/aws/ because it imports boto3, and no AWS SDK import is
allowed anywhere else. The local provider (providers/local/dynamo.py) is this
class pointed at http://localhost:8001; the AWS provider in Prompt 3 is the same
class with no endpoint override. One code path, so what passes locally is what
runs on AWS.

Exercised against DynamoDB Local (amazon/dynamodb-local) in this build. Not yet
run against real DynamoDB.
"""
from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

from core.ports import TablePort
from core.types import AuditEvent

# table -> (partition key, sort key or None)
SCHEMA = {
    "worklist": ("study", None),
    "audit": ("study", "event_id"),
}
NO_STUDY = "-"      # audit partition for events that precede a StudyRef


def _to_ddb(item: dict) -> dict:
    """boto3's resource layer rejects float; round-trip through Decimal."""
    return json.loads(json.dumps(item), parse_float=Decimal)


def _from_ddb(item: dict | None) -> dict | None:
    if item is None:
        return None
    return json.loads(json.dumps(item, default=lambda d: float(d) if d % 1 else int(d)))


class DynamoDBTable(TablePort):
    def __init__(self, prefix: str = "auralane", **boto_kwargs):
        self.prefix = prefix
        self.ddb = boto3.resource("dynamodb", **boto_kwargs)
        self._ready: set[str] = set()

    def _table(self, name: str):
        if name not in SCHEMA:
            raise KeyError(f"unknown table {name!r}")
        full = f"{self.prefix}-{name}"
        if name not in self._ready:
            self._ensure(full, *SCHEMA[name])
            self._ready.add(name)
        return self.ddb.Table(full)

    def _ensure(self, full, pk, sk):
        existing = self.ddb.meta.client.list_tables()["TableNames"]
        if full in existing:
            return
        keys = [{"AttributeName": pk, "KeyType": "HASH"}]
        attrs = [{"AttributeName": pk, "AttributeType": "S"}]
        if sk:
            keys.append({"AttributeName": sk, "KeyType": "RANGE"})
            attrs.append({"AttributeName": sk, "AttributeType": "S"})
        self.ddb.create_table(TableName=full, KeySchema=keys, AttributeDefinitions=attrs,
                              BillingMode="PAY_PER_REQUEST")
        self.ddb.meta.client.get_waiter("table_exists").wait(TableName=full)

    def put_item(self, table: str, item: dict[str, Any]) -> None:
        if table == "audit":
            raise PermissionError("audit is append only; use append_audit")
        self._table(table).put_item(Item=_to_ddb(item))

    def get_item(self, table: str, key: dict[str, Any]) -> dict[str, Any] | None:
        return _from_ddb(self._table(table).get_item(Key=key).get("Item"))

    def query(self, table: str, **conditions) -> list[dict[str, Any]]:
        pk = SCHEMA[table][0]
        if set(conditions) != {pk}:
            raise ValueError(f"{table} is queried by {pk!r} only, got {sorted(conditions)}")
        t, items, kwargs = self._table(table), [], {
            "KeyConditionExpression": Key(pk).eq(conditions[pk])}
        while True:
            r = t.query(**kwargs)
            items += r["Items"]
            if "LastEvaluatedKey" not in r:
                return [_from_ddb(i) for i in items]
            kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]

    def append_audit(self, event: AuditEvent) -> None:
        item = event.to_dict()
        item["study"] = event.study or NO_STUDY
        # Sorts by time; the uuid suffix keeps two events in the same
        # microsecond distinct. The condition refuses any overwrite.
        item["event_id"] = f"{event.at}#{uuid.uuid4().hex[:12]}"
        self._table("audit").put_item(
            Item=_to_ddb(item), ConditionExpression="attribute_not_exists(event_id)")
