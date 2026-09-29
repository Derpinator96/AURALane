"""Give audit events written before the by_day index existed their `day` attribute.

    python scripts/backfill_audit_day.py --stack Auralane           # AWS
    python scripts/backfill_audit_day.py --stack Auralane --dry-run

The audit table's by_day index (partition `day`, sort `event_id`) only holds items
that carry `day`, which append_audit writes from now on. Older events have none,
so the recent-events queries would not see them. This scans the table once and
sets `day` (the first ten characters of the event time) on each item that lacks
it. It changes no other attribute. The application's own role cannot scan or
update the audit table; run this with the credentials that deployed the stack.

NON-DIAGNOSTIC; DECISION SUPPORT ONLY.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stack", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    import os

    import boto3

    from core.run import load_stack
    load_stack(args.stack)
    table = f"{os.environ.get('AURALANE_TABLE_PREFIX') or 'auralane'}-audit"
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    seen = updated = 0
    kwargs = {"TableName": table,
              "ProjectionExpression": "#s, event_id, #d, #a",
              "ExpressionAttributeNames": {"#s": "study", "#d": "day", "#a": "at"}}
    while True:
        page = ddb.scan(**kwargs)
        for item in page["Items"]:
            seen += 1
            if "day" in item:
                continue
            at = (item.get("at") or {}).get("S") or item["event_id"]["S"]
            if not args.dry_run:
                ddb.update_item(TableName=table,
                                Key={"study": item["study"], "event_id": item["event_id"]},
                                UpdateExpression="SET #d = :d",
                                ExpressionAttributeNames={"#d": "day"},
                                ExpressionAttributeValues={":d": {"S": at[:10]}})
            updated += 1
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    print(f"{table}: {seen} events read, {updated} {'would get' if args.dry_run else 'given'} a day")
    return 0


if __name__ == "__main__":
    sys.exit(main())
