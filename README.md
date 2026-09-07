# AURALane — round 2 demo

A two-column worklist that shows the one thing the deck argues: **flagging fails,
reordering works.** Studies stream in, the left column keeps them in arrival order,
the right column re-sorts by calibrated acuity, and a critical study climbs to the
top instead of waiting behind whatever happened to arrive first.

Not a diagnostic tool. It orders a reading queue.

---

## Run it

```
pip install -r requirements.txt
python server.py           # http://localhost:8000
```

On Windows, install CPU-only torch first or pip pulls a ~2.5 GB CUDA build:

```
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

First use of the model downloads its weights (~28 MB) to `~/.torchxrayvision/`.
On Windows that download can die with a `UnicodeEncodeError` — the progress bar
writes a block character the cp1252 console cannot encode. If that happens, delete
the truncated file in `~/.torchxrayvision/models_data/` and re-run with
`PYTHONUTF8=1`. Once the weights are cached the problem cannot recur, because the
progress bar only runs during a download.

`scores.json` ships with 1,000 real model outputs, so the demo runs immediately —
no images and no scoring pass needed.

---

## Images

**`images/` is not in this repo.** It is 5,606 NIH ChestX-ray14 PNGs, about 2.2 GB
of public data we did not create. Get the **sample subset** from Kaggle as
`nih-chest-xrays/sample` — 5,606 images, ~2 GB. The full set is 112,120 images and
~42 GB; you do not need it. Unzip and copy the PNGs into `images/`.

Everything except the study thumbnails works without them: the queue, the lanes,
the acuity scores and the wait calculation all read from `scores.json`. Only the
image inside the study modal will be blank until the PNGs are present.

Public or openly licensed images only. No real patient records — that claim is on
the slide, so keep it true.

---

## Core System Architecture

AURALane is an AI-assisted medical imaging triage and worklist orchestration platform built on the principle: **FLAGGING ≠ TRIAGE**.

```
Modality-specific Model (CXR Live / CT Prototype / MRI Experimental)
        ↓
Normalized InferenceResult
        ↓
Common Calibration (Temperature Scaling T=1.6)
        ↓
Common Abstention (Uncertainty Band [0.35, 0.60])
        ↓
Common Acuity Engine (Z-Score Baseline Normalization × Urgency Weighting)
        ↓
Common SLA Lane (CRITICAL, URGENT, EXPEDITED, ROUTINE, ABSTAIN)
        ↓
