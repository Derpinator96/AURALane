import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { Pipeline } from "./AdminOps.jsx";

const stage = (stage, label, count, service) =>
  ({ stage, label, count, failed: 0, median_ms: count ? 1200 : null, last_ms: count ? 900 : null, service, services: [] });

const data = {
  runtime: "local", basis: "Every figure is counted from audit events.",
  stages: [stage("receive", "Receive", 2, "local staged pool"), stage("deidentify", "De-identify", 2, "edge"),
           stage("store", "Store", 2, "Orthanc (DICOMweb)"), stage("prepare", "Prepare inputs", 1, "x"),
           stage("infer", "Infer", 1, "in-process PyTorch"), stage("adapt", "Adapt", 1, null),
           stage("regional", "Regional prior", 0, null), stage("triage", "Triage", 1, null),
           stage("evidence", "Evidence", 1, "local filesystem"), stage("persist", "Persist", 1, "DynamoDB Local")],
  live: [{ study: "1.2.3.4.5.6.7.8.9.10.11", batch: "b1", type: "chest", modality: "CR", status: "running",
           stage: "infer", failed: false, done: false, lane: null, end_to_end_ms: 3000 }],
  batches: [{ batch: "b1", running: true }], recent: [],
  totals: { day: "2026-09-28", studies: 1, by_modality_lane: [{ modality: "CR", lane: "URGENT", count: 1 }],
            end_to_end_median_ms: { CR: 8000 }, end_to_end_n: { CR: 1 } },
  overdue: [{ study: "9.9.9", assigned_name: "Reader 2" }],
};

describe("Pipeline", () => {
  it("draws every stage with its service and counts, the study in flight, and overdue critical work", async () => {
    render(<Pipeline load={() => Promise.resolve(data)} loadStudy={() => Promise.resolve(null)} />);
    const flow = await screen.findByTestId("pipe-flow");
    expect(within(flow).getAllByRole("listitem")).toHaveLength(10);
    expect(flow).toHaveTextContent("Orthanc (DICOMweb)");
    expect(within(screen.getByTestId("pipe-live")).getByRole("button")).toHaveTextContent("chest");
    expect(screen.getByTestId("pipe-overdue")).toHaveTextContent("Reader 2");
    expect(screen.getByTestId("pipe-today")).toHaveTextContent("8.0 s");
  });
});
