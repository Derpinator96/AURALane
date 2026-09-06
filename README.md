# AURALane — round 2 demo

A two-column worklist that shows the one thing the deck argues: **flagging fails,
reordering works.** Studies stream in, the left column keeps them in arrival order,
the right column re-sorts by calibrated acuity, and the critical study climbs to
the top instead of waiting eighth in line.

Not a diagnostic tool. It orders a reading queue.

---

## Run it

```
pip install -r requirements.txt
python prepare.py          # scores images/ -> scores.json  (once, offline)
python server.py           # http://localhost:8000
```

On Windows, install CPU-only torch first or pip pulls a ~2.5 GB CUDA build:

```
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

First run downloads the model weights (~30 MB) to `~/.torchxrayvision/`.

---

## Images

Already populated with your NIH ChestX-ray14 sample, and `scores.json` is prebuilt
from 100 of them — so `python server.py` works straight away. Re-run `prepare.py`
only if you want to score a different subset.

For NIH ChestX-ray14, the **sample subset** is what you want — 5,606 images, ~2 GB,
on Kaggle as `nih-chest-xrays/sample`. The full set is 112,120 images and ~42 GB;
you do not need it. Unzip and copy the PNGs into `images/`.

`prepare.py` scores 300 by default (`--limit` to change). 300 is plenty: the demo
queue only uses nine, and the rest exist to fit the operating points.

Public or openly licensed images only. No real patient records — that claim is on
the slide, so keep it true.

---

## What is real and what is simulated

Say this out loud during the demo; it is the difference between a demo and a mockup.

**Real** — every acuity score, lane and abstention. TorchXRayVision
`densenet121-res224-all`, 18 sigmoid heads, run over the images in `images/`.

**Simulated** — two things only, both stated on the page:
- *arrival order*, chosen so the critical study lands eighth of nine. Real studies
  arrive when scanners produce them; burying the critical one is the whole reason
  FIFO is a problem.
- *read cadence*, one radiologist clearing one study every six minutes.

The wait figures on the scoreboard are computed from those two assumptions by
simulating both policies over the same nine studies. They are your numbers, not
the RSNA paper's.

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
   assigned and the study goes to the human tray. This is the fail-open path and
   it is the thing no competitor shows.

`reference.json` ships fitted on a 44-study corpus. `prepare.py` refits it from
your own images once there are 50 or more, and the page footer says which one is
in use — so if a judge asks, the answer is on screen.

---

## If the lane mix comes out wrong

Thresholds are in `triage.py`:

```python
LANES = [("CRITICAL", 78, ...), ("URGENT", 52, ...), ("EXPEDITED", 22, ...), ...]
ABSTAIN_LO, ABSTAIN_HI = 0.35, 0.60
Z_FLOOR, Z_CEIL = 0.5, 2.5
```

These are already tuned against a 100-study sample of *your* NIH images, and the
shipped `scores.json` and `reference.json` come from that run. The mix is 51%
routine, 23% expedited, 10% abstain, 9% urgent, 7% critical — about what a real
chest X-ray population looks like.

`Z_FLOOR` is the one to understand if you re-tune. A finding contributes nothing
until it is at least half a standard deviation above its own baseline. Without
that floor, taking a max over 18 heads means almost every study has *something*
mildly elevated and the whole corpus scores critical — which is exactly what
happened on the first run: 44 of 100.

If you re-run `prepare.py` over a different or larger subset, check the lane counts
it prints and adjust `LANES` so the critical lane holds roughly the top 5–8%. That
is a capacity decision — how many studies one reader can actually absorb — not a
modelling one.

---

## Before you present

- `python server.py`, then click **Warm up model** in the toolbar. First inference
  after load takes several seconds and that is a bad silence on a call.
- Run it once end to end. Nine arrivals at ~1.1 s each is about ten seconds.
- Leave the mode on **Cached scores**. Live mode is there if the jury hands you an
  image, but nothing should depend on it.
- Record a screen capture as a fallback. If Teams screen-share fails you still have
  something to show.

---

## Layout

```
prepare.py        score images/ -> scores.json          (offline, run once)
triage.py         calibration, urgency, abstention      (shared)
queue_builder.py  pick nine studies, set arrival order
server.py         FastAPI: /api/queue, /api/score, /api/warm
web/index.html    the page — no build step, no CDN, works offline
reference.json    per-finding operating points
```
