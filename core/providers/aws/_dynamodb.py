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
import datetime
from concurrent.futures import ThreadPoolExecutor
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
    "access": ("username", None),        # access requests, core/api.py
    "annotations": ("study", "annotation_id"),
    "reports": ("study", "version"),     # radiologist reports, one row per saved version
}
AUDIT_BY_DAY = "by_day"                  # audit GSI: partition day (YYYY-MM-DD), sort event_id
NO_STUDY = "-"      # audit partition for events that precede a StudyRef


def _to_ddb(item: dict) -> dict:
    """boto3's resource layer rejects float; round-trip through Decimal."""
    return json.loads(json.dumps(item), parse_float=Decimal)


def _plain(v: Any) -> Any:
    """Decimals to int or float, in place of a JSON dump and reload."""
    if isinstance(v, Decimal):
        return float(v) if v % 1 else int(v)
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_plain(x) for x in v]
    return v


def _from_ddb(item: dict | None) -> dict | None:
    return None if item is None else _plain(item)


class DynamoDBTable(TablePort):
    def __init__(self, prefix: str = "auralane", **boto_kwargs):
        self.prefix = prefix
        self.ddb = boto3.resource("dynamodb", **boto_kwargs)
        self._ready: set[str] = set()
        self._no_day_index = False           # the audit table has no by_day index

    def _table(self, name: str):
        if name not in SCHEMA:
            raise KeyError(f"unknown table {name!r}")
        full = f"{self.prefix}-{name}"
        if name not in self._ready:
            self._ensure(full, *SCHEMA[name])
            self._ready.add(name)
        return self.ddb.Table(full)

    def _ensure(self, full, pk, sk):
        client = self.ddb.meta.client
        try:
            client.describe_table(TableName=full)
            return
        except client.exceptions.ResourceNotFoundException:
            pass
        # (list_tables answers 100 names a page; DynamoDB Local fills up with
        # test tables, so a first-page check missed tables that existed.)
        keys = [{"AttributeName": pk, "KeyType": "HASH"}]
        attrs = [{"AttributeName": pk, "AttributeType": "S"}]
        if sk:
            keys.append({"AttributeName": sk, "KeyType": "RANGE"})
            attrs.append({"AttributeName": sk, "AttributeType": "S"})
        extra = {}
        if full.endswith("-audit"):
            attrs.append({"AttributeName": "day", "AttributeType": "S"})
            extra["GlobalSecondaryIndexes"] = [{
                "IndexName": AUDIT_BY_DAY, "Projection": {"ProjectionType": "ALL"},
                "KeySchema": [{"AttributeName": "day", "KeyType": "HASH"},
                              {"AttributeName": "event_id", "KeyType": "RANGE"}]}]
        try:
            self.ddb.create_table(TableName=full, KeySchema=keys, AttributeDefinitions=attrs,
                                  BillingMode="PAY_PER_REQUEST", **extra)
        except client.exceptions.ResourceInUseException:
            pass                                 # created meanwhile by another process
        self.ddb.meta.client.get_waiter("table_exists").wait(TableName=full)

    def put_item(self, table: str, item: dict[str, Any]) -> None:
        if table == "audit":
            raise PermissionError("audit is append only; use append_audit")
        self._table(table).put_item(Item=_to_ddb(item))

    def get_item(self, table: str, key: dict[str, Any]) -> dict[str, Any] | None:
        return _from_ddb(self._table(table).get_item(Key=key).get("Item"))

    def delete_item(self, table: str, key: dict[str, Any]) -> None:
        if table == "audit":
            raise PermissionError("audit is append only")
        self._table(table).delete_item(Key=key)

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

    def scan(self, table: str, fields: list[str] | None = None) -> list[dict[str, Any]]:
        if table == "audit":
            raise PermissionError("audit is read per study with query, never scanned")
        t, items, kwargs = self._table(table), [], {}
        if fields:
            # Aliased: status, source, error and others are DynamoDB reserved words.
            kwargs["ProjectionExpression"] = ", ".join(f"#f{i}" for i in range(len(fields)))
            kwargs["ExpressionAttributeNames"] = {f"#f{i}": f for i, f in enumerate(fields)}
        while True:
            r = t.scan(**kwargs)
            items += r["Items"]
            if "LastEvaluatedKey" not in r:
                return [_from_ddb(i) for i in items]
            kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]

    def append_audit(self, event: AuditEvent) -> None:
        item = event.to_dict()
        item["study"] = event.study or NO_STUDY
        item["day"] = event.at[:10]          # the by_day index's partition
        # Sorts by time; the uuid suffix keeps two events in the same
        # microsecond distinct. The condition refuses any overwrite.
        item["event_id"] = f"{event.at}#{uuid.uuid4().hex[:12]}"
        self._table("audit").put_item(
            Item=_to_ddb(item), ConditionExpression="attribute_not_exists(event_id)")

    def recent_audit(self, days: int = 7, limit: int = 5000) -> list[dict[str, Any]] | None:
        """One query per day on the by_day index, newest first. None when the
        table has no such index (a stack deployed before it existed)."""
        if self._no_day_index:
            return None
        t = self._table("audit")
        today = datetime.datetime.now(datetime.timezone.utc).date()

        def one(day: str) -> list[dict]:
            out, kwargs = [], {"IndexName": AUDIT_BY_DAY, "ScanIndexForward": False,
                               "KeyConditionExpression": Key("day").eq(day)}
            while len(out) < limit:
                r = t.query(**kwargs)
                out += r["Items"]
                if "LastEvaluatedKey" not in r:
                    break
                kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]
            return out

        try:
            with ThreadPoolExecutor(min(days, 8)) as pool:
                per_day = list(pool.map(one, [(today - datetime.timedelta(days=i)).isoformat()
                                              for i in range(days)]))
        except Exception as e:                       # noqa: BLE001
            if "index" in str(e).lower():
                self._no_day_index = True
                return None
            raise
        events = [_from_ddb(i) for day in per_day for i in day]
        events.sort(key=lambda e: e["event_id"], reverse=True)
        return events[:limit]
