# Pipeline latency per step, from the audit trail

**Awaiting a local run of `scripts/measure_latency.py`. No figure on this page has been measured yet.** The previous single figure (about 70 s) was an estimate for one chest image, not a measurement.

| step | chest run 1 (cold) ms | chest run 2 ms | brain run 1 (cold) ms | brain run 2 ms |
|---|---:|---:|---:|---:|
| deidentify | not measured | not measured | not measured | not measured |
| blob_put | not measured | not measured | not measured | not measured |
| import | not measured | not measured | not measured | not measured |
| prepare_inputs | not measured | not measured | not measured | not measured |
| infer | not measured | not measured | not measured | not measured |
| adapt | not measured | not measured | not measured | not measured |
| triage | not measured | not measured | not measured | not measured |
| persist | not measured | not measured | not measured | not measured |
| blob_delete | not measured | not measured | not measured | not measured |
| **total** | not measured | not measured | not measured | not measured |
| outcome | not measured | not measured | not measured | not measured |

Run 1 includes loading the model into memory. Later runs re-ingest the same study, so the datastore already holds its instances. `prepare_inputs` is pipeline work before the model (for brain, identifying the four channels and rebuilding them as NIfTI); `infer` is the model call alone. One machine and one study per modality: a measurement, not a benchmark.
