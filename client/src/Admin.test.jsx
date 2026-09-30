import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import fixture from "./test/admin.api.json";
import Admin, { Intake } from "./Admin.jsx";
import { laneName } from "./worklist.js";
import userEvent from "@testing-library/user-event";

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
      expect(rows[i]).toHaveTextContent(laneName(l.lane, l.label));
      expect(rows[i]).toHaveTextContent(`${l.count}${l.percent}%`);
    });
    expect(screen.getByText(new RegExp(fixture.lane_mix.basis))).toBeInTheDocument();
  });

  it("shows lane floors and the abstention band read only", async () => {
    show("/admin/thresholds");
    const floors = await screen.findByTestId("lane-floors");
    for (const l of fixture.models.lanes) expect(floors).toHaveTextContent(`${laneName(l.lane)}${l.acuity_floor}${l.clock}`);
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

describe("Intake", () => {
  it("says why it is unavailable and keeps the button off", async () => {
    const load = () => Promise.resolve({ available: false, reason: "no study corpus on this host",
                                         running: false, catalogue: { CR: 0, MR: 0, CT: 0 }, runtime: "aws" });
    render(<Intake load={load} start={vi.fn()} />);
    expect(await screen.findByTestId("intake-unavailable")).toHaveTextContent("no study corpus on this host");
    expect(screen.getByTestId("intake-start")).toBeDisabled();
  });

  it("starts a run and shows each study's real result", async () => {
    const running = { available: true, running: false, catalogue: { CR: 40, MR: 2, CT: 2 }, runtime: "local",
                      total: 2, done: 1, failed: 1, by: "admin@dev.auralane.local", started_at: "2026-09-28T10:00:00+00:00",
                      items: [{ modality: "CT", source: "CQ500CT419", status: "SCORED", lane: "URGENT", seconds: 92.5 },
                              { modality: "MR", source: "x", status: "FAILED", lane: "FAILED", error: "LookupError: y", seconds: 3 }] };
    // As the API does: after a start, polling returns the run's state.
    let current = { ...running, total: undefined, items: [] };
    const start = vi.fn(async () => (current = running));
    render(<Intake load={() => Promise.resolve(current)} start={start} />);
    await userEvent.click(await screen.findByTestId("intake-start"));
    expect(start).toHaveBeenCalledWith(30);
    expect(await screen.findByTestId("intake-progress")).toHaveTextContent("1 scored, 1 failed, of 2");
    expect(screen.getByText("Urgent")).toBeInTheDocument();
    expect(screen.getByText(/FAILED: LookupError: y/)).toBeInTheDocument();
  });
});
