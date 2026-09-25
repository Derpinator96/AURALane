# Architecture: ports, providers and the runtime switch

AURALane is built against six ports (abstract interfaces in `core/ports/`). The
pipeline, the adapters and the API see only the ports. Two provider sets
implement them: `core/providers/local/` runs on one machine with no AWS account,
`core/providers/aws/` targets AWS. `core/run.py` is the only file that chooses
between them.

NON-DIAGNOSTIC; DECISION SUPPORT ONLY. The platform orders a reading queue. It
does not read a study.

## The five steps

```
[upload / ingest] -> [S3] -> [Lambda: de-identify] -> [HealthImaging]
                                                            |
                                  [Lambda: model + Grad-CAM + triage]
                                                            |
                                                      [DynamoDB]
                                                            |
                      [React app: login, worklist, viewer, audit]
```

`core/pipeline.py` implements the middle three boxes as nine audited steps:
`deidentify`, `blob_put`, `import`, `prepare_inputs`, `infer`, `adapt`,
`triage`, `persist`, `blob_delete`. `prepare_inputs` (building the model's
inputs) and `infer` (the model call) are separate so model time is measured on
its own. De-identification is first and nothing is stored before it
succeeds.

## Ports

| port | methods | used by |
|---|---|---|
| `DatastorePort` | `import_study`, `search`, `get_metadata`, `get_frame`, `frame_url` | pipeline step 3, API frame URLs |
| `BlobPort` | `put`, `get`, `delete`, `presigned_url` | transient study copy, evidence PNGs |
| `TablePort` | `put_item`, `get_item`, `query`, `scan`, `append_audit` | worklist rows, audit trail |
| `AuthPort` | `login(username, password) -> token`, `verify(token) -> Principal` | API login, every route except health and login |
| `InferencePort` | `score(ref, model_cfg, **inputs)` | pipeline step 4 |
| `LLMPort` | `draft(context) -> str` | API study detail |

Two rules the ports enforce:

- `frame_url` exists so the browser fetches pixels from the datastore
  directly. The API returns a URL and never proxies pixel data.
- `TablePort` has no update or delete for audit. `append_audit` is conditional
  on the event id not existing, `put_item` refuses the audit table, and `scan`
  refuses it too. Audit is append only.

## Which local provider stands in for which AWS service

| port | local provider | stands in for | AWS provider (status) |
|---|---|---|---|
| Datastore | `OrthancDatastore`: Orthanc 1.13.0 DICOMweb, STOW-RS in, QIDO-RS and WADO-RS out | AWS HealthImaging | `HealthImagingDatastore` (stub) |
| Blob | `FileBlob`: a directory, `data/blob/` | Amazon S3 | `S3Blob` (stub) |
| Table | `DynamoLocalTable`: DynamoDB Local on host port 8001 | Amazon DynamoDB | `DynamoTable` (stub; shares `_dynamodb.py` with the local provider) |
| Auth | `DevAuth`: HS256 JWTs, two seeded users, development only | Amazon Cognito | `CognitoAuth` (stub) |
| Inference | `InProcessInference`: the model in this process, dispatched on `output_type` | Lambda container (chest), SageMaker Async (brain) | `LambdaSageMakerInference` (stub) |
| LLM | `TemplateLLM`: fills a fixed template, no model call | Amazon Bedrock | `BedrockLLM` (stub; Bedrock is blocked at the account level) |

Every AWS stub method raises `NotImplementedError` naming the service it will
call. Prompt 3 fills them.

Why Orthanc is a fair stand-in: HealthImaging's write surface is STOW-RS and its
read surface is QIDO-RS and WADO-RS. `tests/test_datastore_contract.py` holds
any datastore provider to the same assertions; HealthImaging is added to its
provider list in Prompt 3 and must pass unchanged. It already decodes HTJ2K
frames, which HealthImaging returns and Orthanc does not, so that branch has not
run yet.