Unified Worklist Ranking
```

---

## CURRENTLY IMPLEMENTED

- **CXR Live Model Inference**: In-process TorchXRayVision DenseNet121 model scoring actual image pixels (`LIVE MODEL`).
- **FIFO Worklist**: Strict arrival-order queue preserving original scanner receipt order.
- **AURALane Ranking Engine**: Unified multi-modal worklist sorting by calibrated acuity score.
- **Temperature Calibration**: Platt/Temperature scaling ($T=1.6$) for raw model sigmoid outputs.
- **Baseline Normalization**: Z-score signal computation relative to population reference statistics.
- **Urgency Weighting**: Clinical severity multiplier per pathology finding.
- **Abstention Logic**: Uncertainty-aware abstention flagging (confidence between 0.35 and 0.60) triggering human verification.
- **SLA Lanes**: CRITICAL (<15 min), URGENT (<1 hr), EXPEDITED (<4 hr), ROUTINE (scheduled), ABSTAIN.
- **Wait-Time Simulator**: Replays FIFO vs AURALane queue clearing to demonstrate critical wait time reduction.
- **Live Upload**: Interactive image upload with live model scoring and immediate worklist re-ordering.
- **Human Override System**: Interactive AGREE, DISAGREE, and OVERRIDE (custom lane & reason) with server-side persistence.

---

## MVP PROTOTYPE

- **Head CT Adapter**: Pretrained prototype adapter for acute intracranial hemorrhage triage (`PRETRAINED PROTOTYPE`).
- **Brain MRI Adapter**: Experimental adapter for structural brain lesion triage (`EXPERIMENTAL`).
- **Modality Router**: Unified dispatching mechanism routing CXR, CT, and MRI to proper adapters.
- **Multi-Modal Worklist Pool**: 1,200 multi-modal studies scored through the common triage pipeline.
- **Honest Labeling & Data Source Transparency**: Every study displays explicit Model Status (`LIVE MODEL`, `PRETRAINED PROTOTYPE`, `EXPERIMENTAL`) and Data Source (`LIVE MODEL INFERENCE` vs `DEMO FIXTURE`).

---

## TARGET CLOUD ARCHITECTURE

- **Amazon S3**: Ingestion bucket for incoming DICOM imaging series.
- **AWS HealthImaging**: Managed DICOM repository for cloud-native medical image storage & retrieval.
- **AWS Lambda**: Serverless de-identification and modality routing triggers.
- **Amazon SageMaker**: Hosted inference endpoints for multi-modal AI models (TorchXRayVision CXR, MONAI Head CT, BraTS MRI).
- **Amazon DynamoDB**: Low-latency store for normalized study triage metadata and human override audit logs.
- **Amazon API Gateway & AWS Cognito**: Secure, authenticated REST API for healthcare application clients.
- **OHIF Viewer & React Frontend**: Web-based DICOM viewer integrated with AURALane worklist orchestration.

---

## Using it

- **studies** — how many to draw. Default 40. Do not go below 20; see the note on
  variance under *Compute waits*.
- **Start intake** → **Stop intake** while running, **Resume** if you halt it early.
  When a run finishes, the button returns to **Start intake** and the next press
  draws a fresh random sample.
- **Warm up model** — press it before you present. The first inference after load
  takes ~10 s from cached weights, and that is a bad silence on a call.
- **Upload study** — hand the model an image it has never seen. It is scored in
  process (~150 ms warm) and inserted into both queues. It always arrives *last*,
  which is the honest FIFO position for something that just landed, so wherever it
  appears on the right is the reordering, live.
- Click any study for the finding table, the per-finding baseline comparison and the
  reason for its lane. **Agree with lane** marks it read and clears it from both
  worklists. **Disagree** records the verdict without clearing.

Both worklists scroll inside their own box, so the page does not grow as the queue
does. FIFO's newest arrivals fall below its scroll fold while AURALane keeps the
urgent ones at the top — which is the argument, made structurally.

---

## Compute waits

The button appears once intake is paused or finished. It replays both policies over
everything that arrived and prints the totals:

```
40 studies · 4 critical · read cadence 6 min

                           FIFO AURALANE
