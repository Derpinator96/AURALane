# Deploy

NON-DIAGNOSTIC; DECISION SUPPORT ONLY.

Three pieces, three hosts:

| | where | what it runs |
|---|---|---|
| client | Vercel, `https://aura-lane.vercel.app` | the built React app from `client/`; unchanged |
| API | Render, `auralane-api`, virginia | `python -m core.run serve`, `AURALANE_RUNTIME=aws`: HealthImaging, DynamoDB, S3, Cognito. Never runs a model |
| models | AWS us-east-1 (`infra/`) | chest on Lambda, brain MR and head CT on SageMaker asynchronous endpoints |
| fallback API | Render, `auralane-preview`, virginia | the fixture runtime, synthetic rows, no AWS. Section "The fixture preview" below |

Ingest runs where the studies are (in production the hospital's edge agent;
here, your machine): it de-identifies locally, then talks to AWS. The
deployed API only reads the worklist and serves the viewer.

## The AWS runtime, in order

Every command from the repository root unless it says `cd infra`. Region
us-east-1 throughout. Costs per resource: `docs/AWS-COSTS.md`; the totals are
in the table at the end of this section.

### 1. Build the three images locally (no AWS)

```
docker build --platform linux/amd64 -f infra/lambda/chest/Dockerfile   -t auralane-chest .
docker build --platform linux/amd64 -f infra/containers/brain/Dockerfile -t auralane-brain .
docker build --platform linux/amd64 -f infra/containers/ct/Dockerfile    -t auralane-ct .
```

Check: each ends with `naming to docker.io/library/auralane-...`. The three
images are 7.6 GB, and with the build cache Docker's disk grew to 18 GB on the
build machine, leaving C: with 1.2 GB. Before building, move Docker's disk to a
drive with 25 GB free: Docker Desktop, Settings, Resources, Advanced, Disk
image location. The brain image needs `_external/brainmri` with its Git LFS
weights; the CT image needs `_external/triagelane-ct`.

### 2. Bootstrap CDK, once per account and region

```
pip install -r infra/requirements.txt
cd infra && npx cdk bootstrap aws://294488969610/us-east-1
```

Check: a `CDKToolkit` stack in CloudFormation, status `CREATE_COMPLETE`.

### 3. Deploy the stack

With the venv activated (CDK runs `python app.py`, which needs `aws_cdk`):

```
cd infra && python push_images.py
cd infra && npx cdk deploy Auralane --asset-parallelism=false --require-approval never
```

`push_images.py` builds the brain and CT images with Docker v2 manifests and
pushes them under the tags `cdk deploy` looks for. SageMaker rejects the OCI
manifests Docker Desktop writes by default ("Unsupported manifest media type"),
and CDK CLI 2.1143.0 fails on the option that fixes it ("x.replace is not a
function"); `cdk deploy` skips any image already in ECR, so it never reaches
that code. Run it again whenever a model image changes. `--asset-parallelism=false`
pushes one image at a time: in parallel, the chest push failed once.

Flags, all optional: `-c brain=false`, `-c ct=false` leave an endpoint out;
`-c chest_provisioned=1` keeps one chest environment warm (presentation day
only). `cdk deploy` builds and pushes the chest image, then creates
everything. Check: it prints the outputs, one per environment variable.

Save the outputs as a file you will source (never commit it):

```
aws cloudformation describe-stacks --stack-name Auralane --query "Stacks[0].Outputs[].[Description,OutputValue]" --output text
```

Each line is `NAME value`. Keep `AURALANE_APP_POLICY_ARN` for step 5.

### 4. Cognito users

```
aws cognito-idp admin-create-user --user-pool-id <AURALANE_COGNITO_POOL_ID> --username radiologist --message-action SUPPRESS
aws cognito-idp admin-set-user-password --user-pool-id <AURALANE_COGNITO_POOL_ID> --username radiologist --password <password> --permanent
aws cognito-idp admin-add-user-to-group --user-pool-id <AURALANE_COGNITO_POOL_ID> --username radiologist --group-name radiologist
```

Then the same three for `admin` with `--group-name admin`. The password must
meet the pool's default policy (8 or more characters, upper and lower case, a
number, a symbol).

