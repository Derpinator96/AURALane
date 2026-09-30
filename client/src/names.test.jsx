import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { api } from "./api.js";
import fixture from "./test/worklist.api.json";
import { NamesProvider, PatientLabel } from "./names.jsx";
import Worklist from "./Worklist.jsx";

vi.mock("./components/LatestCasePanel.jsx", () => ({ default: () => <div /> }));

const DEMO = { name: "Meera Nambiar", dob: "1971-04-05", sex: "F", source: "demo-layer" };
// One patient whose record carried a placeholder name, one image wrapped for ingest (it carries no patient),
// one RSNA head CT (no name in the file). The API names the first and leaves the other two out.
const rows = [
  { ...fixture.studies.find((s) => s.modality === "CR"), study: "S-DEMO", patient_id: "AUR-000001", exam: "CR Chest" },
  { ...fixture.studies.find((s) => s.modality === "CR" && s.lane === "URGENT"), study: "S-IMG", patient_id: "AUR-000002", exam: "CR Chest" },
  { ...fixture.studies.find((s) => s.modality === "CT"), study: "S-CT", patient_id: "AUR-000003", exam: "CT" },
];
const mixed = { ...fixture, me: null, scope: "all", studies: rows };

const renderList = (data = mixed) => render(
  <MemoryRouter><NamesProvider token="t"><Worklist load={() => Promise.resolve(data)} token="t" /></NamesProvider></MemoryRouter>);
const rowOf = (study) => screen.getAllByTestId("study-row").find((r) => r.dataset.study === study);

afterEach(() => vi.restoreAllMocks());

describe("patient names on the worklist", () => {
  it("shows a name for the demo patient and only the pseudonym for the image and the RSNA CT", async () => {
    const resolve = vi.spyOn(api, "resolveNames").mockResolvedValue({ available: true, patients: { "AUR-000001": DEMO } });
    renderList();
    await screen.findAllByTestId("study-row");
    await waitFor(() => expect(within(rowOf("S-DEMO")).getByText("Meera Nambiar")).toBeInTheDocument());

    // All three were asked about, in one request.
    expect(resolve).toHaveBeenCalledTimes(1);
    expect(resolve.mock.calls[0][1].sort()).toEqual(["AUR-000001", "AUR-000002", "AUR-000003"]);

    const named = rowOf("S-DEMO");
    expect(within(named).getByText("AUR-000001")).toBeInTheDocument();
    expect(named.querySelector(".patient-name")).toHaveAttribute("title", expect.stringContaining("fictional"));
    for (const study of ["S-IMG", "S-CT"]) {
      const row = rowOf(study);
      expect(row.querySelector(".patient-name")).toBeNull();                        // no name
      const pseudo = row.querySelector(".cell-patient .patient-id");
      expect(pseudo).toHaveTextContent(/^AUR-00000[23]$/);
      // The pseudonym is in the same cell and the same style as a named row's pseudonym.
      expect(pseudo.className).toBe(named.querySelector(".cell-patient .patient-id").className);
      expect(pseudo.closest(".cell-patient")).toBe(row.querySelector(".cell-patient"));
      expect(row.querySelector(".cell-patient").textContent).not.toMatch(/unknown|unavailable|anonymi[sz]ed|n\/a/i);
    }
  });

  it("says, where a name is shown, that names are fictional, and not when none is", async () => {
    vi.spyOn(api, "resolveNames").mockResolvedValue({ available: true, patients: { "AUR-000001": DEMO } });
    const { unmount } = renderList();
    expect(await screen.findByTestId("demo-names-note")).toHaveTextContent("Names are fictional, from the demo layer");
    unmount();
    vi.spyOn(api, "resolveNames").mockResolvedValue({ available: true, patients: {} });
    renderList();
    await screen.findAllByTestId("study-row");
    await waitFor(() => expect(api.resolveNames).toHaveBeenCalled());
    expect(screen.queryByTestId("demo-names-note")).toBeNull();
  });

  it("finds a patient by name in the search, and still by pseudonym", async () => {
    vi.spyOn(api, "resolveNames").mockResolvedValue({ available: true, patients: { "AUR-000001": DEMO } });
    renderList();
    await screen.findByText("Meera Nambiar");
    await userEvent.type(screen.getByPlaceholderText(/search studies/i), "nambiar");
    expect(screen.getAllByTestId("study-row").map((r) => r.dataset.study)).toEqual(["S-DEMO"]);
    await userEvent.clear(screen.getByPlaceholderText(/search studies/i));
    await userEvent.type(screen.getByPlaceholderText(/search studies/i), "AUR-000003");
    expect(screen.getAllByTestId("study-row").map((r) => r.dataset.study)).toEqual(["S-CT"]);
  });

  it("leaves every row as it was when the lookup fails or the runtime has no identity map", async () => {
    vi.spyOn(api, "resolveNames").mockRejectedValue(new Error("down"));
    renderList();
    await screen.findAllByTestId("study-row");
    await waitFor(() => expect(api.resolveNames).toHaveBeenCalled());
    expect(document.querySelector(".patient-name")).toBeNull();
    expect(rowOf("S-DEMO").querySelector(".cell-patient .patient-id")).toHaveTextContent("AUR-000001");
    expect(screen.queryByTestId("demo-names-note")).toBeNull();
  });

  it("does not ask twice about a patient it has already asked about", async () => {
    const resolve = vi.spyOn(api, "resolveNames").mockResolvedValue({ available: true, patients: {} });
    const { rerender } = renderList();
    await waitFor(() => expect(resolve).toHaveBeenCalledTimes(1));
    rerender(<MemoryRouter><NamesProvider token="t"><Worklist load={() => Promise.resolve({ ...mixed })} token="t" /></NamesProvider></MemoryRouter>);
    await new Promise((r) => setTimeout(r, 120));
    expect(resolve).toHaveBeenCalledTimes(1);
  });
});

describe("PatientLabel", () => {
  it("shows sex and date of birth only where the API sent them, and never when there is no name", async () => {
    vi.spyOn(api, "resolveNames").mockResolvedValue({ available: true, patients: {
      "AUR-000001": DEMO, "AUR-000004": { name: "Kabir Joshi", dob: null, sex: null, source: "demo-layer" } } });
    render(<NamesProvider token="t">
      <PatientLabel id="AUR-000001" inline detail /><PatientLabel id="AUR-000004" inline detail />
      <PatientLabel id="AUR-000005" inline detail /></NamesProvider>);
    await screen.findByText("Meera Nambiar");
    expect(screen.getByText("F, born 1971-04-05")).toBeInTheDocument();
    expect(screen.getByText("Kabir Joshi")).toBeInTheDocument();
    expect(document.querySelectorAll(".patient-demo")).toHaveLength(1);
    expect(screen.getByText("AUR-000005").className).toContain("patient-id");
    expect(document.body.textContent).not.toMatch(/unknown|unavailable/i);
  });

  it("shows the pseudonym alone with no provider at all, as before", () => {
    render(<PatientLabel id="AUR-000009" fallback="S9" />);
    expect(screen.getByText("AUR-000009")).toBeInTheDocument();
  });
});
