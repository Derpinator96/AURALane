import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import fixture from "./test/worklist.api.json";
import Worklist from "./Worklist.jsx";

async function show() {
  render(<MemoryRouter><Worklist load={() => Promise.resolve(fixture)} /></MemoryRouter>);
  await screen.findAllByTestId("study-row");
}
const sectionLanes = () =>
  screen.getAllByTestId(/^section-/).map((el) => el.dataset.testid.replace("section-", ""));
const rowIds = () => screen.getAllByTestId("study-row").map((el) => el.dataset.study);

describe("Worklist", () => {
  it("renders the fixture in lane order, one row per study", async () => {
    await show();
    expect(sectionLanes()).toEqual(["CRITICAL", "URGENT", "ABSTAIN", "EXPEDITED", "ROUTINE"]);
    expect(rowIds()).toEqual(fixture.studies.map((r) => r.study));
  });

  it("shows the abstention group, labelled, with its reason", async () => {
    await show();
    const group = screen.getByTestId("section-ABSTAIN");
    expect(within(group).getByRole("heading")).toHaveTextContent("NEEDS HUMAN TRIAGE");
    expect(within(group).getByText(/not sufficient to assign a lane/)).toBeInTheDocument();
    const n = fixture.studies.filter((r) => r.lane === "ABSTAIN").length;
    expect(within(group).getAllByTestId("study-row")).toHaveLength(n);
    expect(within(group).getByRole("heading")).toHaveTextContent(`(${n})`);
  });

  it("writes every lane name out and shows acuity exactly as the API sent it", async () => {
    await show();
    for (const row of screen.getAllByTestId("study-row")) {
      const api = fixture.studies.find((r) => r.study === row.dataset.study);
      expect(within(row).getByText(api.lane_label)).toBeInTheDocument();
      const shown = row.querySelector(".acuity").textContent;
      expect(shown).toBe(api.lane === "ABSTAIN" ? "--" : api.acuity.toFixed(1));
    }
  });

  it("the sort control changes the order", async () => {
    await show();
    const before = rowIds();
    await userEvent.selectOptions(screen.getByLabelText("Sort"), "arrival-oldest");
    expect(rowIds()).not.toEqual(before);
    expect(sectionLanes()[0]).toBe("ABSTAIN");
  });

  it("the lane filter narrows the list but cannot hide the abstention group", async () => {
    await show();
    await userEvent.selectOptions(screen.getByLabelText("Lane filter"), "ROUTINE");
    expect(sectionLanes()).toEqual(["ABSTAIN", "ROUTINE"]);
  });
});