### 5. A scoped IAM user for the API

```
aws iam create-user --user-name auralane-api
aws iam attach-user-policy --user-name auralane-api --policy-arn <AURALANE_APP_POLICY_ARN>
aws iam create-access-key --user-name auralane-api
```

The policy holds exactly what `core/` calls, nothing else. The access key is
shown once; it goes into Render (step 6) and into your shell for ingest
(step 7). Never your admin key.

### 6. Moving the API to virginia, and pointing it at AWS

Render cannot change a service's region in place, so the singapore service is
replaced. Copy these from the old service before deleting it: nothing else on
it matters (the fixture rows live in the repository).

| copy | from | to |
|---|---|---|
| custom domain, if you added one | old service, Settings | new `auralane-api` |
| the uptime monitor's URL | UptimeRobot | new service URL |
| `AURALANE_DEV_PASSWORD` | old service | new `auralane-preview` (the fallback) |

Then:

1. Delete the old singapore `auralane-api` service (Settings, Delete Service),
   so its name and URL are free.
2. Dashboard, New, Blueprint, this repository. `render.yaml` creates both
   `auralane-api` (aws) and `auralane-preview` (fixture), both in virginia.
3. At the prompts for `auralane-api`: `AWS_ACCESS_KEY_ID` and
   `AWS_SECRET_ACCESS_KEY` from step 5, `AWS_REGION` = `us-east-1`, and every
   `AURALANE_*` value from the stack outputs in step 3. For
   `auralane-preview`: the development password.
4. If Render gives either service a different URL than the one in
   `render.yaml` (`AURALANE_PUBLIC_URL`), change it there and push.

Check: `https://auralane-api.onrender.com/api/health` returns
`{"runtime":"aws"}`, and `https://auralane-preview.onrender.com/api/health`
returns `{"runtime":"fixture"}`. A deploy log ending in
`AURALANE_RUNTIME=aws serve needs ...` names the missing output.

Vercel stays as it is: its `VITE_API_BASE` already points at
`https://auralane-api.onrender.com`. If the URL changed in step 4, update
`VITE_API_BASE` and redeploy. To demo the fallback, point `VITE_API_BASE` at
`auralane-preview` and redeploy (about a minute).

### 7. Ingest, and the end-to-end smoke test

In your shell, with the scoped key and the stack outputs exported:

```
export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... AWS_REGION=us-east-1
export AURALANE_RUNTIME=aws AURALANE_BUCKET=... AURALANE_IMPORT_ROLE_ARN=... \
       AURALANE_COGNITO_POOL_ID=... AURALANE_COGNITO_CLIENT_ID=... \
       AURALANE_CHEST_FUNCTION=... AURALANE_BRAIN_ENDPOINT=... AURALANE_CT_ENDPOINT=...
export AURALANE_SITE_STATE=Chhattisgarh        # the site's state, for the chest regional prior
python scripts/smoke_aws.py --api https://auralane-api.onrender.com --user radiologist --password <password>
```

It ingests one chest, one brain and one head CT study, then reads the
deployed worklist and prints each study with its lane. `SMOKE PASSED` means
all three reached it: that is done. It also fetches one frame through the
viewer's URL and says whether HealthImaging's presigned URL answers a browser
origin with CORS headers. Frames default to `presigned`: the browser fetches
them from HealthImaging and the API never reads pixels. Checked live on
2026-09-28, including the CORS preflight Cornerstone's Accept header triggers.
`AURALANE_FRAME_MODE=proxy` on Render streams them through the API instead.

More studies: `python -m core.run ingest <study dir>` with the same
environment (`--state` overrides the site state for one ingest).

Expect the first brain and CT jobs after idle to wait for an instance: the
endpoints scale from 0, and a cold start takes several minutes.

### What it costs

