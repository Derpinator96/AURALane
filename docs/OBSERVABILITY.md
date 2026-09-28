# Observability: the pipeline view, Prometheus and Grafana

NON-DIAGNOSTIC; DECISION SUPPORT ONLY.

Every pipeline step writes an audit event with its measured duration and the
service that ran it (core/pipeline.py). The admin "Pipeline" screen and
`GET /metrics` are both computed from those events by core/pipeline_view.py;
nothing is sampled or estimated, and a stage with no events shows no figure.
Runs recorded before steps named their service are attributed by runtime
(HealthImaging, S3, DynamoDB on AWS; the registry runtime for infer).

`GET /metrics` is Prometheus text: `auralane_stage_duration_seconds` (a histogram
per stage and service, buckets 50 ms to 10 min) and `auralane_worklist_studies`
(a gauge per modality and lane). It answers an admin's bearer token, or the
value of `AURALANE_METRICS_TOKEN` when that is set on the API.

## Prometheus and Grafana, in Docker

`infra/monitoring/docker-compose.yml` runs Prometheus (scraping `/metrics` every
15 s with the token) and Grafana with the "AURALane pipeline" dashboard
provisioned: studies by lane and modality, median seconds per stage, runs per
stage and service, and the lane mix over time.

1. Set `AURALANE_METRICS_TOKEN` on the API (Render: auralane-api, Environment)
   to a long random value, and put the same value in
   `infra/monitoring/metrics_token` (gitignored).
2. Start both, pointed at the API:

   ```
   AURALANE_METRICS_URL=https://auralane-api.onrender.com docker compose -f infra/monitoring/docker-compose.yml up -d
   ```

   For a local API use `http://host.docker.internal:8100`; the API must listen
   on an interface Docker can reach, not only 127.0.0.1.
3. Grafana: http://localhost:3000 (anonymous, read only). Prometheus:
   http://localhost:9090/targets shows whether the scrape succeeds.

History starts when Prometheus starts: the in-app Pipeline screen recomputes
from the audit table at request time, Prometheus keeps what it scraped.
