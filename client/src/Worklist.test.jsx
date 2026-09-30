import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import fixture from "./test/worklist.api.json";
import Worklist from "./Worklist.jsx";
import { laneName } from "./worklist.js";

// The department queue: every study, as the API ordered it.
async function show() {
  render(<MemoryRouter><Worklist load={() => Promise.resolve(fixture)} /></MemoryRouter>);
  if (fixture.me) await userEvent.click(await screen.findByTestId("scope-department"));
  await screen.findAllByTestId("study-row");
}
// "Pool-LANE" for every section on screen, in display order.
const sections = () =>
  screen.getAllByTestId(/^section-/).map((el) => el.dataset.testid.replace("section-", ""));
const sectionLanes = (pool) =>
  sections().filter((s) => s.startsWith(`${pool}-`)).map((s) => s.slice(pool.length + 1));
const rowIds = () => screen.getAllByTestId("study-row").map((el) => el.dataset.study);
const inPool = (pool) => fixture.studies.filter((r) => r.pool === pool);

describe("Worklist", () => {
  it("sections by reading pool, then lane, ranking only within a pool", async () => {
    await show();
    expect(screen.getAllByTestId(/^pool-/).map((el) => el.dataset.testid))
      .toEqual(fixture.pools.map((p) => `pool-${p.pool}`));
    expect(sectionLanes("Chest")).toEqual(["CRITICAL", "URGENT", "ABSTAIN", "EXPEDITED", "ROUTINE"]);
    // Neuro has no abstention in the fixture; its section is still there.
    expect(sectionLanes("Neuro")).toEqual(["CRITICAL", "URGENT", "ABSTAIN"]);
    // Within each pool, rows keep the API's order; no row sits in the wrong pool.
    const expected = fixture.pools.flatMap((p) => inPool(p.pool).map((r) => r.study));
    expect(rowIds()).toEqual(expected);
    for (const p of fixture.pools) {
      for (const row of within(screen.getByTestId(`pool-${p.pool}`)).queryAllByTestId("study-row")) {
        expect(fixture.studies.find((r) => r.study === row.dataset.study).pool).toBe(p.pool);
      }
    }
  });

  it("gives each reading pool its own heading and count, and never one merged list", async () => {
    await show();
    for (const p of fixture.pools) {
      const section = screen.getByTestId(`pool-${p.pool}`);
      expect(within(section).getByRole("heading", { level: 3, name: new RegExp(`^${p.label} pool`) })).toBeInTheDocument();
      expect(section).toHaveTextContent(`${inPool(p.pool).length} studies`);
    }
  });

  it("shows the abstention group, labelled, with its count", async () => {
    await show();
    const group = screen.getByTestId("section-Chest-ABSTAIN");
    expect(within(group).getByRole("heading")).toHaveTextContent("Abstention Tray");
    const n = fixture.studies.filter((r) => r.lane === "ABSTAIN").length;
    expect(within(group).getAllByTestId("study-row")).toHaveLength(n);
    expect(within(group).getByTitle(`${n} ${n === 1 ? "study" : "studies"}`)).toHaveTextContent(String(n));
    // The tray has no reading clock to show; the old description of what a human does is gone.
    expect(within(group).getByRole("heading")).not.toHaveTextContent("a human picks the lane");
  });

  it("writes every lane name out and shows acuity exactly as the API sent it", async () => {
    await show();
    for (const row of screen.getAllByTestId("study-row")) {
      const api = fixture.studies.find((r) => r.study === row.dataset.study);
      // A row inside its lane section names the lane for screen readers; the heading shows it.
      expect(within(row).getByText(laneName(api.lane, api.lane_label))).toBeInTheDocument();
      const shown = row.querySelector(".acuity").textContent;
      expect(shown).toBe(api.lane === "ABSTAIN" ? "--" : api.acuity.toFixed(1));
    }
  });

  it("the sort control changes the order", async () => {
    await show();
    const before = rowIds();
    await userEvent.selectOptions(screen.getByLabelText("Sort"), "arrival-oldest");
    expect(rowIds()).not.toEqual(before);
    expect(sectionLanes("Chest")[0]).toBe("ABSTAIN");
    expect(sectionLanes("Neuro")[0]).toBe("ABSTAIN");
  });

  it("the lane filter narrows the list but cannot hide the abstention group", async () => {
    await show();
    await userEvent.selectOptions(screen.getByLabelText("Lane filter"), "ROUTINE");
    expect(sectionLanes("Chest")).toEqual(["ABSTAIN", "ROUTINE"]);
    expect(sectionLanes("Neuro")).toEqual(["ABSTAIN"]);
  });
});

describe("Worklist, readers", () => {
  const me = "radiologist-1@dev.auralane.local";
  const withReaders = {
    ...fixture, me,
    readers: [{ id: me, name: "Reader 1", pools: ["Chest", "Neuro"] },
              { id: "radiologist-2@dev.auralane.local", name: "Reader 2", pools: ["Chest"] }],
    studies: fixture.studies.map((s, i) => ({ ...s, assigned_to: i === 0 ? me : null,
                                              assigned_name: i === 0 ? "Reader 1" : null })),
  };

  it("shows only my studies by default, the department on request, and the reader on every row", async () => {
    render(<MemoryRouter><Worklist load={() => Promise.resolve(withReaders)} /></MemoryRouter>);
    await screen.findAllByTestId("study-row");
    expect(rowIds()).toEqual([withReaders.studies[0].study]);
    expect(within(screen.getByTestId("study-row")).getByTestId("assigned")).toHaveTextContent("You");
    await userEvent.click(screen.getByTestId("scope-department"));
    expect(rowIds()).toHaveLength(fixture.studies.length);
    expect(screen.getAllByTestId("assigned").some((el) => el.textContent.includes("Unassigned"))).toBe(true);
  });
});