| state | cost | from |
|---|---|---|
| deployed, idle, endpoints at 0 | pennies a month plus ECR image storage at $0.10 per GB-month (about 6 GB, so about $0.60) | docs/AWS-COSTS.md |
| the smoke test | three HealthImaging imports, one Lambda call (seconds at $0.000049 per second), one wake of each endpoint (about 20 to 30 minutes billed: $0.15 to $0.23 brain, $0.08 to $0.12 CT) | docs/AWS-COSTS.md, estimate |
| right after `cdk deploy` | each endpoint starts with 1 instance until it scales in: about 30 minutes at $0.461 and $0.23 per hour | docs/AWS-COSTS.md |
| presentation day, `-c chest_provisioned=1` | about $1.04 per day ($31.72 per month) | docs/AWS-COSTS.md |
| Render, Vercel | free tiers | |

### Tearing down

```
python infra/teardown.py              # dry run
python infra/teardown.py --yes        # bucket emptied, stack and endpoint log groups deleted
```

The HealthImaging datastore and every image set in it stay.

---

## The fixture preview: `auralane-preview`, the fallback

The fixture runtime: the committed synthetic rows in `fixtures/`, held in memory. No AWS, no datastore, no model. Created by the same Blueprint (step 6 above); the steps below are what it needs on its own, and how to check it.

### Order, and why

1. **Render first.** Vite writes `VITE_API_BASE` into the client bundle at build
   time, so the API's URL has to exist before the client is built.
2. **Vercel second**, with `VITE_API_BASE` set to the Render URL.
3. **Back to Render** to set `AURALANE_CORS_ORIGINS` to the Vercel URL. The API
   reads it at start, so fixing it is an edit plus a redeploy, no rebuild of
   anything.

### 1. Render (the API)

Dashboard, New, Blueprint, pick this repository. Render reads `render.yaml` at
the repo root:

| setting | value |
|---|---|
| type, runtime, plan | `web`, `python`, `free` |
| name | `auralane-preview` |
| region | `virginia` |
| build command | `pip install -r requirements-deploy.txt` |
| start command | `python -m core.run serve --host 0.0.0.0 --port $PORT` |
| health check path | `/api/health` |
| auto-deploy | on commit |

Environment variables:

| key | value | how |
|---|---|---|
| `PYTHON_VERSION` | `3.14.3` | committed. Render's documented default; it requires a full x.y.z |
| `AURALANE_RUNTIME` | `fixture` | committed |
| `AURALANE_DEV_PASSWORD` | the sign-in password for both users | **prompted**, never committed. Anyone holding it can sign in as either role |
| `AURALANE_DEV_JWT_SECRET` | random 256-bit value | generated once by Render and kept, so sessions survive sleep and restarts |
| `AURALANE_PUBLIC_URL` | `https://auralane-preview.onrender.com` | **prompted**. Evidence image URLs are built from it |
| `AURALANE_CORS_ORIGINS` | `https://<project>.vercel.app` | **prompted**. Enter the Vercel URL you intend to use; step 3 corrects it if needed |

`PORT` is set by Render (default 10000) and is not ours to set.

**Check after this step**

- Deploy log ends with `CORS origins: <your value>` and `Uvicorn running on http://0.0.0.0:<port>`.
- If it ends with `refusing to serve on 0.0.0.0: set ...`, the named variable is
  missing. The message names every missing one.
- The service page shows its URL. If Render added a suffix because the name
  was taken, set `AURALANE_PUBLIC_URL` to the URL actually shown, then
  "Save and deploy".
- `https://<service>.onrender.com/api/health` in a browser returns
  `{"runtime":"fixture"}`. No token needed.

### 2. Vercel (the client)

Dashboard, Add New, Project, import this repository.

| setting | value | where it comes from |
|---|---|---|
| Root Directory | `client` | **set in the dashboard**; Vercel has no vercel.json field for it |
| Framework Preset | Vite | `client/vercel.json`, `"framework": "vite"` |
| Build Command | `node scripts/require-api-base.mjs && npm run build` | `client/vercel.json` |
| Output Directory | `dist` | `client/vercel.json` |
| SPA rewrite | `/(.*)` to `/index.html` | `client/vercel.json`. Files in `dist` win over the rewrite, so assets and the sample frame are served as files, and a refreshed deep link such as `/studies/<id>` gets the app |