total wait (min)           1836     1836
mean wait (min)              45       45
mean wait, critical          38        3
```

**Total wait is identical under both policies, always.** That is not a bug and not a
rounding artefact — it is the work-conserving queue invariant. With one reader and a
fixed cadence, reordering cannot change aggregate waiting time; it can only decide
*who* waits. Measured across 200 random runs the difference was exactly zero every
time, while the critical figure differed in 195 of them and AURALane was never worse.

This is the honest statement of what triage does: **it does not create radiologist
capacity, it allocates it.** The critical patient's wait collapses, paid for by
routine studies waiting marginally longer. Have that ready — "so you are just moving
the problem around?" is the sharpest question a judge can ask, and the answer is yes,
deliberately, toward the patient who cannot wait.

**On variance.** With random arrival the headline percentage swings with the draw.
Measured over 250 runs per size:

| intake | median | 5th pct | runs showing ≤25% |
|---|---|---|---|
| 10 | −83% | 0% | 9% |
| 20 | −92% | −64% | 2% |
| 40 | −95% | −86% | 2% |
| 60 | −97% | −93% | 0% |

At small intakes a run can land on **0% improvement** in front of the jury. Hence the
default of 40.

Note also that these are queue-simulation numbers under a single reader with no
competing work. They are not comparable to the −24% in the RSNA study the deck cites,
which is a real-world clinical result. They are your numbers, not the paper's.

---

## How a study gets a lane

Four steps, in `triage.py`:

1. **Temperature scaling** (T = 1.6, logit space) turns a raw sigmoid output into
   the confidence a clinician is shown.
2. **Per-finding operating point.** This is the part the deck understates. The 18
   heads sit at wildly different points — `Nodule` never drops below ~0.36 across a
   corpus, `Edema` averages ~0.21. Judged against a flat 0.5, one head dominates
   every study. So each finding is scored against its own reference distribution
   (`reference.json`), and "typical for this finding" scores zero.
3. **Clinical urgency weighting.** A confidence is not an urgency. Pneumothorax at
   0.6 outranks cardiomegaly at 0.9.
4. **Abstention.** If the driving finding is elevated but not clearly, no lane is
   assigned. The study still appears in both worklists labelled `ABSTAIN` with no
   acuity, and a human decides. This is the fail-open path and it is the thing no
   competitor shows.

The page footer says whether the operating points were fitted on this corpus or
borrowed from the shipped reference — so if a judge asks, the answer is on screen.

---

## Image handling — why `imaging.py` exists

Every caller — `prepare.py` and the live-upload path in `server.py` — goes through
`imaging.predict`. They used to carry their own copy of the same six preprocessing
lines, and both copies shared two faults:

- **Alpha channels were averaged into the pixels.** `img.mean(2)` folded a constant
  255 alpha into the greyscale, brightening the image. It did not crash; it returned
  a *different* score. Six of the 1,000 pool images are RGBA.
- **Bit depth was hard-coded to 8.** `normalize(img, 255)` raises when the input
  exceeds 255, so a 16-bit PNG — what most DICOM viewers export — produced HTTP 500
  and the words "Internal Server Error".

Both are fixed: alpha is dropped before averaging, and `maxval` comes from the dtype.
Unreadable uploads now return HTTP 400 with the reason instead of a 500.

This matters more for live upload than for the corpus. The corpus is uniform 8-bit
greyscale; the file a jury hands you is not. Note that `scores.json` was generated
before this fix, so the six RGBA studies in the pool carry slightly stale acuity
values — measured drift on one of them was 0.0 to 0.8, same lane. Re-run
`prepare.py --limit 1000 --no-refit` if you want them exact.

`server.py` imports `imaging` *inside* the scoring endpoint rather than at module
scope, because `imaging` pulls in torch and the cached worklist has to keep working
on a machine with no torch installed.

---

## Re-scoring

`prepare.py` scores images into `scores.json`. It samples `--limit` images (default
300) using `--seed` (default 7), so a given seed and image set always produce the
same sample.

```
python prepare.py --limit 1000 --no-refit
```

**`--no-refit` matters.** By default `prepare.py` refits `reference.json` whenever it
has 50+ studies, which moves every acuity value and invalidates the `LANES`
thresholds tuned against the old scale. `--no-refit` scores against the existing
reference instead. The shipped `scores.json` was built exactly this way.

The shipped `reference.json` is fitted on a 100-study sample. Against it, the
1,000-study pool comes out:

| lane | count | share |
|---|---|---|
| ROUTINE | 505 | 50.5% |
| EXPEDITED | 233 | 23.3% |
| URGENT | 96 | 9.6% |
| CRITICAL | 89 | 8.9% |
| ABSTAIN | 77 | 7.7% |

About what a real chest X-ray population looks like, and close enough to the
100-study mix the thresholds were tuned on that they still hold.

If you re-score a different corpus, check the lane counts it prints and adjust
`LANES` in `triage.py` so the critical lane holds roughly the top 5–8%. That is a
capacity decision — how many studies one reader can absorb — not a modelling one.

`Z_FLOOR` is the one to understand if you re-tune. A finding contributes nothing
until it is at least half a standard deviation above its own baseline. Without that
floor, taking a max over 18 heads means almost every study has *something* mildly
elevated and the whole corpus scores critical — which is exactly what happened on the
first run: 44 of 100.

---

## Before you present

- `python server.py`, then click **Warm up model**.
- Run it once end to end at your intended intake size and check the mix looks sane.
- Record a screen capture as a fallback. If Teams screen-share fails you still have
  something to show.

---

## Layout

```
prepare.py        score images/ -> scores.json          (offline, --no-refit)
imaging.py        one image loader — dtype, alpha, resize   (shared)
triage.py         calibration, urgency, abstention      (shared)
queue_builder.py  serve the scored pool; the page samples from it
server.py         FastAPI: /api/queue, /api/score, /api/warm, /api/health
web/index.html    the page — no build step, no CDN, works offline
web/fonts/        Poppins, vendored so the page renders with no network
reference.json    per-finding operating points
scores.json       1,000 scored studies — the pool every run draws from
```
