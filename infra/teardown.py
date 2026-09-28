"""Remove everything the Auralane stack created. Keeps the HealthImaging datastore.

    python infra/teardown.py            # dry run: prints what it would delete
    python infra/teardown.py --yes      # deletes it
    python infra/teardown.py --yes --bootstrap   # also the CDKToolkit stack

What it deletes, in order:
  1. every object in the stack's S3 bucket (CloudFormation cannot delete a
     bucket that is not empty)
  2. the stack itself: bucket, tables, user pool, roles, Lambda and its log
     group, SageMaker endpoint, config, model, scaling, alarm, policy
  3. the SageMaker endpoint's log group, which SageMaker creates outside the
     stack (/aws/sagemaker/Endpoints/<name>)
  4. with --bootstrap only: the CDKToolkit stack that `cdk bootstrap` made, after
     emptying its staging bucket and container-asset repository. Leave it if
     anything else in the account was deployed with CDK.

What it never touches: the HealthImaging datastore
293abea3292b4e888cbdf60e3a9ff283 and every image set in it, including the
smoke-test image set 6f7968d2159b0167b2ba896c78bd0533. This script does not
create a HealthImaging client at all. Image sets the pipeline imported while
the stack was up also stay in the datastore; they are listed for the operator
to delete by hand if wanted.

Region is us-east-1. Run it with the credentials that deployed the stack.
"""
from __future__ import annotations

import argparse
import sys

import boto3

REGION = "us-east-1"
STACK = "Auralane"
KEEP = {"datastore": "293abea3292b4e888cbdf60e3a9ff283",
        "image set": "6f7968d2159b0167b2ba896c78bd0533"}


def plan(cfn, stack: str = STACK) -> dict:
    """What would be deleted, read from the stack. Makes read calls only."""
    try:
        desc = cfn.describe_stacks(StackName=stack)["Stacks"][0]
    except cfn.exceptions.ClientError as e:
        if "does not exist" in str(e):
            return {"stack": None}
        raise
    outputs = {o.get("Description", o["OutputKey"]): o["OutputValue"]
               for o in desc.get("Outputs", [])}
    resources = []
    for page in cfn.get_paginator("list_stack_resources").paginate(StackName=stack):
        resources += [(r["ResourceType"], r.get("PhysicalResourceId", ""))
                      for r in page["StackResourceSummaries"]]
    for kind, physical in resources:
        if kind.startswith("AWS::HealthImaging") or KEEP["datastore"] in physical:
            raise RuntimeError(f"stack {stack} lists {kind} {physical}; refusing: the datastore "
                               f"is not the stack's to delete")
    endpoints = [outputs[k] for k in ("AURALANE_BRAIN_ENDPOINT", "AURALANE_CT_ENDPOINT")
                 if outputs.get(k)]
    return {"stack": stack, "bucket": outputs.get("AURALANE_BUCKET"), "resources": resources,
            "log_groups": [f"/aws/sagemaker/Endpoints/{e}" for e in endpoints]}


def empty_bucket(s3, bucket: str) -> int:
    n = 0
    for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket):
        batch = [{"Key": o["Key"], "VersionId": o["VersionId"]}
                 for o in page.get("Versions", []) + page.get("DeleteMarkers", [])]
        if batch:
            s3.delete_objects(Bucket=bucket, Delete={"Objects": batch, "Quiet": True})
            n += len(batch)
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--yes", action="store_true", help="delete; without it, only print the plan")
    ap.add_argument("--bootstrap", action="store_true",
                    help="also delete the CDKToolkit bootstrap stack")
    args = ap.parse_args(argv)
    session = boto3.Session(region_name=REGION)
    cfn = session.client("cloudformation")
    p = plan(cfn)

    print(f"Keeping: HealthImaging datastore {KEEP['datastore']} and image set "
          f"{KEEP['image set']} (never touched by this script).")
    if p["stack"] is None:
        print(f"Stack {STACK} does not exist in {REGION}; nothing of it to delete.")
    else:
        print(f"Stack {STACK}: {len(p['resources'])} resources")
        for kind, physical in p["resources"]:
            print(f"  {kind:45} {physical}")
        print(f"Bucket to empty first: {p['bucket']}")
        for g in p["log_groups"]:
            print(f"Log group outside the stack: {g}")
    if args.bootstrap:
        print("Also: the CDKToolkit stack, its staging bucket and asset repository.")
    if not args.yes:
        print("Dry run. Re-run with --yes to delete.")
        return 0

    if p["stack"]:
        if p["bucket"]:
            print(f"emptied {empty_bucket(session.client('s3'), p['bucket'])} objects")
        cfn.delete_stack(StackName=STACK)
        cfn.get_waiter("stack_delete_complete").wait(StackName=STACK)
        print(f"deleted stack {STACK}")
        logs = session.client("logs")
        for g in p["log_groups"]:
            try:
                logs.delete_log_group(logGroupName=g)
                print(f"deleted log group {g}")
            except logs.exceptions.ResourceNotFoundException:
                pass
    if args.bootstrap:
        tk = plan(cfn, "CDKToolkit")
        if tk["stack"]:
            ecr, s3 = session.client("ecr"), session.client("s3")
            for kind, physical in tk["resources"]:
                if kind == "AWS::S3::Bucket":
                    empty_bucket(s3, physical)
                if kind == "AWS::ECR::Repository":
                    ids = [i for page in ecr.get_paginator("list_images").paginate(
                        repositoryName=physical) for i in page["imageIds"]]
                    for i in range(0, len(ids), 100):
                        ecr.batch_delete_image(repositoryName=physical, imageIds=ids[i:i + 100])
            cfn.delete_stack(StackName="CDKToolkit")
            cfn.get_waiter("stack_delete_complete").wait(StackName="CDKToolkit")
            print("deleted stack CDKToolkit")
    print("HealthImaging image sets imported while the stack was up are still in the "
          "datastore; delete them by hand if they should go.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
