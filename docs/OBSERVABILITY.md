# Observability: the pipeline view, and Grafana later

NON-DIAGNOSTIC; DECISION SUPPORT ONLY.

Every pipeline step writes an audit event with its measured duration and the
service that ran it (core/pipeline.py). The admin "Pipeline" screen and
`GET /metrics` are both computed from those events by core/pipeline_view.py;
nothing is sampled or estimated, and a stage with no events shows no figure.

`GET /metrics` is Prometheus text: `auralane_stage_duration_seconds` (a histogram
per stage and service, buckets 50 ms to 10 min) and `auralane_worklist_studies`
(a gauge per modality and lane). It answers an admin's bearer token, or the
value of `AURALANE_METRICS_TOKEN` when that is set on the API.

**Attaching Grafana later.** Nothing needs to change in AURALane. Set
`AURALANE_METRICS_TOKEN` to a long random value on the API, then point any
Prometheus-compatible scraper at `https://<api>/metrics` with that value as its
bearer token (in Prometheus, `authorization: {credentials: <token>}` in the
scrape config; Grafana Cloud's hosted collector and Amazon Managed Service for
Prometheus both accept the same). Add that Prometheus as a Grafana data source
and chart `histogram_quantile(0.5, sum by (le, stage) (rate(auralane_stage_duration_seconds_bucket[15m])))`
for median stage time. The in-app screen stays the reference for a demo because
it needs nothing hosted; Grafana adds history, since the in-app view recomputes
from the audit table at request time.
