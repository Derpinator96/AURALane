# Deploy: the hosted preview

Two services on two origins:

| | where | what it runs |
|---|---|---|
| client | Vercel, `https://<project>.vercel.app` | the built React app from `client/` |
| API | Render free web service, `https://<service>.onrender.com` | `python -m core.run serve` with `AURALANE_RUNTIME=fixture` |

The hosted API runs the **fixture runtime only**: the committed synthetic rows
in `fixtures/`, held in memory. No torch, no Orthanc, no DynamoDB, no DICOM
datastore, no live pipeline. Chest studies show one public sample image and
brain studies none, and the study screen says so. The live pipeline is the
local build (docs/RUN.md). Do not try to host it: the imaging data is
gitignored and the free instance has 512 MB.

## Order, and why

1. **Render first.** Vite writes `VITE_API_BASE` into the client bundle at build
   time, so the API's URL has to exist before the client is built.
2. **Vercel second**, with `VITE_API_BASE` set to the Render URL.
3. **Back to Render** to set `AURALANE_CORS_ORIGINS` to the Vercel URL. The API
   reads it at start, so fixing it is an edit plus a redeploy, no rebuild of
   anything.

## 1. Render (the API)

Dashboard, New, Blueprint, pick this repository. Render reads `render.yaml` at
the repo root:

| setting | value |
|---|---|
| type, runtime, plan | `web`, `python`, `free` |
| name | `auralane-api` |
| region | `singapore` (nearest to the presenters; the data is synthetic) |
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
| `AURALANE_PUBLIC_URL` | `https://auralane-api.onrender.com` | **prompted**. Evidence image URLs are built from it |
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

## 2. Vercel (the client)

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
| `VITE_API_BASE` | the Render URL, e.g. `https://auralane-api.onrender.com` (no path) |

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

## 3. Render again: CORS

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

## When CORS is wrong

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

## Sleep, and the uptime monitor

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

## Not in the hosted preview

- The live pipeline: de-identification, the datastore, inference, scoring.
  Run it locally (docs/RUN.md).
- Study images, apart from one public sample chest image shown for every chest
  row. Brain rows have none.
- AWS. The AWS runtime is a separate piece of work.
