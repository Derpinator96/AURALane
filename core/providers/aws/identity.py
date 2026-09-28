"""DynamoIdentityMap: the identity map for de-identification running in AWS.

The same three calls sim/edge/deid.py makes on the local SQLite map
(sim/edge/identity.py): map_uid, map_patient, record_study, with the same two
guarantees, consistency and reversibility.

Where it lives, and who can read it. In production de-identification and this
map run inside the hospital. In the PoC's cloud path de-identification is the
first step inside AWS (the ingest task, infra/containers/ingest), so the map is
in AWS too: its own DynamoDB table, readable and writable only by the ingest
task's role. The API's policy has no access to it, so nothing that serves the
worklist can turn a pseudonym back into a patient. Identifiers never reach the
shared, searchable layer (HealthImaging, the worklist table).

Concurrency: several ingest tasks run at once. Every "create if absent" is a
conditional put, and the patient counter is an atomic ADD, so two tasks never
hand out two pseudonyms for one original.

Items, keyed by "k":
  uid#<original UID>          {"v": replacement UID}
  patient#<original id>       {"v": pseudo id, "name", "dob", "sex"}
  study#<original study UID>  {"v": pseudo study UID, "patient", "accession",
                               "pseudo_accession", "date"}
  counter#patient             {"n": patients issued}
"""
from __future__ import annotations

import boto3
from botocore.exceptions import ClientError
from pydicom.uid import generate_uid

from core.providers.aws.config import REGION

UID_ROOT = "1.2.826.0.1.3680043.10.1422."        # as sim/edge/identity.py


class DynamoIdentityMap:
    def __init__(self, table_name: str, region: str = REGION, resource=None):
        self.table = (resource or boto3.resource("dynamodb", region_name=region)).Table(table_name)

    def _get(self, key: str) -> dict | None:
        return self.table.get_item(Key={"k": key}, ConsistentRead=True).get("Item")

    def _put_new(self, item: dict) -> bool:
        """Write only if absent; False if another task got there first."""
        try:
            self.table.put_item(Item=item, ConditionExpression="attribute_not_exists(k)")
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def map_uid(self, original):
        if not original:
            return original
        key = f"uid#{original}"
        hit = self._get(key)
        if hit:
            return hit["v"]
        new = generate_uid(prefix=UID_ROOT)
        return new if self._put_new({"k": key, "v": new}) else self._get(key)["v"]

    def map_patient(self, original_id, name=None, dob=None, sex=None):
        key = f"patient#{original_id or 'UNKNOWN'}"
        hit = self._get(key)
        if hit:
            return hit["v"]
        n = self.table.update_item(
            Key={"k": "counter#patient"}, UpdateExpression="ADD n :one",
            ExpressionAttributeValues={":one": 1}, ReturnValues="UPDATED_NEW")["Attributes"]["n"]
        pseudo = f"AUR-{int(n):06d}"
        item = {"k": key, "v": pseudo, **{f: str(v) for f, v in
                                            (("name", name), ("dob", dob), ("sex", sex)) if v}}
        return pseudo if self._put_new(item) else self._get(key)["v"]

    def record_study(self, original_uid, pseudo_uid, original_patient,
                     original_accession=None, original_date=None):
        pseudo_accession = "ACC" + pseudo_uid.split(".")[-1][-9:]
        item = {"k": f"study#{original_uid}", "v": pseudo_uid,
                "patient": original_patient or "UNKNOWN", "pseudo_accession": pseudo_accession,
                **{f: str(v) for f, v in (("accession", original_accession),
                                          ("date", original_date)) if v}}
        self._put_new(item)                     # first record wins, as INSERT OR IGNORE
        return pseudo_accession
