# AURALane

**Non-diagnostic; decision support only.** AURALane puts a radiology reading queue in order. It does not
read a study and it never says what is in one. A radiologist reads every study.

A cloud-native, AI-ready imaging platform for early disease triage, built by Team Peanut Butter (NIT Raipur)
for the Precision Care Challenge 2026. It sits beside a hospital's PACS as a sidecar: PACS, archive and RIS
stay where they are; AURALane receives a copy and returns an ordering.

## The idea

Flagging a study does not shorten the wait for a critical one; re-sorting the worklist does. A prospective
RSNA study over 6,696 head CTs found that an AI flag left critical wait time unchanged, and that actively
reprioritising the worklist cut it by 24%. So this is a queue that re-sorts, not a classifier with a
confidence readout.

## What it does

- **Lanes with clocks.** Critical (under 15 min), Urgent (under 1 hr), Expedited (under 4 hr), Routine
  (scheduled). Each finding is scored against its own reference distribution and weighted by clinical
  urgency, so urgency is not confidence.
- **Abstention.** When the model is not confident enough to place a study, it refuses and the study goes to
  the **Abstention Tray**, where a radiologist assigns a lane, gets a second opinion, or marks it
  technically inadequate.
- **Reading pools.** Chest and Neuro are ranked separately and never merged.
- **Second opinions.** A reader can send a study, in any lane, with a message, to other radiologists. It
  works like mail: the study stays on the sender's worklist. They find it under *Second opinions*, write
  reports of their own, and everyone on the study reads them from a dropdown.
- **Upload study.** A reader can send their own files: a study's DICOM folder, several studies, or chest
  X-ray images (PNG, JPEG). The API sorts them into studies and runs each through the same pipeline, which
  de-identifies it before anything is stored. Each study lands on the uploader's own worklist, in the pool
  its modality belongs to.
- **The study view.** Images (Cornerstone3D for 2D, NiiVue for 3D), a per-finding Grad-CAM shown only here,
  a drafted report assembled from structured output, and the reader's own edits saved to Reports.
- **Admin screens.** Audit log, pipeline timings, lane mix, thresholds and the model registry. Admins cannot
  open a study.
- **De-identification before anything is indexed**, including OCR masking of burned-in text.

How it fits together, and what is known to be limited: [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md).

## Runtimes

One codebase, three runtimes, chosen with `AURALANE_RUNTIME`. Everything is built against ports, so the same
pipeline runs in each.

| runtime | datastore | table | auth | use |
|---|---|---|---|---|
| `fixture` | in-memory fixture rows | in memory | development JWT | no Docker, no AWS; the hosted preview |
| `local` | Orthanc (DICOMweb) | DynamoDB Local | development JWT | the full pipeline on one machine |
| `aws` | AWS HealthImaging | DynamoDB | Cognito | the deployed system |

## Quick start (the fixture runtime)

Python 3.11 or newer and Node 20 or newer. From the repo root, in PowerShell:

```
python -m venv .venv; .venv\Scripts\activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt -r requirements-dev.txt

$env:AURALANE_RUNTIME = "fixture"
python -m core.run serve                    # the API on 127.0.0.1:8100

cd client; npm install; npm run dev         # http://localhost:5173
```

On Linux or macOS use `source .venv/bin/activate` and `AURALANE_RUNTIME=fixture python -m core.run serve`.

Sign in as `radiologist` or `admin`. Both use one development password: `AURALANE_DEV_PASSWORD` if set in the
terminal that starts the API, otherwise `data/dev/devauth.password`, created with a random value on first
run. `radiologist-1` to `radiologist-4` are further readers, which is how to try second opinions with two
sessions. No password is in the repository. The fixture runtime keeps its state in memory.

The local runtime (Docker, ingest, Tesseract) is in [docs/SETUP.md](docs/SETUP.md) and
[docs/RUN.md](docs/RUN.md).

## Tests

```
pytest                        # Python: API, pipeline, adapters, de-identification, infra
cd client; npm test           # unit tests (Vitest)
cd client; npm run e2e        # browser tests (Playwright, needs Chrome)
```

Some Python tests need Tesseract on PATH and the local data corpus; [docs/SETUP.md](docs/SETUP.md) lists what
to install.

## Where things are

| path | what |
|---|---|
| `core/` | the API, the pipeline, the ports and their local, fixture and AWS providers |
| `adapters/`, `models/` | each model's adapter, and the registry that describes them and the readers |
| `triage.py` | lanes, urgency weighting and abstention |
| `sim/` | de-identification, the identity map, and synthetic DICOM generation |
| `data/` | corpus builders and their notes; the data itself is not in git |
| `client/` | the React app (Vite), with its unit and end-to-end tests |
| `infra/` | the AWS stack (Python CDK); nothing here is deployed by running the tests |
| `fixtures/` | the fixture runtime's rows, built by `scripts/make_fixtures.py` |
| `scripts/` | doctor, smoke and end-to-end checks, latency measurement, backfills |
| `tests/` | the Python tests |
| `docs/` | setup, run, deploy, costs, latency, performance, observability |
| `web/`, `server.py`, `prepare.py` | the round-2 demo, still runnable: [docs/ROUND-2-DEMO.md](docs/ROUND-2-DEMO.md) |
| `shaurya-webapp/` | a separate Flask model explorer; nothing else depends on it |
| `CT_Mehak/` | the head CT model, as a git submodule (`git submodule update --init`) |

## Data

No real patient data. Images are public, synthetic or openly licensed, and synthetic identifiers are
unmistakably synthetic (`SIM^PATIENT^0042`). The NIH ChestX-ray14 sample PNGs (`images/`, 5,606 files,
about 2 GB) are not in the repository; [docs/SETUP.md](docs/SETUP.md) says where to get them. BraTS and CQ500
studies are downloaded by hand under their own licences.

## Working on it

Work happens on a branch and lands through a pull request against `main`. Run the Python and client tests
before opening one, and keep the non-diagnostic notice on every screen.
