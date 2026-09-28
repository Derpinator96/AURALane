# AWS costs, per billable resource

NON-DIAGNOSTIC; DECISION SUPPORT ONLY.

Everything below is us-east-1 on-demand pricing, read from AWS's own pricing
pages on 2026-09-27 (source named on each line). Nothing has been deployed, so
no figure here is a measured bill. Where a number is an estimate rather than a
published price, it says so and says what it rests on. Check the AWS Pricing
Calculator before deploying; prices change.

"At rest" means deployed and idle. "In use" is what work adds.

## Created by the stack (infra/auralane_stack.py)

| resource | at rest | in use | source |
|---|---|---|---|
| S3 bucket (evidence PNGs kept; transient/, import/, inference/ expire after 1 day) | $0.023 per GB-month of what is stored | request charges per PUT and GET (not read for this page) | S3 Standard rate as quoted in AWS's Centralized Logging cost page |
| DynamoDB `auralane-worklist`, `auralane-audit`, on demand | storage only: the first 25 GB per month free on the Standard table class, per the page's example | $0.625 per million writes, $0.125 per million reads | aws.amazon.com/dynamodb/pricing, on-demand example |
| Cognito user pool, Lite plan, 2 users | $0 | $0 up to 10,000 monthly active users (Lite and Essentials free tier) | aws.amazon.com/cognito/pricing |
| IAM roles (import, SageMaker), managed policy | $0 | $0 | IAM has no charge |
| Chest Lambda, container image, 3,008 MB, x86, no provisioned concurrency | $0 | $0.20 per million requests plus $0.0000166667 per GB-second: at 3,008 MB (2.9375 GB) that is $0.0000490 per second of run time | aws.amazon.com/lambda/pricing |
| Chest Lambda log group, 1-week retention | stored logs only | $0.50 per GB ingested | CloudWatch pricing ("Application & custom logs") |
| Brain SageMaker async endpoint, ml.m5.2xlarge (CPU image), scaling 0 to 1 | $0 per hour at 0 instances | **$0.461 per hour while one instance is up**, plus $0.14 per GB-month for its attached volume and $0.02 per GB of request and response data | $0.461: AWS Price List API, AmazonSageMaker, usage type USE1-Host:ml.m5.2xlarge, read 2026-09-28. $0.14 and $0.02 from the SageMaker pricing page's asynchronous inference example (#11) |
| Head CT SageMaker async endpoint, ml.m5.xlarge (CPU image), scaling 0 to 1 | $0 per hour at 0 instances | **$0.23 per hour while one instance is up**, plus the same volume and data charges | AWS Price List API, USE1-Host:ml.m5.xlarge, read 2026-09-28 |
| Cloud ingest: one Fargate task per arrival, 2 vCPU and 4 GB, started by EventBridge | $0: no task runs at rest | $0.09874 per task-hour (2 x $0.04048 per vCPU-hour + 4 x $0.004445 per GB-hour): a chest study measured 24.2 s in the task, about $0.0007; a 620-slice brain MR is minutes, a few cents | vCPU rate: AWS Price List API, USE1-Fargate-vCPU-Hours:perCPU, read 2026-09-28. Memory rate: Fargate pricing page, NOT re-read |
| Ingest VPC: public subnets, no NAT gateway | $0 | a public IPv4 address per running task, $0.005 per hour | VPC pricing page, NOT re-read; no NAT gateway is created, so no NAT charge |
| EventBridge rule on the bucket's events, and the identity table (on demand) | $0 at rest | pennies at demo volume | EventBridge and DynamoDB on-demand pricing, NOT re-read |
| Demo corpus in S3 (corpus/, 44 studies, about 250 MB) | about $0.006 per month | copies per simulated arrival are requests only | S3 Standard rate above |
| CloudWatch alarms for the CT endpoint: 1 in the stack, 2 from its target tracking | about $0.30 per month | same | as the brain alarms below |
| CloudWatch alarms: 1 in the stack, plus the 2 that target-tracking scaling creates for itself | $0.10 per alarm per month each, so about $0.30 | same | NOT re-read in this build; CloudWatch's billing guide confirms alarms are billed per alarm-metric but the page fetched did not show the rate |

### What a brain job costs, and why "scale to zero" is not free per job

At rest the endpoint runs 0 instances and costs nothing per hour. A job wakes
it: the step policy adds one instance when `HasBacklogWithoutCapacity` fires,
and target tracking removes it once the backlog has been empty long enough
(scale-in cooldown 600 s in the stack; target tracking also waits for its own
low alarm). Estimate, not measured: each wake keeps an instance up for roughly
20 to 30 minutes including start-up, about $0.15 to $0.23 at $0.461 per hour
for brain and $0.08 to $0.12 at $0.23 per hour for CT.
Back-to-back jobs share one wake.

