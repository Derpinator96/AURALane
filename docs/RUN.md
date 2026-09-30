# Run: the local daily sequence

The local build is what we demonstrate on. The hosted preview (docs/DEPLOY.md)
has no datastore and no model; everything below needs this machine.

PowerShell, from the repo root, with `.venv` activated and Tesseract on PATH
(docs/SETUP.md steps 4 and 8). Four terminals, in this order.

Head CT needs `transformers` and `pyyaml` (requirements.txt) and the CQ500
studies in `data\ct\raw\` (data/ct/SOURCE.md). The chest regional prior reads
`$env:AURALANE_SITE_STATE` (for example `Chhattisgarh`, or `--state` per
ingest); `$env:AURALANE_REGIONAL_PRIOR = "off"` turns it off for a
side-by-side.

| what | port |
|---|---|
| Orthanc (DICOMweb) | 8042 |
| DynamoDB Local | 8001 |
| API (`core.run serve`) | 8100 |
| client (Vite dev server) | 5173 |
| round-2 demo, the fallback | 8000, untouched by all of the above |

## 1. Docker

    docker compose -f docker-compose.local.yml up -d
    python scripts\doctor.py

`doctor.py` must print `all green`.

**DynamoDB Local runs `-inMemory`.** Whenever its container restarts (a reboot,
Docker Desktop restarting, `docker compose restart`), the worklist and the
audit log are gone. Orthanc keeps its images across restarts and loses them
only when the container is removed. So after any restart the worklist is empty
while Orthanc still holds studies, and a fresh ingest (step 4) is required.
Tables are recreated on first use; nothing to do by hand.

## 2. The API

    $env:AURALANE_RUNTIME = "local"
    python -m core.run serve

Listens on 127.0.0.1:8100. On a loopback host none of the hosted-preview
variables are needed.

**The development password.** Both seeded users (`radiologist`, `admin`) sign
in with one password, resolved in this order:

1. `$env:AURALANE_DEV_PASSWORD`, if set in the terminal that starts the API
2. otherwise `data\dev\devauth.password`, created with a random value the
   first time the API or `core.run token` runs. `serve` prints this path.

To choose your own: set the variable before `serve`, or overwrite the file
and restart the API. `data\` is gitignored; no password is in the repository.
The token signing key sits next to it in `data\dev\devauth.key`, so a session
survives an API restart.

## 3. The client

    cd client
    npm run dev

http://localhost:5173. Vite proxies `/api` to 8100 and `/dicom-web` to Orthanc
on 8042, so leave `VITE_API_BASE` unset locally.

## 4. Ingest

Tesseract must be on PATH in this terminal (the de-identification OCR).

    $env:AURALANE_RUNTIME = "local"
    Get-ChildItem data\chest\studies -Directory | ForEach-Object { python -m core.run ingest $_.FullName }
    Get-ChildItem data\brain\dicom -Directory | ForEach-Object { python -m core.run ingest $_.FullName }
    Get-ChildItem data\ct\raw -Directory | ForEach-Object { python -m core.run ingest $_.FullName }

Each study prints its lane and the per-step audit durations. Refresh the
worklist to see it. One study at a time is fine; the worklist sorts itself.

**Measured ingest time** (this machine: 8 logical CPUs, CPU inference; one
machine, a measurement, not a benchmark):

| modality | per study | source |
|---|---|---|
| chest, one CLI process per study (the loop above) | 20.7 s and 27.5 s wall-clock, two studies | timed 2026-09-28 |
| chest, model already loaded in the process | 1.8 s | docs/LATENCY.md, run 2 |
| brain (620 instances), first study in a process | 168.0 s | docs/LATENCY.md, run 1 |
| brain, model already loaded | 122.7 s, of which de-identification 86.5 s | docs/LATENCY.md, run 2 |
| head CT, CQ500-CT-419 (36 slices), first ever run: includes downloading the 343 MB ViT | model 101.9 s | timed 2026-09-28, with a Docker build running |
| head CT, CQ500-CT-5 (53 slices), weights cached | model 32.0 s, de-identification 9.7 s | timed 2026-09-28 |

The loop starts a new process per study, so every chest study pays for loading
torch and the model again; that is the gap between the first two rows. The
full 40-study chest loop was not timed end to end. At the measured 20 to 28 s
per study it would take roughly 14 to 19 minutes, an extrapolation, not a
measurement. Ingest a handful of chest studies and both brain studies before a
demo rather than the whole corpus.

As of 2026-09-28 the brain study measured above (BraTS2021_00621) ingests to
NEEDS HUMAN TRIAGE, "Segmentation could not be automatically verified (failed:
inside_brain)". Measured cause: the de-identification OCR pass reads MR anatomy
as text on 8 of its 620 slices and blacks those boxes out, so part of the
predicted tumour lands on zeroed T1c pixels (inside_brain 0.9783 against a
floor of 0.99; 1.0 against the raw T1c). The brain corpus has no burned-in
text, so all 8 are false positives. The check is reporting a real change to the
model's input. No threshold has been changed. BraTS2021_00495 passes (0.9999).

## Simulated intake: 30 studies from the admin screen

Admin, "Simulated intake", "Ingest 30 studies". It ingests real studies from
this machine's corpus through the full pipeline in a shuffled arrival order:
every brain MR and head CT study on disk (2 and 2 today), chest X-rays to make
up 30. The lanes are pipeline results; only the order is simulated. Each
finished study appears on the worklist; the tab shows per-study progress and
the run is audited (`intake_simulation`).

It runs where the studies are, in the process serving the API, so start the
API on this machine:

- local stack: `python -m core.run serve` as in step 2 (one study at a time,
  the models share the process).
- AWS, from the deployed site or `python -m core.run serve --stack Auralane`:
  cloud-native. The button copies 30 corpus studies into S3 `upload/`
  server-side, and each one starts its own Fargate ingest task
  (docs/DEPLOY.md step 7), so the studies never pass through the API host.
  Needs the corpus in S3 once (`python -m core.run upload-corpus --stack
  Auralane`). Sign in as a Cognito `admin` user. Cost: a Fargate task, a
  HealthImaging import and a model call per study, plus one wake of each
  SageMaker endpoint (docs/AWS-COSTS.md).

On the Render API and the fixture runtime the tab says why it is unavailable:
no corpus on that host, or no pipeline.

## Simulate ingest: the radiologist screen

Radiologist screen, "Simulate ingest". Choose how many chest X-rays (up to 25),
brain MRs (up to 3) and head CTs (up to 5) to send, and which readers get them. The
panel shows the estimated AWS cost, itemised with what each line assumes, before
you confirm. The studies come from a staged pool, already de-identified at the
edge, and each runs through the real pipeline in the background (receive, a
check of the edge de-identification, store, prepare, infer, adapt, regional
prior, triage, evidence, persist). Each lands on the worklist, assigned, as it
finishes. Admin, "Pipeline" shows them crossing the stages.

Stage the pool once, on this machine (the edge):

```
python scripts/stage_pool.py --local                 # data/pool/, for the local runtime
python scripts/stage_pool.py --stack Auralane        # s3://<bucket>/pool/, for AWS
```

De-identification happens there and nowhere else: the pipeline refuses any
staged instance without PatientIdentityRemoved YES and a
DeidentificationMethod. New BraTS cases: put them in data/brain/raw/<case>/,
run `python scripts/convert_brain.py`, then stage again (already-staged studies
are skipped).

What is in the pool: 100 chest X-ray studies (the 40 of the tested corpus in
data/chest/studies, and 60 more in data/chest/extra, built by
`python sim/generator/make_dicom.py --src images --out data/chest/extra --count 60 --seed 2026 --burn-in 0.1`),
12 brain MRs and 9 head CTs (CQ500 and the RSNA set). More head CTs: put each
study's DICOM folder in data/ct/raw/ and stage again. The S3 pool is a separate
copy of the same staging, so after adding studies run the `--stack` command too.

## Upload study: your own files

Radiologist screen, "Upload study". Choose files, or a folder, and upload. Two
kinds are taken: DICOM files (one study, or several; chest X-ray CR, brain MR with
its four sequences, head CT) and PNG or JPEG chest X-ray images (each is wrapped
as a frontal PA Computed Radiography study that carries no patient, so it is shown by pseudonym alone). Each study
runs through the real pipeline, which de-identifies it first, and lands on your
own worklist in the pool its modality belongs to. A reader who does not read that
pool is told before anything is sent. The fixture preview has no pipeline and says
so. Use public, synthetic or openly licensed studies only.

The limits are 1,000 files, 64 MB a file, 400 MB and 20 studies in one upload.
Files go to the API one request each as the raw body, so a file name (which can
carry a patient's name) is never sent, stored or audited. The API holds them in a
temporary folder only until they are handed to the pipeline and deletes each as
its study finishes. On AWS they go to S3 `upload/` and the ingest task takes them
from there, as for the edge agent (docs/DEPLOY.md step 7).

"Distribute worklist" deals every unread study, critical first, round robin
among the readers you choose. The fixture preview has no pipeline and says so.

## Reset after any change to de-identification

    docker compose -f docker-compose.local.yml down
    docker compose -f docker-compose.local.yml up -d

then ingest again. Why Orthanc needs it: Orthanc does not overwrite an instance
it already holds, and the identity map gives a re-ingested study the same
pseudonymous UIDs by design. A study stored under the old de-identification
rules therefore keeps its old metadata, silently. This has bitten once already:
brain series stored before sequence names were kept still read
`TRIAGE SERIES`, and the pipeline refused them as unidentifiable. Neither
container has a volume, so `down` clears both stores. The identity map
(`data\identity\identity.db`) is kept on purpose: it is what makes the UIDs
stable.

## Without Docker

    $env:AURALANE_RUNTIME = "fixture"
    python -m core.run serve

The same API over the committed fixture rows, no Orthanc, no DynamoDB, no
model: what the hosted preview runs. The round-2 demo (`python server.py`,
port 8000) remains the fallback if the local stack is down.
