import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { api } from "./api.js";
import Worklist from "./Worklist.jsx";
import worklist from "./test/worklist.api.json";
import OpinionsView from "./components/OpinionsView.jsx";
import SecondOpinionBar from "./components/SecondOpinionBar.jsx";
import AbstentionTray from "./components/AbstentionTray.jsx";
import { DraftPanel } from "./components/DraftPanel.jsx";
import { Overlay } from "./components/ui.jsx";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const R1 = "r1@x", R2 = "r2@x", R3 = "r3@x", ME = "me@x";
const study = (o = {}) => ({ study: "S1", patient_id: "P-1", lane: "URGENT", lane_label: "URGENT", pool: "Chest", exam: "CR Chest",
                             modality: "CR", driver_label: "Edema", acuity: 61.2, ...o });
const opinion = (to, status, extra = {}) => ({ to, to_name: `Reader ${to[1]}`, requested_by: ME, requested_by_name: "Dr Me",
                                              at: "2026-09-25T08:15:00+00:00", note: "", opened_at: null, status, ...extra });

describe("the Second opinions tab", () => {
  const data = {
    received: [
      { study: study({ study: "S1" }), opinion: opinion(ME, "waiting", { requested_by: R1, requested_by_name: "Reader 1", note: "Is this edema?" }) },
      { study: study({ study: "S2", pool: "Neuro", exam: "MR Brain", modality: "MR" }), opinion: opinion(ME, "reported", { requested_by: R2, requested_by_name: "Reader 2" }) },
    ],
    sent: [{ study: study({ study: "S3" }), opinions: [opinion(R2, "reported"), opinion(R3, "waiting")] }],
  };

  it("lists what was asked of you by reading pool, with who asked, where it stands and the note", async () => {
    vi.spyOn(api, "secondOpinions").mockResolvedValue(data);
    render(<OpinionsView token="t" onOpen={() => {}} />);
    const rows = await screen.findAllByTestId("opinion-row");
    expect(rows).toHaveLength(2);
    // Chest and Neuro stay in their own pools.
    expect(within(screen.getByTestId("opinion-pool-Chest")).getAllByTestId("opinion-row")).toHaveLength(1);
    expect(within(screen.getByTestId("opinion-pool-Neuro")).getAllByTestId("opinion-row")).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("From Reader 1");
    expect(rows[0]).toHaveTextContent("Waiting");
    expect(rows[0]).toHaveTextContent("Is this edema?");
    expect(within(screen.getByTestId("opinion-pool-Neuro")).getByTestId("opinion-status")).toHaveTextContent("Reported");
    expect(screen.getByTestId("opinion-tab-received")).toHaveTextContent("Received (2)");
  });

  it("opens the study when a row is chosen", async () => {
    vi.spyOn(api, "secondOpinions").mockResolvedValue(data);
    const onOpen = vi.fn();
    render(<OpinionsView token="t" onOpen={onOpen} />);
    await userEvent.click((await screen.findAllByTestId("opinion-row"))[0]);
    expect(onOpen).toHaveBeenCalledWith("S1");
  });

  it("shows what you asked of others, and how many have reported", async () => {
    vi.spyOn(api, "secondOpinions").mockResolvedValue(data);
    render(<OpinionsView token="t" onOpen={() => {}} />);
    await userEvent.click(await screen.findByTestId("opinion-tab-sent"));
    const row = screen.getByTestId("opinion-row");
    expect(row).toHaveTextContent("1 of 2 reported");
    expect(row).toHaveTextContent("Asked Reader 2, Reader 3");
  });

  it("says so when nothing was asked of you", async () => {
    vi.spyOn(api, "secondOpinions").mockResolvedValue({ received: [], sent: [] });
    render(<OpinionsView token="t" onOpen={() => {}} />);
    expect(await screen.findByTestId("opinions-empty")).toHaveTextContent("No radiologist has asked you");
  });

  it("is a tab in the bar, with the number of requests nobody has opened yet", async () => {
    vi.spyOn(api, "secondOpinions").mockResolvedValue({ received: [], sent: [] });
    render(<MemoryRouter><Worklist load={() => Promise.resolve({ ...worklist, opinions_waiting: 2 })} /></MemoryRouter>);
    const tab = await screen.findByTestId("nav-opinions");
    expect(tab).toHaveTextContent("Second opinions");
    expect(tab).toHaveTextContent("2");
    await userEvent.click(tab);
    expect(await screen.findByTestId("opinions-view")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Second opinions");
  });
});

describe("second opinions on a study", () => {
  const base = { study: study(), opinions: [], my_opinion: null, can_request_opinion: true };

  it("says who it was sent to and how far each has got", () => {
    const detail = { ...base, opinions: [opinion(R1, "reported"), opinion(R2, "opened"), opinion(R3, "waiting")] };
    render(<SecondOpinionBar detail={detail} token="t" me={ME} onChanged={() => {}} />);
    expect(screen.getByTestId("opinion-count")).toHaveTextContent("Sent to 3 radiologists");
    expect(screen.getAllByTestId("opinion-person").map((p) => p.textContent)).toEqual(["Reader 1Reported", "Reader 2Opened", "Reader 3Waiting"]);
    expect(screen.getByTestId("ask-opinion")).toHaveTextContent("Send to another radiologist");
  });

  it("tells the one who was asked who asked and why, and gives them no button to ask on", () => {
    const mine = opinion(ME, "waiting", { requested_by: R1, requested_by_name: "Reader 1", note: "Please look at the left base" });
    const detail = { ...base, can_request_opinion: false, opinions: [mine, opinion(R2, "waiting")], my_opinion: mine };
    render(<SecondOpinionBar detail={detail} token="t" me={ME} onChanged={() => {}} />);
    expect(screen.getByTestId("opinion-from")).toHaveTextContent("requested by Reader 1");
    expect(screen.getByTestId("opinion-from")).toHaveTextContent("Please look at the left base");
    expect(screen.getAllByTestId("opinion-person")[0]).toHaveTextContent("You");
    expect(screen.queryByTestId("ask-opinion")).toBeNull();
  });

  it("shows nothing at all when there is nothing to say and nothing to ask", () => {
    const { container } = render(<SecondOpinionBar detail={{ ...base, can_request_opinion: false }} token="t" me={ME} onChanged={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("offers only radiologists who read the pool and have not been asked, and sends the chosen with the note", async () => {
    vi.spyOn(api, "readers").mockResolvedValue({ readers: [
      { id: ME, name: "Me", pools: ["Chest"] }, { id: R1, name: "Reader 1", pools: ["Chest", "Neuro"] },
      { id: R2, name: "Reader 2", pools: ["Neuro"] }, { id: R3, name: "Reader 3", pools: ["Chest"] }], pools: ["Chest", "Neuro"] });
    const send = vi.spyOn(api, "requestOpinions").mockResolvedValue({});
    const onChanged = vi.fn();
    const detail = { ...base, opinions: [opinion(R3, "waiting")] };          // R3 already asked
    render(<SecondOpinionBar detail={detail} token="t" me={ME} onChanged={onChanged} />);
    await userEvent.click(screen.getByTestId("ask-opinion"));
    const list = await screen.findByTestId("opinion-readers");
    expect(within(list).getAllByRole("checkbox")).toHaveLength(1);           // only Reader 1
    expect(screen.getByTestId("opinion-send")).toBeDisabled();
    await userEvent.click(within(list).getByLabelText(/Reader 1/));
    await userEvent.type(screen.getByTestId("opinion-note"), " Consolidation? ");
    await userEvent.click(screen.getByTestId("opinion-send"));
    expect(send).toHaveBeenCalledWith("t", "S1", [R1], "Consolidation?");
    expect(onChanged).toHaveBeenCalled();
    expect(screen.queryByTestId("ask-opinion-dialog")).toBeNull();
  });

  it("says why when the API refuses", async () => {
    vi.spyOn(api, "readers").mockResolvedValue({ readers: [{ id: R1, name: "Reader 1", pools: ["Chest"] }], pools: ["Chest"] });
    vi.spyOn(api, "requestOpinions").mockRejectedValue(new Error("Reader 1 has already been asked"));
    render(<SecondOpinionBar detail={base} token="t" me={ME} onChanged={() => {}} />);
    await userEvent.click(screen.getByTestId("ask-opinion"));
    await userEvent.click(await screen.findByLabelText(/Reader 1/));
    await userEvent.click(screen.getByTestId("opinion-send"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Reader 1 has already been asked");
  });
});

describe("getting a second opinion from any study", () => {
  const readers = { readers: [{ id: R1, name: "Reader 1", pools: ["Chest"] }], pools: ["Chest"] };

  it("is offered on a study in every lane, and says it stays on your worklist", async () => {
    vi.spyOn(api, "readers").mockResolvedValue(readers);
    for (const lane of ["CRITICAL", "URGENT", "ABSTAIN", "EXPEDITED", "ROUTINE", "FAILED", "REPEAT"]) {
      const view = render(<SecondOpinionBar detail={{ study: study({ lane }), opinions: [], my_opinion: null, can_request_opinion: true }}
                                            token="t" me={ME} onChanged={() => {}} />);
      expect(screen.getByTestId("ask-opinion")).toHaveTextContent("Get a second opinion");
      view.unmount();
    }
    render(<SecondOpinionBar detail={{ study: study(), opinions: [], my_opinion: null, can_request_opinion: true }} token="t" me={ME} onChanged={() => {}} />);
    await userEvent.click(screen.getByTestId("ask-opinion"));
    expect(await screen.findByRole("dialog", { name: "Get a second opinion" })).toHaveTextContent("It stays on your worklist.");
    expect(screen.getByLabelText("Message (optional)")).toBeInTheDocument();
  });

  it("is what the abstention tray's option opens, and it does not hand the study over", async () => {
    vi.spyOn(api, "readers").mockResolvedValue(readers);
    const send = vi.spyOn(api, "requestOpinions").mockResolvedValue({});
    const detail = { study: study({ lane: "ABSTAIN", driver: "edema" }), findings: [], opinions: [], my_opinion: null, can_request_opinion: true };
    render(<><SecondOpinionBar detail={detail} token="t" me={ME} onChanged={() => {}} /><AbstentionTray detail={detail} token="t" onChanged={() => {}} /></>);
    await userEvent.click(screen.getByTestId("tray-second"));
    expect(screen.getByTestId("tray-second")).toHaveTextContent("Get a second opinion");
    await userEvent.click(await screen.findByLabelText(/Reader 1/));
    await userEvent.type(screen.getByTestId("opinion-note"), "Please place this one");
    await userEvent.click(screen.getByTestId("opinion-send"));
    expect(send).toHaveBeenCalledWith("t", "S1", [R1], "Please place this one");
    // The old hand-over form is gone.
    expect(screen.queryByTestId("tray-reader")).toBeNull();
    expect(screen.queryByTestId("tray-second-confirm")).toBeNull();
  });
});

describe("the report dropdown", () => {
  const report = (author, name, status, text) => ({ study: "S1", version: "00000x", author, author_name: name, status, text, at: "2026-09-25T09:00:00+00:00", mine: author === ME });
  const detail = (extra) => ({ study: study(), draft: "TEMPLATE DRAFT", report: null, draft_review: null, reports: [], opinions: [], my_opinion: null, ...extra });

  it("is not there on a study nobody else has reported on", () => {
    render(<DraftPanel detail={detail()} saveDraft={vi.fn()} />);
    expect(screen.queryByTestId("report-picker")).toBeNull();
  });

  it("lists your report first, then the others, and those asked who have not written one", () => {
    const d = detail({ reports: [report(ME, "Me", "draft", "mine"), report(R1, "Reader 1", "reviewed", "theirs")],
                       opinions: [opinion(R1, "reported"), opinion(R2, "waiting")] });
    render(<DraftPanel detail={d} saveDraft={vi.fn()} />);
    const options = within(screen.getByTestId("report-picker")).getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual(["Your report", "Reader 1, reviewed", "Reader 2, no report yet"]);
    expect(options[2]).toBeDisabled();
  });

  it("shows another radiologist's report read only, with who wrote it, and takes you back to your own", async () => {
    const d = detail({ report: report(ME, "Me", "draft", "MY OWN TEXT"),
                       reports: [report(ME, "Me", "draft", "MY OWN TEXT"), report(R1, "Reader 1", "reviewed", "READER ONE WROTE THIS")] });
    render(<DraftPanel detail={d} saveDraft={vi.fn()} />);
    expect(screen.getByTestId("draft-text")).toHaveValue("MY OWN TEXT");
    await userEvent.selectOptions(screen.getByTestId("report-picker"), R1);
    const box = screen.getByTestId("report-readonly");
    expect(box).toHaveValue("READER ONE WROTE THIS");
    expect(box).toHaveAttribute("readonly");
    expect(screen.getByTestId("report-status")).toHaveTextContent("Reviewed by Reader 1");
    expect(screen.queryByTestId("draft-reviewed")).toBeNull();               // nothing here to sign
    expect(screen.queryByTestId("draft-text")).toBeNull();
    await userEvent.selectOptions(screen.getByTestId("report-picker"), "mine");
    expect(screen.getByTestId("draft-text")).toHaveValue("MY OWN TEXT");
    expect(screen.getByTestId("draft-reviewed")).toBeInTheDocument();
  });
});

describe("stacked overlays", () => {
  it("Escape closes only the one on top", async () => {
    const below = vi.fn(), top = vi.fn();
    render(<><Overlay onClose={below}><p>sheet</p></Overlay><Overlay onClose={top}><p>dialog</p></Overlay></>);
    await userEvent.keyboard("{Escape}");
    expect(top).toHaveBeenCalledTimes(1);
    expect(below).not.toHaveBeenCalled();
  });
});