Environment variable, **set in the dashboard** (Project Settings, Environment
Variables) for Production:

| key | value |
|---|---|
| `VITE_API_BASE` | the Render URL, e.g. `https://auralane-preview.onrender.com` (no path) |

It is not in `vercel.json` because Vercel deprecates `build.env` there in favour
of Project Settings. If it is missing, the build fails on purpose with
`VITE_API_BASE is not set to an absolute URL`: without it the client would call
`/api` on Vercel, get `index.html` back, and every screen would fail.
Changing it later needs a redeploy, because it is baked in at build time.

**Check after this step**

- The build log shows `API base: https://<service>.onrender.com`.
- The site loads with the favicon, the `NON-DIAGNOSTIC; DECISION SUPPORT ONLY`
  badge, and Privacy and Terms links in the footer.
- Signing in fails with **Failed to fetch** until step 3 is done if the Vercel
  URL differs from what you entered at the Render prompt. That is the CORS
  symptom below, and expected.

### 3. Render again: CORS

Set `AURALANE_CORS_ORIGINS` on the Render service to the exact Vercel origin:
scheme and host, no trailing slash, no path. Several are comma-separated.
Then "Save and deploy". Never `*`: it is not needed, and credentials are
switched off anyway because the token travels in a header, not a cookie.

**Check after this step**

- Deploy log: `CORS origins: https://<project>.vercel.app`.
- Sign in as `radiologist`: the worklist shows the Chest and Neuro pools.
- Open a chest study: the sample image renders in the viewer and a note says no
  DICOM datastore is connected. Switch "Triage rationale" on for a Mass,
  Nodule or Infiltration row; the Grad-CAM layer is drawn over the image (the
  Edema rows have nothing above the display threshold, and say so).
- Refresh the study page: it reloads, still signed in.
- Sign out, sign in as `admin`: audit log, lane mix, thresholds and model
  registry load. A study link sends admin back to the audit log.

### When CORS is wrong

Measured against this build with an origin the API does not allow:

- The sign-in screen shows **Failed to fetch** under the button. Nothing else.
- The browser console: `Access to fetch at 'https://<api>/api/auth/login' from
  origin 'https://<client>' has been blocked by CORS policy: Response to
  preflight request doesn't pass access control check: No
  'Access-Control-Allow-Origin' header is present on the requested resource.`
- The Render log: `"OPTIONS /api/auth/login HTTP/1.1" 400 Bad Request`.
- `/api/health` opened directly in a browser tab still works. That is how to
  tell CORS from an API that is down or asleep.

Usual causes: a trailing slash or a path in `AURALANE_CORS_ORIGINS` (trailing
slashes are stripped, paths are not), `http` against `https`, or a Vercel
**preview** deployment, whose URL differs from production. Add a preview URL
to the list if you need it.

### Sleep, and the uptime monitor

A free Render service spins down after 15 minutes without traffic; the next
request waits about a minute while it starts. Everything held in memory is
lost on every spin-down, restart or deploy: verdicts and audit events reset to
the committed fixture state. Sessions survive, because the signing key is
stable.

To keep it awake for the presentation, add an HTTP monitor on
`https://<service>.onrender.com/api/health` at a 5-minute interval (a free
UptimeRobot monitor does this; the route needs no token and touches nothing).
**Switch it on on 30 September, the day before the 1 October presentation, and
off afterwards.** Render's free tier grants 750 instance hours per workspace
per calendar month, shared by every free service in the workspace, and an
instance kept awake meters all 24 of them every day.

Not verified: how a `fetch` from the client behaves while the instance is
still spinning up. Render shows browsers a loading page during spin-up, and
that page may not carry CORS headers, so the first sign-in after a sleep may
show Failed to fetch once. The monitor avoids the question.

### Not in the hosted preview

- The live pipeline: de-identification, the datastore, inference, scoring.
  Run it locally (docs/RUN.md).
- Study images, apart from one public sample chest image shown for every chest
  row. Brain rows have none.
- AWS. The AWS runtime is a separate piece of work.
