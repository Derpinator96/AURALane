# Pipeline latency per step, from the audit trail

Measured by `scripts/measure_latency.py` on 2026-09-27 19:28 UTC. Every duration is read from the audit event the pipeline wrote for that step, in milliseconds.

- Platform: Windows-11-10.0.26200-SP0
- CPU: Intel64 Family 6 Model 140 Stepping 1, GenuineIntel
- Logical CPUs: 8
- Python: 3.14.5
- OCR workers: 8
- Runtime: local: Orthanc, DynamoDB Local, in-process CPU inference
- Studies: chest 1 instances (data/chest/studies/1.2.826.0.1.3680043.10.1421.105961411032363014371518744615673768), brain 620 instances (data/brain/dicom/1.2.826.0.1.3680043.10.1421.692321219394174180045603303719022305)

| step | chest run 1 (cold) ms | chest run 2 ms | brain run 1 (cold) ms | brain run 2 ms |
|---|---:|---:|---:|---:|
| deidentify | 5,527.8 | 739.4 | 114,069.2 | 86,540.7 |
| blob_put | 7.8 | 13.1 | 4,103.1 | 2,805.1 |
| import | 223.4 | 169.3 | 15,978.5 | 13,034.2 |
| prepare_inputs | 1.2 | 1.3 | 1,025.2 | 871.5 |
| infer | 29,148.5 | 871.6 | 31,581.8 | 18,637.8 |
| adapt | 0.5 | 0.4 | 775.1 | 531.7 |
| triage | 0.1 | 0.1 | 0.1 | 0.1 |
| persist | 119.8 | 49.8 | 68.7 | 62.2 |
| blob_delete | 0.7 | 1.0 | 359.9 | 219.8 |
| **total** | 35,029.8 | 1,846.0 | 167,961.5 | 122,703.1 |
| outcome | SCORED, EXPEDITED | SCORED, EXPEDITED | SCORED, ABSTAIN | SCORED, ABSTAIN |
| Grad-CAM inside infer | yes | yes | n/a | n/a |

Run 1 includes loading the model into memory. Later runs re-ingest the same study, so the datastore already holds its instances. `prepare_inputs` is pipeline work before the model (for brain, identifying the four channels and rebuilding them as NIfTI); `infer` is the model call, and for chest it includes the Grad-CAM backward pass and overlay writes when the Grad-CAM row says yes (the platform default since Prompt 4). One machine and one study per modality: a measurement, not a benchmark.
