"""Build and push the SageMaker images under the tags cdk deploy expects.

    cd infra && python push_images.py && npx cdk deploy Auralane

Why: SageMaker accepts only Docker v2 manifests, and Docker with the containerd
image store writes OCI ones, so the stack builds those assets with
--output type=image,oci-mediatypes=false. The CDK CLI (2.1143.0) passes that
option wrongly: it maps each output to a one-element array and the command
line fails with "x.replace is not a function". cdk deploy skips any asset whose
tag already exists in ECR, so this script builds those assets itself, from
CDK's own staged build context, and pushes them first.

TODO: delete this script once the CDK CLI passes dockerOutputs correctly.

Needs Docker and credentials that can push to the CDK bootstrap repository.
Creates no AWS resource other than the images themselves.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import boto3

HERE = Path(__file__).resolve().parent
OUT = HERE / "cdk.out"
REGION = "us-east-1"


def run(cmd: list[str], **kw) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def main() -> int:
    # Synth into infra/cdk.out, where cdk deploy synthesises too. Without
    # CDK_OUTDIR a bare `python app.py` writes to a temporary directory, and
    # this script would read a stale manifest.
    run([sys.executable, "app.py"], cwd=HERE, env={**os.environ, "CDK_OUTDIR": str(OUT)})
    manifest = json.loads((OUT / "Auralane.assets.json").read_text())
    account = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]
    ecr = boto3.client("ecr", region_name=REGION)
    logged_in = False
    for asset_hash, asset in manifest.get("dockerImages", {}).items():
        src = asset["source"]
        if not src.get("dockerOutputs"):
            continue                        # cdk deploy builds these itself
        for dest in asset["destinations"].values():
            repo = dest["repositoryName"].replace("${AWS::AccountId}", account) \
                                         .replace("${AWS::Region}", REGION)
            tag = dest["imageTag"]
            found = ecr.describe_images(repositoryName=repo, imageIds=[{"imageTag": tag}]) \
                if _exists(ecr, repo, tag) else None
            uri = f"{account}.dkr.ecr.{REGION}.amazonaws.com/{repo}:{tag}"
            if found:
                print(f"already in ECR: {uri}")
                continue
            if not logged_in:
                token = ecr.get_authorization_token()["authorizationData"][0]
                user, password = base64.b64decode(token["authorizationToken"]).decode().split(":", 1)
                run(["docker", "login", "--username", user, "--password-stdin", token["proxyEndpoint"]],
                    input=password.encode())
                logged_in = True
            build = ["docker", "build", "--tag", uri, "--file", src.get("dockerFile", "Dockerfile")]
            if src.get("platform"):
                build += ["--platform", src["platform"]]
            for o in src["dockerOutputs"]:
                build += ["--output", o]
            run(build + ["."], cwd=OUT / src["directory"],
                env={**os.environ, "BUILDX_NO_DEFAULT_ATTESTATIONS": "1"})
            run(["docker", "push", uri])
    return 0


def _exists(ecr, repo: str, tag: str) -> bool:
    try:
        ecr.describe_images(repositoryName=repo, imageIds=[{"imageTag": tag}])
        return True
    except ecr.exceptions.ImageNotFoundException:
        return False


if __name__ == "__main__":
    sys.exit(main())
