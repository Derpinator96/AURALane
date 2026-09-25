# Pipeline latency per step, from the audit trail

Measured by `scripts/measure_latency.py` on 2026-09-25 13:45 UTC. Every duration is read from the audit event the pipeline wrote for that step, in milliseconds.

- Platform: Windows-11-10.0.26200-SP0
- CPU: Intel64 Family 6 Model 140 Stepping 1, GenuineIntel
- Logical CPUs: 8
- Python: 3.14.5
- OCR workers: 8
- Runtime: local: Orthanc, DynamoDB Local, in-process CPU inference
- Studies: chest 1 instances (data\chest\studies\1.2.826.0.1.3680043.10.1421.105961411032363014371518744615673768), brain 620 instances (data\brain\dicom\1.2.826.0.1.3680043.10.1421.692321219394174180045603303719022305)

| step | chest run 1 (cold) ms | chest run 2 ms | brain run 1 (cold) ms | brain run 2 ms |
|---|---:|---:|---:|---:|
| deidentify | 1,041.6 | 572.6 | 98,113.3 | 91,096.6 |
| blob_put | 9.5 | 5.1 | 3,172.5 | 4,489.5 |
| import | 74.2 | 78.2 | 9,264.7 | 10,664.5 |
| prepare_inputs | 0.7 | 0.9 | 921.3 | 905.7 |
| infer | 5,756.5 | 487.1 | 38,601.5 | 30,956.2 |
| adapt | 0.4 | 0.5 | 2,818.6 | 2,751.9 |
| triage | 0.1 | 0.1 | 0.4 | 0.1 |
| persist | 96.7 | 49.2 | 57.3 | 54.8 |
| blob_delete | 0.8 | 0.6 | 277.0 | 238.4 |
| **total** | 6,980.5 | 1,194.2 | 153,226.5 | 141,157.6 |
| outcome | SCORED, EXPEDITED | SCORED, EXPEDITED | SCORED, ROUTINE | SCORED, ROUTINE |

Run 1 includes loading the model into memory. Later runs re-ingest the same study, so the datastore already holds its instances. `prepare_inputs` is pipeline work before the model (for brain, identifying the four channels and rebuilding them as NIfTI); `infer` is the model call alone. One machine and one study per modality: a measurement, not a benchmark.
