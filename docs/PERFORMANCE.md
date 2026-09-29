# Performance of the AWS runtime

What was slow, what was measured, what changed, and what to run after a deploy.
Every figure below comes from `scripts/bench_api.py`; nothing is estimated.

## How it was measured

`scripts/bench_api.py` signs in and times the requests the client makes: worklist
load, study open, series metadata, the first 10 frames of a chest study and of a brain
MR series (six at a time, as the viewer fetches them), and the admin pipeline. Each
request is timed end to end and, when the response has a `Server-Timing` header, split
into the server's total and its time in DynamoDB, HealthImaging, S3 and auth.

    python scripts/bench_api.py --base https://auralane-api.onrender.com \
        --user <name> --password-env AURALANE_BENCH_PASSWORD \
        --admin-user <name> --admin-password-env AURALANE_BENCH_ADMIN_PASSWORD

**Where these numbers were taken.** The tables below are from the API run on the
development laptop (India) against the real AWS resources in us-east-1, with
development tokens: the deployed Render API needs a Cognito sign-in, and the run was not
given credentials. A DynamoDB or HealthImaging call therefore costs a round trip of about
250 ms here, against a few milliseconds from Render, which is in Virginia. Compare the
two tables with each other, not with a stopwatch on the deployed site. Run the command
above against the deployed API before and after the deploy to get its own numbers.

`GET /api/health` on the free Render instance, 5 calls from the same laptop before any
change: 374, 448, 496, 748 and 814 ms.

## Frames

The direct path already existed and is the default (`AURALANE_FRAME_MODE` unset, and
`presigned` in `render.yaml`): the browser fetches each frame straight from HealthImaging
with a presigned SigV4 URL. Checked live on 2026-09-29: HealthImaging answers the CORS
preflight (`allow-origin: *`, `allow-headers: accept`), so no frame service and no proxy
is needed. If a deployed API is on `AURALANE_FRAME_MODE=proxy` in the Render dashboard,
frames still go through Render decoded in Python; unset it. `bench_api.py` prints
"via the API" or "direct from the datastore" for the frames it fetched.

What was left on the table was the bytes. Asked for the default media type,
HealthImaging decodes the stored HTJ2K itself and sends uncompressed pixels. Asked for
HTJ2K it sends what it stored:

| frame | uncompressed (before) | HTJ2K (after) |
|---|---:|---:|
| chest radiograph | 1.05 MB | 0.34 MB |
| brain MR slice | 0.12 MB | 0.05 MB |

The client now sends `Accept: multipart/related; type="image/jphc";
transfer-syntax=1.2.840.10008.1.2.4.202` for frames whose header says HTJ2K and whose
URL is HealthImaging's, and Cornerstone decodes them in its web workers (checked in the
browser: chest and brain MR series render). The viewer loads the middle slice first, then
the rest of the series in the background, nearest first: two requests for what the reader
is looking at and four for the background, six at most.

## Before and after

Median of 5 calls, plus the first call, which is the cold one (nothing cached on either
side). "Before" is `main` at d796721, "after" is this branch, each on a freshly started
API. Frames: before with the default Accept, after with HTJ2K.

| request | before, first call ms | before, median ms | after, first call ms | after, median ms |
|---|---:|---:|---:|---:|
| health | 31 | 2 | 20 | 5 |
| worklist (49 studies) | 3447 | 617 | 764 | 16 |
| study open (chest) | 2810 | 784 | 2252 | 13 |
| series metadata (chest) | 1198 | 733 | 1038 | 11 |
| study open (brain MR) | 3264 | 502 | 2653 | 16 |
| series metadata (brain MR, 155 instances) | 2952 | 1638 | 2498 | 390 |
| first frame of a chest study (1 frame) | 2761 | 2761 | 3921 | 3921 |
| first 10 frames of a brain MR series | 2977 | 2977 | 1873 | 1873 |
| admin pipeline | 11173 | 16 | 15351 | 17 |

Read this table with three things in mind.

- The medians are what a reader sees after the first open: caches for the worklist (3 s,
  shared by every user), the study payload, the row, and series metadata make repeats
  cost single-digit milliseconds. The cold column is the honest cost of a cold API.
- The cold study-open and series numbers are HealthImaging's own metadata calls for
  studies ingested before this branch. Studies ingested by it get a slim series index in
  S3 (`evidence/<study>/series_index.json.gz`) and never ask HealthImaging for metadata.
  Run `scripts/backfill_series_index.py --stack Auralane` once to give the existing
  studies theirs.