The brain endpoint was ml.g4dn.xlarge ($0.7364 per hour) until the image
became CPU-only: the CUDA base does not fit the build machine's Docker disk
(infra/containers/brain/Dockerfile). `-c brain_instance=ml.g4dn.xlarge` still
deploys it on a GPU instance, where the CPU image runs without using the GPU.

After `cdk deploy` each endpoint starts with 1 instance (SageMaker creates the
variant with an initial count of 1) and only scales in to 0 once the idle
policy fires, so expect the first 20 to 30 minutes after a deploy to be billed.

### The chest cold start, flagged and not solved

The warm figure we quote locally is ~250 ms for the forward pass alone on a
desktop CPU; with Grad-CAM (the platform default) this build container measured
4.5 s for the backward pass and 7.4 s for a full chest ingest (docs/LATENCY.md
has the per-step table once it is re-run). A Lambda invocation after idle adds
a cold start on top of that.

Estimate: **10 to 30 seconds** before the first prediction. Not measured:
nothing is deployed, and this build machine could not even build the image
(the Lambda base image and the CPU torch wheels are both blocked by its
network policy). The reasoning:

- Image size. The Python packages the image installs, other than torch, occupy
  about 710 MB installed on this machine (scipy 143 MB, opencv-headless 160 MB
  pulled in by grad-cam, pandas 71 MB and scikit-learn 49 MB pulled in by
  torchxrayvision and grad-cam, numpy 71 MB, and the rest). CPU torch adds
  several hundred MB more (its size could not be measured here; the CUDA
  build on this machine is 1.2 GB without its NVIDIA libraries). Well over 1 GB
  uncompressed, on top of the base image.
- Lambda loads container images lazily, so a cold start pays for the parts of
  that image the process actually reads: importing torch, torchvision, scipy,
  scikit-image, opencv and pandas, then loading the 28 MB DenseNet weights and
  running the first forward and backward pass.
- The team's earlier figure of 5 to 15 s for a PyTorch Lambda was also an
  estimate, and did not count the Grad-CAM dependencies (opencv, scikit-learn,
  matplotlib) this image carries; hence the wider range.

Provisioned concurrency removes it, at a price:

| provisioned environments | per hour | per 30-day month | plus |
|---|---|---|---|
| 1 at 3,008 MB | 2.9375 GB x 3,600 s x $0.0000041667 = $0.0441 | $31.72 | duration at $0.0000097222 per GB-second instead of $0.0000166667 |

Source: the provisioned-concurrency section of aws.amazon.com/lambda/pricing
($0.0000041667 per GB-second provisioned, $0.0000097222 per GB-second duration,
us-east-1 x86). The stack deploys with none; `-c chest_provisioned=1` adds one.
Cheaper middle ground, not built: provisioned concurrency only during reading
hours, on a schedule. This is a decision for the team, not a default.

## Not created by the stack, but billed because of it

| resource | at rest | in use | source |
|---|---|---|---|
| HealthImaging datastore 293abea3292b4e888cbdf60e3a9ff283 (existing, kept) | $0.105 per GB-month Frequent Access, $0.006 Archive Instant Access after 30 days unread; each image set billed at 5 MB minimum and 30 days minimum | imports free; $0.005 per 1,000 API requests; the frame requests a viewer makes count as API requests | aws.amazon.com/healthimaging/pricing, its us-east-1 examples |
| ECR images (chest Lambda image, brain SageMaker image), in the CDK bootstrap repository | $0.10 per GB-month of image stored; sizes not measured (see above: chest well over 1 GB; the brain image starts from a CUDA PyTorch runtime and is larger) | pulls within the region are free | aws.amazon.com/ecr/pricing |
| CDK bootstrap stack (CDKToolkit): staging bucket and that ECR repository | as S3 and ECR above | | created by `cdk bootstrap`, removed only by `infra/teardown.py --bootstrap` |
| SageMaker endpoint log group, created by SageMaker | stored logs | $0.50 per GB ingested | CloudWatch pricing; deleted by infra/teardown.py |
| Data transfer to the browser (frames, overlays) | | 100 GB per month free across services; beyond that, internet egress rates (not read for this page) | HealthImaging pricing page, Data Transfer |

One HealthImaging figure for scale, computed from the prices above and the
smoke test: a chest study stored 458,999 bytes of HTJ2K but is billed at the
5 MB minimum, so it costs 5 / 1,024 GB x $0.105 = $0.00051 per month.

## Summary for the decision

- Idle, with nothing provisioned: pennies per month. S3 and DynamoDB storage for
  a demo-sized worklist, ECR image storage (the largest line, at $0.10 per GB),
  and about $0.30 of alarms.
- The brain endpoint: $0.461 per hour while warm, 0 while scaled in.
- The head CT endpoint: $0.23 per hour while warm, 0 while scaled in.
- The chest Lambda: per invocation only, unless provisioned concurrency is
  chosen ($31.72 per month for one warm environment).
