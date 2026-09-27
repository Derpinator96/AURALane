# infra: the AWS stack (Python CDK)

NON-DIAGNOSTIC; DECISION SUPPORT ONLY.

Creates what the AWS providers in `core/providers/aws/` talk to. us-east-1 only:
HealthImaging is not offered in Mumbai. Costs per resource: `docs/AWS-COSTS.md`.

Nothing here has been deployed. Synth needs no AWS credentials and makes no
AWS call:

```
pip install -r infra/requirements.txt
cd infra && python app.py            # writes cdk.out/; tests/test_infra.py does the same
```

## What the stack creates, and what it does not

Creates: one S3 bucket, the tables `auralane-worklist` and `auralane-audit`, a
Cognito user pool (Lite) with groups `radiologist` and `admin`, the
HealthImaging import role, the chest inference Lambda (container image), the
brain SageMaker asynchronous endpoint (ml.g4dn.xlarge, scaling 0 to 1) with its
model, role, scaling policies and alarm, and one managed policy holding exactly
what `core/` needs.

Does not create: the HealthImaging datastore. The existing
`293abea3292b4e888cbdf60e3a9ff283` is referenced by ID, so there is nothing
for the stack to collide with and nothing for teardown to delete. Nor does it
host the API or the web app; those are outside this stack.

Context flags: `-c brain=false` leaves the SageMaker endpoint out.
`-c chest_provisioned=N` adds N provisioned environments to the chest Lambda
(default 0; see the cold-start section of `docs/AWS-COSTS.md`).

## Deploying: the commands, what each creates, what it costs

Run none of these without deciding to. Credentials: the IAM user that owns the
account's AWS resources, region us-east-1.

1. `npx cdk bootstrap aws://<account>/us-east-1`
   Creates the CDKToolkit stack: an S3 staging bucket, an ECR repository for
   container assets, and the roles CDK deploys with. Costs S3 and ECR storage
   for whatever assets are pushed ($0.10 per GB-month for images).

2. `cd _external/brainmri && git lfs pull`
   Not an AWS command. The brain image copies the SegResNet weights; without
   them every brain job fails loudly at model load. Skip if deploying with
   `-c brain=false`.

3. `cd infra && npx cdk diff`
   Read only: shows what deploy would change.

4. `cd infra && npx cdk deploy Auralane` (optionally `-c brain=false`,
   `-c chest_provisioned=1`)
   Builds both images locally with Docker, pushes them to the bootstrap ECR
   repository, and creates every resource listed above. Costs as in
   `docs/AWS-COSTS.md`; note the SageMaker endpoint starts with one instance
   ($0.7364 per hour) until its idle scale-in fires.

5. Users, in the pool the stack output names:
   `aws cognito-idp admin-create-user --user-pool-id <pool> --username radiologist --message-action SUPPRESS`
   `aws cognito-idp admin-set-user-password --user-pool-id <pool> --username radiologist --password <password> --permanent`
   `aws cognito-idp admin-add-user-to-group --user-pool-id <pool> --username radiologist --group-name radiologist`
   and the same for `admin`. No charge under 10,000 monthly active users.

6. `aws iam attach-user-policy --user-name <user> --policy-arn <AURALANE_APP_POLICY_ARN output>`
   Gives whoever runs the API exactly the permissions `core/` uses. No charge.

7. Environment from the stack outputs (each output's description is the
   variable name):
   `aws cloudformation describe-stacks --stack-name Auralane --query "Stacks[0].Outputs[].[Description,OutputValue]" --output text`
   then export each pair and run `AURALANE_RUNTIME=aws python -m core.run serve`.

## Tearing down

```
python infra/teardown.py              # dry run: lists what it would delete
python infra/teardown.py --yes        # empties the bucket, deletes the stack and the endpoint log group
python infra/teardown.py --yes --bootstrap   # also the CDKToolkit stack
```

Never touches the HealthImaging datastore or any image set in it, including
the smoke-test image set `6f7968d2159b0167b2ba896c78bd0533`; the script does not
create a HealthImaging client. Image sets the pipeline imported stay too, and
the script says so.

## Unverified until something is deployed

- Browser frame fetch: `frame_url` returns a SigV4 presigned DICOMweb URL. That
  HealthImaging accepts query-string signing on DICOMweb, and answers a browser
  on another origin with CORS headers, is untested. Test with one study first.
- Bearer tokens: HealthImaging supports OIDC for DICOMweb through a Lambda
  authorizer. If a Cognito token works there, the signing path can go.
- `GetDICOMSeriesMetadata` has not been called on this account.
- Both container images have not been built: the Lambda base image and the CPU
  torch wheels were unreachable from the build machine. Their Dockerfiles are
  written against the published base images and have not run.
- Cold start and warm cost figures are the estimates in `docs/AWS-COSTS.md`.
