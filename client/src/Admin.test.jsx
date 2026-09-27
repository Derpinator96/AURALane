import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import fixture from "./test/admin.api.json";
import Admin from "./Admin.jsx";

// Test data for the audit screen only: the fixture API has no audit events
// until someone records a verdict, and real ones carry the time they ran.
const AUDIT = {
  total: 1,
  events: [{ event_id: "2026-09-25T20:00:44+00:00#0001", at: "2026-09-25T20:00:44+00:00",
             actor: "radiologist@dev.auralane.local", action: "verdict", study: "fixture-cr-ST-028",
             outcome: "ok", duration_ms: 0.4, detail: { verdict: "disagree", lane: "ABSTAIN" } }],
};

// Stable loaders, as App passes them (useCallback): a new function each
// render would reload forever.
const loadAudit = () => Promise.resolve(AUDIT);
const loadLaneMix = () => Promise.resolve(fixture.lane_mix);
const loadModels = () => Promise.resolve(fixture.models);

function show(path) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/admin/*" element={
          <Admin loadAudit={loadAudit} loadLaneMix={loadLaneMix} loadModels={loadModels} />} />
      </Routes>
    </MemoryRouter>);
}

describe("Admin", () => {
  it("lists audit events and never links a study", async () => {
    show("/admin/audit");
    const table = await screen.findByTestId("audit");
    expect(within(table).getByText("fixture-cr-ST-028")).toBeInTheDocument();
    expect(within(table).getByText(/verdict=disagree/)).toBeInTheDocument();
    expect(document.querySelectorAll("a[href*='/studies/']")).toHaveLength(0);
  });

  it("shows the lane mix exactly as counted by the API", async () => {
    show("/admin/lanes");
    const rows = within(await screen.findByTestId("lane-mix")).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(fixture.lane_mix.lanes.length);
    fixture.lane_mix.lanes.forEach((l, i) => {
      expect(rows[i]).toHaveTextContent(l.label);
      expect(rows[i]).toHaveTextContent(`${l.count}${l.percent}%`);
    });
    expect(screen.getByText(new RegExp(fixture.lane_mix.basis))).toBeInTheDocument();
  });

  it("shows lane floors and the abstention band read only", async () => {
    show("/admin/thresholds");
    const floors = await screen.findByTestId("lane-floors");
    for (const l of fixture.models.lanes) expect(floors).toHaveTextContent(`${l.lane}${l.acuity_floor}${l.clock}`);
    const [lo, hi] = fixture.models.abstain_band;
    expect(screen.getByTestId("abstain-band")).toHaveTextContent(`between ${lo} and ${hi}`);
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("spinbutton")).toBeNull();
  });

  it("lists every registry model with its urgency weights", async () => {
    show("/admin/models");
    const cards = await screen.findAllByTestId("model");
    expect(cards.map((c) => within(c).getByRole("heading").textContent))
      .toEqual(fixture.models.models.map((m) => m.id));
    expect(cards[0]).toHaveTextContent("Pneumothorax1.00");
  });
});
