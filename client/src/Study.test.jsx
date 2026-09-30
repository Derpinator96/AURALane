import { describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import fixture from "./test/study.api.json";
import Study, { RegionalContext } from "./Study.jsx";
import { laneName } from "./worklist.js";

// Cornerstone needs WebGL and workers, which jsdom lacks; the viewer is
// exercised end to end by Playwright. Here a stub records what it is given.
vi.mock("./viewer/Viewer.jsx", () => ({
  default: ({ instances, overlay }) => (
    <div data-testid="viewer-stub" data-overlay={overlay ? overlay.url : "none"}
         data-count={instances.length} />
  ),
}));

const { detail, series } = fixture;

function show(sendVerdict = vi.fn(), saveDraft = vi.fn(), d = detail) {
  render(
    <MemoryRouter initialEntries={[`/studies/${d.study.study}`]}>
      <Routes>
        <Route path="/studies/:id" element={
          <Study load={() => Promise.resolve(d)} loadSeries={() => Promise.resolve(series)}
                 sendVerdict={sendVerdict} saveDraft={saveDraft} />} />
      </Routes>
    </MemoryRouter>);
  return screen.findByTestId("viewer-stub");
}

describe("Study", () => {
  it("opens with the Grad-CAM overlay on, the finding named and an opacity slider", async () => {
    const viewer = await show();
    const toggle = screen.getByTestId("rationale-toggle");
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(viewer).toHaveAttribute("data-overlay", detail.evidence_urls.gradcam_layer_png);
    const caption = screen.getByTestId("rationale-caption");
    expect(caption).toHaveTextContent(`Grad-CAM for ${detail.evidence.gradcam_finding}`);
    // The caveat is the button's tooltip, not a sentence on the page.
    expect(caption).not.toHaveTextContent("not a localisation");
    expect(toggle).toHaveAttribute("title", expect.stringContaining("not a localisation"));
    expect(screen.getByTestId("rationale-opacity")).toBeInTheDocument();
    expect(viewer).toHaveAttribute("data-count", String(series.instances.length));
  });

  it("turns the overlay off and on again", async () => {
    const viewer = await show();
    const toggle = screen.getByTestId("rationale-toggle");
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(viewer).toHaveAttribute("data-overlay", "none");
    await userEvent.click(toggle);
    expect(viewer).toHaveAttribute("data-overlay", detail.evidence_urls.gradcam_layer_png);
  });

  it("says plainly when Grad-CAM has nothing above threshold, and draws nothing", async () => {
    const empty = { ...detail, evidence: { ...detail.evidence, gradcam_coverage: 0 } };
    const viewer = await show(vi.fn(), vi.fn(), empty);
    expect(screen.getByTestId("rationale-caption"))
      .toHaveTextContent(`Grad-CAM found no region at or above the display threshold for ${detail.evidence.gradcam_finding}`);
    expect(viewer).toHaveAttribute("data-overlay", "none");
  });

  it("shows the draft beside the viewer, labelled, editable, and marks it reviewed", async () => {
    const save = vi.fn().mockResolvedValue({ draft_review: { text: "x", reviewed: true, by: "r1", at: "t" } });
    await show(vi.fn(), save);
    const panel = screen.getByTestId("draft-panel");
    expect(panel).toHaveAccessibleName("Draft report");
    expect(panel).toHaveTextContent("Not reviewed");
    const text = screen.getByTestId("draft-text");
    expect(text.value).toBe(detail.draft);
    await userEvent.type(text, " Edited.");
    await userEvent.click(screen.getByTestId("draft-reviewed"));
    expect(save).toHaveBeenCalledWith(detail.study.study, `${detail.draft} Edited.`, true);
    expect(screen.getByTestId("draft-status")).toHaveTextContent("Reviewed by r1");
  });

  it("shows lane, driver and every finding exactly as the API sent them", async () => {
    await show();
    expect(screen.getAllByText(laneName(detail.study.lane, detail.study.lane_label)).length).toBeGreaterThan(0);
    const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
    expect(rows.map((r) => r.cells[0].textContent.replace("DRIVER", ""))).toEqual(detail.findings.map((f) => f.label));
    expect(rows.map((r) => r.cells[2].textContent)).toEqual(
      detail.findings.map((f) => f.signal.toFixed(3)));
  });

  it("the verdict sits in the decision tile with the lane, finding and acuity, ahead of the draft", async () => {
    await show();
    const tile = screen.getByRole("region", { name: "Decision" });
    expect(within(tile).getByRole("button", { name: "Agree with the lane" })).toBeInTheDocument();
    expect(within(tile).getByRole("button", { name: "Disagree" })).toBeInTheDocument();
    expect(within(tile).getByRole("heading", { level: 2 })).toHaveTextContent(detail.study.driver_label);
    expect(tile).toHaveTextContent(laneName(detail.study.lane, detail.study.lane_label));
    // The draft comes later in the page than the verdict, so the verdict never waits behind it.
    const draft = screen.getByTestId("draft-panel");
    expect(tile.compareDocumentPosition(draft) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("agree writes through the API and updates the verdict in place", async () => {
    const updated = { ...detail.study, verdict: { value: "agree", by: "radiologist@dev.auralane.local", at: "2026-09-26T09:00:00+00:00" } };
    const send = vi.fn().mockResolvedValue({ study: updated });
    await show(send);
    expect(screen.getByTestId("verdict-status")).toHaveTextContent("No verdict yet.");
    await userEvent.click(screen.getByRole("button", { name: "Agree with the lane" }));
    expect(send).toHaveBeenCalledWith(detail.study.study, "agree");
    expect(screen.getByTestId("verdict-status")).toHaveTextContent("Agreed by radiologist@dev.auralane.local");
    expect(screen.getByRole("button", { name: "Agree with the lane" })).toHaveAttribute("aria-pressed", "true");
  });

  it("states the datastore note only when the API sends one", async () => {
    // The fixture API sends one; Orthanc and HealthImaging send null.
    await show();
    expect(screen.getByTestId("datastore-note")).toHaveTextContent(detail.datastore_note);
    expect(detail.datastore_note).toMatch(/^No DICOM datastore is connected/);
    cleanup();
    render(
      <MemoryRouter initialEntries={["/studies/x"]}>
        <Routes><Route path="/studies/:id" element={
          <Study load={() => Promise.resolve({ ...detail, datastore_note: null })}
                 loadSeries={() => Promise.resolve(series)} sendVerdict={vi.fn()} />} /></Routes>
      </MemoryRouter>);
    await screen.findByTestId("viewer-stub");
    expect(screen.queryByTestId("datastore-note")).toBeNull();
  });
});

describe("Study, brain and failed rows", () => {
  const brain = {
    ...detail,
    study: { ...detail.study, modality: "MR", exam: "MR Brain", driver: "enhancing_tumor",
             driver_label: "Enhancing tumor", confidence: null },
    evidence: { overlay_png: "evidence/x/segmentation_overlay.png", axial_index: 75 },
    evidence_urls: { overlay_png: "/api/blob/evidence/x/segmentation_overlay.png?signed" },
  };

  it("brain rationale shows the segmentation image on open, and no confidence", async () => {
    render(
      <MemoryRouter initialEntries={["/studies/x"]}>
        <Routes><Route path="/studies/:id" element={
          <Study load={() => Promise.resolve(brain)} loadSeries={() => Promise.resolve(series)}
                 sendVerdict={vi.fn()} />} /></Routes>
      </MemoryRouter>);
    await screen.findByTestId("viewer-stub");
    expect(screen.getByText(/the brain model reports volumes, not a probability/)).toBeInTheDocument();
    const fig = screen.getByTestId("rationale-image");
    expect(within(fig).getByRole("img")).toHaveAttribute("src", brain.evidence_urls.overlay_png);
    expect(fig).toHaveTextContent("axial index 75");
    expect(screen.getByTestId("viewer-stub")).toHaveAttribute("data-overlay", "none");
    await userEvent.click(screen.getByTestId("rationale-toggle"));
    expect(screen.queryByTestId("rationale-image")).toBeNull();
  });

  it("a failed study offers no verdict and says why", async () => {
    const failed = { ...detail, findings: [], evidence: {}, evidence_urls: {},
                     study: { ...detail.study, lane: "FAILED", lane_label: "PIPELINE FAILED",
                              error: "RuntimeError: model unavailable" } };
    render(
      <MemoryRouter initialEntries={["/studies/x"]}>
        <Routes><Route path="/studies/:id" element={
          <Study load={() => Promise.resolve(failed)} loadSeries={() => Promise.resolve(series)}
                 sendVerdict={vi.fn()} />} /></Routes>
      </MemoryRouter>);
    await screen.findByTestId("viewer-stub");
    expect(screen.queryByRole("button", { name: "Agree with the lane" })).toBeNull();
    expect(screen.getByTestId("no-findings")).toHaveTextContent("did not reach the model output");
    expect(screen.getByTestId("rationale-toggle")).toBeDisabled();
  });

  it("a study that fails the segmentation check says not verified, never broken", async () => {
    const reason = "Segmentation could not be automatically verified (failed: largest_component)";
    const unverified = { ...detail, findings: [], evidence: {}, evidence_urls: {},
                         study: { ...detail.study, modality: "MR", lane: "ABSTAIN", driver: null,
                                  driver_label: null, lane_label: "NEEDS HUMAN TRIAGE",
                                  abstain_reason: reason } };
    render(
      <MemoryRouter initialEntries={["/studies/x"]}>
        <Routes><Route path="/studies/:id" element={
          <Study load={() => Promise.resolve(unverified)} loadSeries={() => Promise.resolve(series)}
                 sendVerdict={vi.fn()} />} /></Routes>
      </MemoryRouter>);
    await screen.findByTestId("viewer-stub");
    const note = screen.getByTestId("abstain-reason");
    expect(note).toHaveTextContent("could not be automatically verified");
    expect(note.textContent.toLowerCase()).not.toMatch(/broken|wrong|invalid/);
  });
});

describe("RegionalContext", () => {
  it("shows the state and the factor applied to the driving finding", () => {
    const regional = { state: "Kerala", applied: true,
                       factors: { Pneumonia: { factor: 1.1565 } } };
    render(<RegionalContext regional={regional} driver="Pneumonia" driverLabel="Pneumonia" />);
    expect(screen.getByTestId("regional-context")).toHaveTextContent("Regional context: Kerala, x1.16");
    cleanup();
    render(<RegionalContext regional={regional} driver="Edema" driverLabel="Edema" />);
    expect(screen.getByTestId("regional-context")).toHaveTextContent("x1.00 (no regional prior for Edema)");
    cleanup();
    render(<RegionalContext regional={{ state: "Kerala", applied: false, reason: "off" }} driver="Edema" />);
    expect(screen.getByTestId("regional-context")).toHaveTextContent("Regional context: off");
  });
});
