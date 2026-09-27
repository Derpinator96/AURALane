import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import fixture from "./test/study.api.json";
import Study from "./Study.jsx";

// Cornerstone needs WebGL and workers, which jsdom lacks; the viewer is
// exercised end to end by Playwright. Here a stub records what it is given.
vi.mock("./viewer/Viewer.jsx", () => ({
  default: ({ instances, overlay }) => (
    <div data-testid="viewer-stub" data-overlay={overlay ? overlay.url : "none"}
         data-count={instances.length} />
  ),
}));

const { detail, series } = fixture;

function show(sendVerdict = vi.fn()) {
  render(
    <MemoryRouter initialEntries={[`/studies/${detail.study.study}`]}>
      <Routes>
        <Route path="/studies/:id" element={
          <Study load={() => Promise.resolve(detail)} loadSeries={() => Promise.resolve(series)}
                 sendVerdict={sendVerdict} />} />
      </Routes>
    </MemoryRouter>);
  return screen.findByTestId("viewer-stub");
}

describe("Study", () => {
  it("opens with the triage rationale off", async () => {
    const viewer = await show();
    const toggle = screen.getByTestId("rationale-toggle");
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(toggle).toHaveTextContent("Triage rationale: off");
    expect(viewer).toHaveAttribute("data-overlay", "none");
    expect(screen.queryByTestId("rationale-caption")).toBeNull();
    expect(viewer).toHaveAttribute("data-count", String(series.instances.length));
  });

  it("toggles the rationale overlay on and off, labelled as rationale", async () => {
    const viewer = await show();
    const toggle = screen.getByTestId("rationale-toggle");
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(viewer).toHaveAttribute("data-overlay", detail.evidence_urls.gradcam_layer_png);
    const caption = screen.getByTestId("rationale-caption");
    expect(caption).toHaveTextContent(`Grad-CAM for ${detail.evidence.gradcam_finding}`);
    expect(caption).toHaveTextContent("not a localisation");
    expect(caption).not.toHaveTextContent(/finding:/i);
    await userEvent.click(toggle);
    expect(viewer).toHaveAttribute("data-overlay", "none");
  });

  it("shows lane, driver and every finding exactly as the API sent them", async () => {
    await show();
    expect(screen.getByText(detail.study.lane_label)).toBeInTheDocument();
    const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
    expect(rows.map((r) => r.cells[0].textContent)).toEqual(detail.findings.map((f) => f.label));
    expect(rows.map((r) => r.cells[1].textContent)).toEqual(
      detail.findings.map((f) => f.signal.toFixed(3)));
  });

  it("agree writes through the API and updates the verdict in place", async () => {
    const updated = { ...detail.study, verdict: { value: "agree", by: "radiologist@dev.auralane.local", at: "2026-09-26T09:00:00+00:00" } };
    const send = vi.fn().mockResolvedValue({ study: updated });
    await show(send);
    expect(screen.getByTestId("verdict-status")).toHaveTextContent("No verdict yet.");
    await userEvent.click(screen.getByRole("button", { name: "Agree" }));
    expect(send).toHaveBeenCalledWith(detail.study.study, "agree");
    expect(screen.getByTestId("verdict-status")).toHaveTextContent("Agreed by radiologist@dev.auralane.local");
    expect(screen.getByRole("button", { name: "Agree" })).toHaveAttribute("aria-pressed", "true");
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

  it("brain rationale shows the segmentation image, off by default, and no confidence", async () => {
    render(
      <MemoryRouter initialEntries={["/studies/x"]}>
        <Routes><Route path="/studies/:id" element={
          <Study load={() => Promise.resolve(brain)} loadSeries={() => Promise.resolve(series)}
                 sendVerdict={vi.fn()} />} /></Routes>
      </MemoryRouter>);
    await screen.findByTestId("viewer-stub");
    expect(screen.queryByTestId("rationale-image")).toBeNull();
    expect(screen.getByText(/the brain model reports volumes, not a probability/)).toBeInTheDocument();
    await userEvent.click(screen.getByTestId("rationale-toggle"));
    const fig = screen.getByTestId("rationale-image");
    expect(within(fig).getByRole("img")).toHaveAttribute("src", brain.evidence_urls.overlay_png);
    expect(fig).toHaveTextContent("axial index 75");
    expect(screen.getByTestId("viewer-stub")).toHaveAttribute("data-overlay", "none");
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
    expect(screen.queryByRole("button", { name: "Agree" })).toBeNull();
    expect(screen.getByTestId("no-findings")).toHaveTextContent("did not reach the model output");
    expect(screen.getByTestId("rationale-toggle")).toBeDisabled();
  });
});
