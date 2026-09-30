import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import fixture from "./test/worklist.api.json";
import { LazyView } from "./components/ErrorBoundary.jsx";
import Shell from "./Shell.jsx";
import Worklist from "./Worklist.jsx";

vi.mock("./components/LatestCasePanel.jsx", () => ({
  default: ({ studyId }) => <div data-testid="case-stub">{studyId}</div>,
}));

async function show() {
  render(<MemoryRouter><Worklist load={() => Promise.resolve(fixture)} /></MemoryRouter>);
  if (fixture.me) await userEvent.click(await screen.findByTestId("scope-department"));
  await screen.findAllByTestId("study-row");
}
const sections = () => screen.getAllByTestId(/^section-/).map((el) => el.dataset.testid.replace("section-", ""));

describe("the dashboard", () => {
  it("counts what the rows say, and nothing else", async () => {
    await show();
    const critical = fixture.studies.filter((s) => s.lane === "CRITICAL").length;
    const triage = fixture.studies.filter((s) => s.lane === "ABSTAIN").length;
    expect(within(screen.getByTestId("stat-critical")).getByText(String(critical))).toBeInTheDocument();
    expect(within(screen.getByTestId("stat-triage")).getByText(String(triage))).toBeInTheDocument();
    // No verdicts in the fixture: the agreement figure is a dash, not a made-up percentage.
    expect(screen.getByTestId("stat-agreement")).toHaveTextContent("--");
    expect(screen.getByTestId("stat-agreement")).toHaveTextContent("0 verdicts");
  });

  it("lists the API's readers with their pools and unread counts", async () => {
    await show();
    const rows = within(screen.getByTestId("readers-card")).getAllByTestId("reader-row");
    expect(rows).toHaveLength((fixture.readers || []).length);
    if (rows.length) expect(rows[0]).toHaveTextContent(/\d+ unread/);
  });

  it("the Needs triage card filters the queue to abstentions, and back", async () => {
    await show();
    expect(sections().some((s) => s.endsWith("CRITICAL"))).toBe(true);
    await userEvent.click(screen.getByTestId("stat-triage"));
    expect(sections().every((s) => s.endsWith("ABSTAIN"))).toBe(true);
    await userEvent.click(screen.getByTestId("triage-only"));
    expect(sections().some((s) => s.endsWith("CRITICAL"))).toBe(true);
  });

  it("the pool tabs show one pool at a time and never merge them", async () => {
    await show();
    await userEvent.click(screen.getByTestId("pooltab-Neuro"));
    expect(screen.getByTestId("pool-Chest")).toHaveAttribute("hidden");
    expect(screen.getByTestId("pool-Neuro")).not.toHaveAttribute("hidden");
    await userEvent.click(screen.getByTestId("pooltab-ALL"));
    expect(screen.getByTestId("pool-Chest")).not.toHaveAttribute("hidden");
  });

  it("the Filter popover holds lane, status, modality and sort", async () => {
    await show();
    const filter = screen.getByTestId("filter-button");
    expect(filter).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(filter);
    expect(filter).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(screen.getByTestId("specialty-MR"));
    const mr = fixture.studies.filter((s) => s.modality === "MR").length;
    expect(screen.getAllByTestId("study-row")).toHaveLength(mr);
    expect(filter).toHaveTextContent("1");                       // one filter active
    await userEvent.keyboard("{Escape}");
    expect(filter).toHaveAttribute("aria-expanded", "false");
  });

  it("the board keeps each reading pool in its own section", async () => {
    await show();
    await userEvent.click(screen.getByTestId("view-board"));
    const chest = screen.getByTestId("board-pool-Chest");
    const neuro = screen.getByTestId("board-pool-Neuro");
    const cards = (el) => within(el).getAllByTestId("board-card").map((c) => c.dataset.study);
    const pool = (p) => fixture.studies.filter((s) => s.pool === p).map((s) => s.study);
    expect(cards(chest).sort()).toEqual(pool("Chest").sort());
    expect(cards(neuro).sort()).toEqual(pool("Neuro").sort());
  });
});

describe("the top bar", () => {
  const session = { user: { email: "radiologist@dev.auralane.local", groups: ["radiologist"] } };

  it("carries the non-diagnostic notice as one chip, and Sign out in the user menu", async () => {
    const onSignOut = vi.fn();
    render(<MemoryRouter><Shell session={session} onSignOut={onSignOut}><p>page</p></Shell></MemoryRouter>);
    expect(screen.getAllByRole("note", { name: "Non-diagnostic notice" })).toHaveLength(1);
    expect(screen.getByRole("contentinfo")).toHaveTextContent("Not a medical device");
    await userEvent.click(screen.getByTestId("user-menu"));
    await userEvent.click(screen.getByRole("menuitem", { name: "Sign out" }));
    expect(onSignOut).toHaveBeenCalled();
  });

  it("gives an administrator their own destinations as links", () => {
    render(
      <MemoryRouter initialEntries={["/admin/audit"]}>
        <Shell session={{ user: { email: "admin@dev.auralane.local", groups: ["admin"] } }} onSignOut={vi.fn()}><p>page</p></Shell>
      </MemoryRouter>);
    for (const name of ["Pipeline", "Assignments", "Audit log", "Simulated intake", "Lane mix", "Thresholds", "Model registry"]) {
      expect(screen.getByRole("link", { name })).toBeInTheDocument();
    }
  });

  it("still shows the notice when signed out", () => {
    render(<MemoryRouter><Shell session={null} onSignOut={vi.fn()}><p>sign in</p></Shell></MemoryRouter>);
    expect(screen.getByRole("note", { name: "Non-diagnostic notice" })).toBeInTheDocument();
  });
});

describe("a viewer that will not load", () => {
  it("says so inside its own place, and retries the import", async () => {
    let attempts = 0;
    const load = () => {
      attempts += 1;
      return attempts === 1 ? Promise.reject(new Error("chunk failed")) : Promise.resolve({ default: () => <p>viewer is up</p> });
    };
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(<div><p>the sheet stays</p><LazyView load={load} what="Viewer" /></div>);
    expect(await screen.findByRole("alert")).toHaveTextContent("Viewer failed to load");
    expect(screen.getByText("the sheet stays")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Retry/ }));
    await waitFor(() => expect(screen.getByText("viewer is up")).toBeInTheDocument());
    expect(attempts).toBe(2);
    console.error.mockRestore();
  });
});
