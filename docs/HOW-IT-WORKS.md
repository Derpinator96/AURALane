# How AURALane works

One short section per component, written to be explained out loud.

NON-DIAGNOSTIC; DECISION SUPPORT ONLY. AURALane puts studies in a reading order.
It never says what is in a study. A radiologist reads every study.

## The idea

A flag does not shorten waits; re-sorting the queue does. In a prospective RSNA
study of 6,696 head CTs, an AI pop-up left critical wait time unchanged at
15.75 minutes, and reprioritising the worklist cut it to 12.01 minutes. So
AURALane re-sorts the queue instead of adding alerts.

## De-identification (`sim/edge/deid.py`)

Before a study is stored anywhere it goes through the DICOM PS3.15 basic
confidentiality profile: names, IDs, dates of birth, institutions and free text
are removed, blanked or replaced with pseudonyms, and every UID is remapped the
same way each time so a study stays one study. Private tags and overlay planes
are deleted.

Some images carry the patient's name drawn into the pixels. Every image is run
through OCR twice (once as is, once on only the brightest pixels) and any text
found is blacked out.

If OCR is not installed, de-identification stops with `OCRUnavailable`. The
study is marked FAILED and nothing is stored. It never continues with the
pixels unmasked unless a caller has explicitly said the modality carries no
burned-in text.

## The identity map (`sim/edge/identity.py`)

The only place original names live. It maps each pseudonym back to the real
patient so a radiologist can see who a study belongs to. In production it stays
inside the hospital; the cloud only ever sees pseudonyms. Locally it is
`data/identity/identity.db`, which git ignores.

## The pipeline (`core/pipeline.py`)

One function, `ingest`, takes a study's files through eight steps:
de-identify, keep a transient copy, import into the datastore, run the model,
turn the output into findings, triage, write the worklist row, delete the
transient copy. Every step writes an audit event with how long it took in
milliseconds. If any step fails, the study still gets a worklist row, with
status FAILED and the error, so it cannot silently vanish.

## The datastore

Where the de-identified images live, queried with the DICOMweb standard. Locally
this is Orthanc; on AWS it is HealthImaging. The browser fetches image pixels
straight from the datastore using a URL the API hands out; the API never passes
pixels through itself.

## The model registry (`models/registry.json`)

A list of models. Each entry says which modality it handles, what input it
needs, where it runs, which adapter reads its output, and how urgent each of its
findings is. Adding a model means adding an entry and an adapter; triage does
not change.

## Adapters (`adapters/`)

Each model speaks differently; an adapter translates its output into one shape:
a signal between 0 and 1 for each finding.

- Chest (`multilabel.py`): each of the 18 outputs is compared with that
  finding's own typical value, because the heads sit at very different levels.
  0 means typical, 1 means far above typical.
- Brain (`brats.py`): reads the tumour volumes Shaurya's pipeline measures and
  maps them between clinically chosen floors and ceilings. Enhancing tumour,
  edema (whole tumour minus core), tumour burden (tumour as a share of brain
  volume) and `mass_effect`. It also draws the tumour outline over the slice
  where it is largest and stores that picture as the evidence.

## Triage (`triage.py`)

Takes the findings and decides the lane. Each signal is multiplied by how fast
that finding needs a human (pneumothorax 1.00, cardiomegaly 0.24). The largest
product is the acuity and names the driving finding. If the driving signal is
in the uncertain band (0.35 to 0.60) the study abstains: no lane, a human
decides. Otherwise acuity sets the lane: Critical (under 15 min), Urgent (under
1 hr), Expedited (under 4 hr), Routine. Every model's findings go through the
same arithmetic.

## The API (`python -m core.run serve`)

Worklist sorted Critical, Urgent, Abstain and Failed, Expedited, Routine, and by
acuity within a lane. Study detail with the audit trail and a drafted note.
Frame URLs for the viewer. Every route except health needs a bearer token; in
development `python -m core.run token radiologist` prints one.

## The drafted note (`TemplateLLM`)

Restates the lane, the driving finding and the signals in a fixed template and
leaves the impression for the radiologist. No language model writes clinical
text.

## What we know is limited

1. OCR masking is high-recall, not complete. The failure mode is a name
   surviving into a de-identified store. At 40 studies one case (SIMID-000033,
   a name overlapping a circled "R" and lead wires) was read by neither OCR
   setting until a second detection pass on the brightest pixels was added.
   Chest X-ray rarely carries burned-in text, so it is the first modality, with
   human review sampling.
2. `mass_effect` is a proxy, not measured midline shift. Real midline shift
   needs the ventricles outlined, and this data does not label them. It is
   tumour burden scaled by how far the tumour sits from the middle of the
   scan, which assumes the scan is centred on the head (true for BraTS). How
   the two are combined is our choice and has not been clinically validated.
3. The brain model was trained only on scans that have tumours. It has never
   seen a normal brain and will outline something on one. It ranks severity
   among tumour studies; it does not detect disease. Below 1 ml of whole tumour
   the study abstains instead of scoring.
4. Bedrock is blocked at the account level, so drafting runs on the template
   implementation. We would keep it that way for clinical text regardless.

Two more found while building the pipeline:

5. De-identification replaces the series names, so the pipeline cannot check
   by name that the four brain series are in the model's channel order
   (T1c, T1, T2, FLAIR). It checks the series numbers are 1 to 4 and trusts
   that the source numbered them in that order, as `nifti_to_dicom.py` does.
   A source that numbers them differently would feed the model scrambled
   channels, which still produces a plausible-looking outline.
6. De-identification of a full brain study is slow. Measured on the build
   container: 144 s for 620 slices, because every slice gets two OCR passes.
   The 10 s estimate for that step is wrong for MR. The chest study took
   0.8 s. These are single runs on one machine, not benchmarks.