Why DynamoDB has one implementation: `core/providers/aws/_dynamodb.py` is the
DynamoDB code for both runtimes. The local provider points it at
`http://localhost:8001` with dummy credentials. It lives under `aws/` because it
imports boto3, and no AWS SDK import is allowed anywhere else.

## Model registry

`models/registry.json` lists each model: modality, input format, runtime,
output type, adapter module and urgency weights. `core/registry.py` validates
it at load. An adapter that does not import, or a finding with no urgency
weight, is a startup error. The pipeline picks the entry by the study's
modality and calls the entry's adapter, which returns
`Findings(findings, evidence, meta)`. `triage.rank` reads `findings` and
nothing else.

| model | modality | runtime | adapter |
|---|---|---|---|
| `cxr-densenet-v1` | CR | lambda | `adapters.multilabel` |
| `brain-brats-monai-v0.5.4` | MR | sagemaker-async | `adapters.brats` |

## Moving from local to AWS

Today the switch is one variable, and the AWS side is not built:

```
AURALANE_RUNTIME=local    # default. Orthanc, DynamoDB Local, files, DevAuth
AURALANE_RUNTIME=aws      # AWS stubs. Every call raises NotImplementedError
```

The local runtime also needs:

```
docker compose -f docker-compose.local.yml up -d    # Orthanc 8042, DynamoDB Local 8001
AURALANE_DEV_JWT_SECRET=...                        # optional; else data/dev/devauth.key
```

PLANNED, NOT YET READ BY ANY CODE. The AWS providers will need at least the
following. The names are a plan for Prompt 3, not a contract:

| variable | for |
|---|---|
| `AWS_REGION=us-east-1` | every service; HealthImaging is not offered in Mumbai |
| `AURALANE_DATASTORE_ID` | the HealthImaging datastore the CDK stack creates |
| `AURALANE_BUCKET` | the S3 bucket for transient copies and evidence |
| `AURALANE_TABLE_PREFIX` | DynamoDB table names (`<prefix>-worklist`, `<prefix>-audit`) |
| `AURALANE_COGNITO_POOL_ID`, `AURALANE_COGNITO_CLIENT_ID` | token verification |
| `AURALANE_CHEST_FUNCTION`, `AURALANE_BRAIN_ENDPOINT` | Lambda function and SageMaker Async endpoint |

Credentials come from the standard AWS chain (environment, profile or role),
never from this repository.

## Commands

```
AURALANE_RUNTIME=local   python -m core.run ingest <study dir or .dcm>
AURALANE_RUNTIME=local   python -m core.run serve     # API on 127.0.0.1:8100
AURALANE_RUNTIME=fixture python -m core.run serve     # same API over fixtures/worklist.json
AURALANE_RUNTIME=local   python -m core.run token radiologist
cd client && npm install && npm run dev               # web app on 5173, /api proxied to 8100
python server.py                                      # round-2 demo, port 8000
```

`serve` uses 8100 because 8000 belongs to the round-2 demo, which is the
fallback and must start while the PoC stack is up.

## The fixture runtime

`AURALANE_RUNTIME=fixture` runs the API with no Docker and no `data/`: an
in-memory table seeded from `fixtures/worklist.json` and a read-only datastore
whose frame URLs point at static files the web server serves. The client makes
the same calls in every runtime and cannot tell which one answered. Each
fixture row carries a `source` field saying where its numbers came from
(`scores.json`, or Shaurya's recorded brain metrics) and what was assigned
rather than computed (arrival time, pseudonymous ID); the worklist shows it as
a tag. `scripts/make_fixtures.py` rebuilds the file.

## Access control

Enforced by the API on every route, not by the client:

| group | may | gets 403 on |
|---|---|---|
| radiologist | worklist, study detail, frame URLs, verdicts | `/api/admin/*` |
| admin | audit log, lane mix, model registry | worklist and every study route |

Admins configure the system; they do not read patient studies.
