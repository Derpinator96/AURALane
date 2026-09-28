# infra: the AWS stack (Python CDK)

NON-DIAGNOSTIC; DECISION SUPPORT ONLY.

Creates what the AWS providers in `core/providers/aws/` talk to. us-east-1 only:
HealthImaging is not offered in Mumbai. Costs per resource: `docs/AWS-COSTS.md`.
The full deploy procedure, in order, is `docs/DEPLOY.md` ("The AWS runtime").

Synth needs no AWS credentials and makes no AWS call:

```
pip install -r infra/requirements.txt
cd infra && python app.py            # writes cdk.out/; tests/test_infra.py does the same
```

## What the stack creates, and what it does not

Creates: one S3 bucket, the tables `auralane-worklist` and `auralane-audit`, a
Cognito user pool (Lite) with groups `radiologist` and `admin`, the
HealthImaging import role, the chest inference Lambda (container image), two
SageMaker asynchronous endpoints scaling 0 to 1 (brain MR on ml.m5.2xlarge,
head CT on ml.m5.xlarge) with their models, roles, scaling policies and
alarms, and one managed policy holding exactly what `core/` needs.

Does not create: the HealthImaging datastore. The existing
`293abea3292b4e888cbdf60e3a9ff283` is referenced by ID, so there is nothing
for the stack to collide with and nothing for teardown to delete. Nor does it
host the API or the web app (Render and Vercel, `docs/DEPLOY.md`).

## Context flags

| flag | default | effect |
|---|---|---|
| `-c brain=false` | true | leave the brain endpoint out |
| `-c ct=false` | true | leave the head CT endpoint out |
| `-c brain_instance=TYPE` | ml.m5.2xlarge | brain endpoint instance |
| `-c ct_instance=TYPE` | ml.m5.xlarge | CT endpoint instance |
| `-c chest_provisioned=N` | 0 | N always-warm chest Lambda environments on alias `live` |

On presentation day, one warm chest environment:
`npx cdk deploy Auralane -c chest_provisioned=1`, and back to 0 afterwards
(`-c chest_provisioned=0`). The function is always invoked through its alias
`live` (the `AURALANE_CHEST_FUNCTION` output is `<name>:live`), so the
provisioned environment is the one that answers.

## Before every `cdk deploy`: `python push_images.py`

SageMaker only accepts Docker v2 image manifests; Docker Desktop's containerd
store writes OCI ones. The stack builds the brain and CT images with
`--output type=image,oci-mediatypes=false`, but CDK CLI 2.1143.0 breaks on
that option ("x.replace is not a function"). `push_images.py` builds those two
from CDK's staged context and pushes them under the asset tags, and
`cdk deploy` skips images already in ECR. Delete it once the CLI is fixed.

## The three images: build locally before `cdk deploy`

`cdk deploy` builds these itself; building first catches a broken image
before anything is created. Run from the repository root with Docker running.

```
docker build --platform linux/amd64 -f infra/lambda/chest/Dockerfile   -t auralane-chest .
docker build --platform linux/amd64 -f infra/containers/brain/Dockerfile -t auralane-brain .
docker build --platform linux/amd64 -f infra/containers/ct/Dockerfile    -t auralane-ct .
```

| image | base | notes |
|---|---|---|
| chest (Lambda) | `public.ecr.aws/lambda/python:3.12` | CPU torch 2.14.0 from download.pytorch.org; DenseNet weights baked in; OpenCV swapped for the headless build (the Lambda base has no libGL) |
| brain (SageMaker) | `python:3.12-slim` | CPU torch 2.14.0 and monai 1.6.0; needs `_external/brainmri` with its Git LFS weights (`git lfs pull`) |
| CT (SageMaker) | `python:3.12-slim` | CPU torch 2.14.0 and transformers; the ViT weights (343 MB) downloaded from Hugging Face at build time, never at run time; needs `_external/triagelane-ct` |

Built on 2026-09-28 and smoke-tested offline (`--network none`): chest 2.97 GB
(all 18 outputs from the baked weights), brain 1.92 GB (one BraTS case in
42.6 s), CT 2.68 GB (a 53-slice CQ500 study in 21.9 s). The brain and CT images
share their torch layer. With the build cache, Docker's disk grew to 18 GB:
put it on a drive with 25 GB free first (Docker Desktop, Settings, Resources,
Advanced, Disk image location).

Quick checks after a build, no AWS needed:

```
docker run --rm --entrypoint python auralane-chest -c "import chest_app"
docker run --rm -p 8080:8080 auralane-brain      # then: curl localhost:8080/ping
docker run --rm -p 8080:8080 auralane-ct         # then: curl localhost:8080/ping
```

## Tearing down

```
python infra/teardown.py              # dry run: lists what it would delete
python infra/teardown.py --yes        # empties the bucket, deletes the stack and both endpoint log groups
python infra/teardown.py --yes --bootstrap   # also the CDKToolkit stack
```

Never touches the HealthImaging datastore or any image set in it, including
the smoke-test image set `6f7968d2159b0167b2ba896c78bd0533`; the script does not
create a HealthImaging client. Image sets the pipeline imported stay too, and
the script says so.

## Unverified until something is deployed

- Browser frame fetch straight from HealthImaging (`AURALANE_FRAME_MODE=presigned`).
  The API streams frames by default (`proxy`); `scripts/smoke_aws.py` reports
  whether the presigned URL answers a browser origin with CORS headers.
- `GetDICOMSeriesMetadata` has not been called on this account.
- Cold start and warm cost figures are the estimates in `docs/AWS-COSTS.md`.
