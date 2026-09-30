import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { api } from "./api.js";
import fixture from "./test/worklist.api.json";
import AbstentionTray from "./components/AbstentionTray.jsx";
import ReportsView from "./components/ReportsView.jsx";
import { activeFinding, gradcamLayer } from "./components/GradcamFindings.jsx";
import { DraftPanel } from "./Study.jsx";
import Worklist from "./Worklist.jsx";

vi.mock("./components/LatestCasePanel.jsx", () => ({
  default: ({ studyId }) => <div data-testid="case-stub">{studyId}</div>,
}));

describe("the panel on the right", () => {
  it("exists only while a study is selected, and Esc or the close button hides it", async () => {
    render(<MemoryRouter><Worklist load={() => Promise.resolve(fixture)} /></MemoryRouter>);
    if (fixture.me) await userEvent.click(await screen.findByTestId("scope-department"));
    const rows = await screen.findAllByTestId("study-row");
    expect(screen.queryByTestId("workstation-details-panel")).toBeNull();     // no default selection
    expect(screen.queryByText("Placeholder")).toBeNull();
    await userEvent.click(rows[0]);
    expect(screen.getByTestId("workstation-details-panel")).toBeInTheDocument();
    expect(screen.getByTestId("case-stub")).toHaveTextContent(rows[0].dataset.study);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByTestId("workstation-details-panel")).toBeNull();
    await userEvent.click(rows[1]);
    await userEvent.click(screen.getByTestId("close-panel"));
    expect(screen.queryByTestId("workstation-details-panel")).toBeNull();
  });
});

const abstained = {
  study: { study: "S9", lane: "ABSTAIN", pool: "Chest", driver: "Nodule", abstain_reason: "Nodule has a signal of 0.50" },
  findings: [{ name: "Nodule", label: "Nodule", signal: 0.5, urgency: 0.5 }],
  abstain_band: [0.35, 0.6],
};

describe("the abstention tray", () => {
  it("says why first, then places a study in a lane only with a reason", async () => {
    const setLane = vi.spyOn(api, "setLane").mockResolvedValue({ study: { study: "S9", lane: "URGENT" } });
    const onChanged = vi.fn();
    render(<AbstentionTray detail={abstained} token="t" me="me" onChanged={onChanged} />);
    expect(screen.getByTestId("abstain-why")).toHaveTextContent("signal 0.50 against the 0.35 to 0.60 band");
    await userEvent.click(screen.getByTestId("tray-lane"));
    const confirm = screen.getByTestId("tray-lane-confirm");
    expect(confirm).toBeDisabled();                                            // a reason is required
    await userEvent.click(screen.getByRole("radio", { name: "Urgent" }));
    await userEvent.type(screen.getByTestId("tray-reason"), "spiculated margin");
    await userEvent.click(confirm);
    expect(setLane).toHaveBeenCalledWith("t", "S9", "URGENT", "spiculated margin");
    expect(onChanged).toHaveBeenCalledWith({ study: "S9", lane: "URGENT" });
  });

  it("is not there for a study the system placed", () => {
    render(<AbstentionTray detail={{ ...abstained, study: { ...abstained.study, lane: "URGENT" } }} token="t" />);
    expect(screen.queryByTestId("abstention-tray")).toBeNull();
  });
});

describe("chest Grad-CAM per finding", () => {
  const ev = {
    gradcam_box: [0, 0, 512], gradcam_finding: "Pneumonia",
    gradcam_findings: [
      { name: "Pneumonia", slug: "pneumonia", driver: true, signal: 0.7, weighted: 0.5, layer_url: "/l/pneumonia.png" },
      { name: "Mass", slug: "mass", driver: false, signal: 0.4, weighted: 0.2, layer_url: "/l/mass.png" },
    ],
  };
  it("shows the driver's layer by default and the chosen finding's when asked", () => {
    expect(activeFinding(ev, null).name).toBe("Pneumonia");
    expect(gradcamLayer(ev, {}, null).url).toBe("/l/pneumonia.png");
    expect(gradcamLayer(ev, {}, "Mass").url).toBe("/l/mass.png");
    expect(gradcamLayer({ ...ev, gradcam_findings: undefined }, { gradcam_layer_png: "/old.png" }, null).url).toBe("/old.png");
  });
});

describe("Reports", () => {
  it("lists the reader's saved reports, filters by status and opens one to read", async () => {
    const all = [
      { study: "A", version: "000002", status: "reviewed", text: "Reviewed text", exam: "CR Chest", patient_id: "P1", lane: "URGENT", at: "2026-09-29T10:00:00+00:00", author: "me" },
      { study: "B", version: "000001", status: "draft", text: "Draft text", exam: "MR Brain", patient_id: "P2", lane: "CRITICAL", at: "2026-09-29T09:00:00+00:00", author: "me" },
    ];
    const spy = vi.spyOn(api, "reports").mockImplementation(async (_t, status) => ({
      reports: status ? all.filter((r) => r.status === status) : all, counts: { reviewed: 1, draft: 1 } }));
    render(<ReportsView token="t" studies={[]} me="me" />);
    expect(await screen.findAllByTestId("report-row")).toHaveLength(2);
    await userEvent.click(screen.getByTestId("reports-draft"));
    expect(spy).toHaveBeenLastCalledWith("t", "draft");
    const rows = await screen.findAllByTestId("report-row");
    expect(rows).toHaveLength(1);
    await userEvent.click(rows[0]);
    expect(within(screen.getByTestId("report-reader")).getByTestId("report-text")).toHaveTextContent("Draft text");
  });
});

describe("the draft panel", () => {
  const detail = { study: { study: "S", driver_label: "Nodule", lane: "URGENT", lane_label: "URGENT" }, draft: "GENERATED DRAFT" };
  it("regenerates the draft, asking first when the box holds edits", async () => {
    render(<DraftPanel detail={detail} saveDraft={vi.fn()} />);
    const box = screen.getByTestId("draft-text");
    await userEvent.type(box, " my edit");
    await userEvent.click(screen.getByTestId("draft-regenerate"));
    expect(screen.getByRole("alert")).toHaveTextContent("Replace your edits");
    expect(box.value).toBe("GENERATED DRAFT my edit");                       // nothing lost yet
    await userEvent.click(screen.getByRole("button", { name: "Replace" }));
    expect(box.value).toBe("GENERATED DRAFT");
  });

  it("marks reviewed and confirms where the report went", async () => {
    const save = vi.fn().mockResolvedValue({ report: { version: "000003", status: "reviewed", by: "r1", author: "r1", at: "t" } });
    render(<DraftPanel detail={detail} saveDraft={save} />);
    await userEvent.click(screen.getByTestId("draft-reviewed"));
    expect(save).toHaveBeenCalledWith("S", "GENERATED DRAFT", true);
    expect(await screen.findByTestId("toast")).toHaveTextContent("Saved to Reports");
    expect(screen.getByTestId("draft-status")).toHaveTextContent("Reviewed by r1");
  });
});
