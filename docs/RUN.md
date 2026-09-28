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