- The admin pipeline is unchanged until the stack is deployed: the `by_day` index on the
  audit table does not exist yet, so the API falls back to one query per study, as
  before. After `cdk deploy` and `scripts/backfill_audit_day.py`, it is a query per day.
- One frame from HealthImaging took 1.7 to 4 s from this laptop on every run, before and
  after, with either media type. That is HealthImaging's latency, not the API's, and it
  varies from run to run: the chest-frame row is slower after (3.9 s against 2.8 s) and the
  brain row faster (1.9 s against 3.0 s) for that reason, not because of the change. The
  saving is in bytes (three times fewer), in fetching the series in the background instead
  of on scroll, and in the API no longer being in the path.
- The cold admin pipeline reads slower after (15 s against 11 s) for the same reason:
  both runs used the per-study fallback and the difference is the network.

## What changed

- `Server-Timing` on every response, and the projection, cache and index changes below.
- Worklist: only the list's columns are read (a DynamoDB `ProjectionExpression`), one
  scan is shared by every user for 3 s and dropped at once by any write through the API,
  and the response carries an `ETag`, answering 304 when nothing changed. The client
  refreshes every 10 s, only while the tab is visible.
- Study open: the `opened_at` write and its audit event run after the response. The study
  payload is cached per study and reader for 90 s and dropped by any write to that row;
  the row for 30 s. Evidence links are signed without a HEAD request each.
- Series metadata: cached per image set in memory, and read from the S3 index when the
  study has one.
- Audit: a global secondary index `by_day` (partition `day`, sort `event_id`) on the audit
  table; the audit screens, a reader's history and the pipeline view read the last 14 (7
  for the pipeline) days in one query per day.
- The reader list is refreshed in the background, and the API warms its connections, the
  DynamoDB table check, the reader list and the worklist at start.
- CORS preflights are cached for a day, boto3 clients use a 32 connection pool with
  keep-alive, DynamoDB numbers are converted without a JSON round trip.
- The client loads NiiVue when a 3D view first opens (it was on every page), and keeps
  the last six study payloads and de-duplicates identical requests in flight.

Results are the same: same lanes, same ordering, same access rules, same audit events.
The pipeline and admin views read a shorter window of the audit trail (7 days) than
before (all of it).

## After the deploy

    cd infra && python push_images.py
    npx cdk deploy Auralane --asset-parallelism=false --require-approval never
    python scripts/backfill_audit_day.py --stack Auralane
    python scripts/backfill_series_index.py --stack Auralane

The deploy creates the `reports` table and the `by_day` index, and rebuilds the chest
Lambda (per-finding Grad-CAM) and the ingest task. An API deployed before the stack still
works: study open finds no reports, saving a draft says the reports store is not deployed
yet, and the audit screens use one query per study.

## Render

Measured: `/api/health` 374 to 814 ms per call from the laptop on the free instance
(the same order as the 290 to 645 ms seen earlier). Pixels no longer pass through the API,
so what is left on it is small JSON, and its CPU matters much less than it did.

What the paid Starter plan would change, from Render's published plans (check the
current pricing page before deciding): the service stays awake instead of spinning down
after 15 minutes idle, so the first request after a quiet period no longer waits for a
cold start, and it gets a dedicated CPU share instead of the free tier's shared fraction;
memory is 512 MB on both. The free tier's 750 instance hours a month cover one always-on
service, not the two in `render.yaml`; keep the uptime monitor on the API's
`/api/health` only (`docs/DEPLOY.md`, "Sleep, and the uptime monitor"). This change was
not made; the plan is the owner's decision.

## Chest Grad-CAM cost

A Grad-CAM for the top findings is computed where the chest model runs. Measured locally
(4 CPU threads, torch 2.14), extra time per study over the driver's own map: 1 finding
1.1 s in all, 2 findings 2.1 s, 3 findings 3.7 s, 5 findings 4.7 s. Five findings added
3.9 s, over the 3 s budget, so the default is 3 findings (2.6 s extra).
`AURALANE_GRADCAM_FINDINGS` changes it, and the Lambda records the time it took in
`evidence.gradcam_findings_seconds`, which is the number to check after deploying (Lambda
at 3,008 MB has about 1.7 vCPU, fewer than the 4 threads used here).
