import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "./api.js";
import UploadPanel, { fileProblems } from "./components/UploadPanel.jsx";

const LIMITS = { files: 1000, file_mb: 64, total_mb: 400, studies: 20 };
const INFO = {
  available: true, runtime: "local", limits: LIMITS, pools: ["Chest", "Neuro"],
  accepts: ["DICOM files of one or more studies", "PNG or JPEG chest X-ray images"],
};
const file = (name, size = 10) => new File([new Uint8Array(size).fill(1)], name, { type: "image/png" });

afterEach(() => vi.restoreAllMocks());

describe("fileProblems", () => {
  it("names each limit the chosen files break, and nothing when they are within them", () => {
    expect(fileProblems([{ size: 5 }], LIMITS)).toEqual([]);
    expect(fileProblems([{ size: 65 * 2 ** 20 }], LIMITS)).toEqual(["1 file is over 64 MB."]);
    expect(fileProblems(Array.from({ length: 1001 }, () => ({ size: 1 })), LIMITS))
      .toEqual(["1001 files; at most 1000 in one upload."]);
    expect(fileProblems(Array.from({ length: 7 }, () => ({ size: 60 * 2 ** 20 })), LIMITS))
      .toEqual(["420 MB in all; at most 400 MB in one upload."]);
    expect(fileProblems([{ size: 1 }], undefined)).toEqual([]);
  });
});

describe("the upload panel", () => {
  it("says why when uploading is unavailable, and offers nothing to choose", async () => {
    vi.spyOn(api, "uploadInfo").mockResolvedValue({ available: false, reason: "this preview has no pipeline", runtime: "fixture" });
    render(<UploadPanel token="t" onClose={() => {}} />);
    expect(await screen.findByTestId("upload-unavailable")).toHaveTextContent("This preview has no pipeline.");
    expect(screen.queryByTestId("upload-drop")).toBeNull();
    expect(screen.getByTestId("upload-send")).toBeDisabled();
  });

  it("states what is accepted, where a study goes and what happens to identifiers", async () => {
    vi.spyOn(api, "uploadInfo").mockResolvedValue(INFO);
    render(<UploadPanel token="t" onClose={() => {}} />);
    expect(await screen.findByText("PNG or JPEG chest X-ray images")).toBeInTheDocument();
    expect(screen.getByText(/you read Chest and Neuro/)).toBeInTheDocument();
    expect(screen.getByTestId("upload-privacy")).toHaveTextContent(/public, synthetic or openly licensed/);
    expect(screen.getByTestId("upload-privacy")).toHaveTextContent(/not all of it/);
  });

  it("sends each file as its own request by number, then submits, and shows each study's status", async () => {
    vi.spyOn(api, "uploadInfo").mockResolvedValue(INFO);
    vi.spyOn(api, "openUpload").mockResolvedValue({ upload: "u1" });
    const send = vi.spyOn(api, "sendUploadFile").mockResolvedValue({});
    const submit = vi.spyOn(api, "submitUpload").mockResolvedValue({
      upload: "u1", running: false, skipped: 1,
      items: [{ n: 1, type: "chest", label: "Chest X-ray", files: 2, status: "done", lane: "URGENT", patient_id: "PSEUDO-7", error: null }],
    });
    const onProgress = vi.fn();
    render(<UploadPanel token="t" onClose={() => {}} onProgress={onProgress} />);
    await screen.findByTestId("upload-drop");
    await userEvent.upload(screen.getByTestId("upload-files"), [file("a.dcm"), file("b.dcm")]);
    expect(screen.getByText("2 files, 0.0 MB chosen")).toBeInTheDocument();
    await userEvent.click(screen.getByTestId("upload-send"));

    const table = await screen.findByTestId("upload-progress");
    expect(send.mock.calls.map((c) => [c[1], c[2]]).sort()).toEqual([["u1", 0], ["u1", 1]]);
    expect(send.mock.calls.every((c) => c[3] instanceof Blob)).toBe(true);
    expect(submit).toHaveBeenCalledWith("t", "u1");
    expect(table).toHaveTextContent("PSEUDO-7");
    expect(table).toHaveTextContent("On your worklist");
    expect(table).toHaveTextContent("1 file was not a study image and skipped");
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
  });

  it("drops the upload and keeps the files when the API refuses them, with its reason", async () => {
    vi.spyOn(api, "uploadInfo").mockResolvedValue(INFO);
    vi.spyOn(api, "openUpload").mockResolvedValue({ upload: "u2" });
    vi.spyOn(api, "sendUploadFile").mockResolvedValue({});
    vi.spyOn(api, "submitUpload").mockRejectedValue(new Error("a study has modality DX; models are registered for CR, CT, MR"));
    const discard = vi.spyOn(api, "discardUpload").mockResolvedValue({});
    render(<UploadPanel token="t" onClose={() => {}} />);
    await screen.findByTestId("upload-drop");
    await userEvent.upload(screen.getByTestId("upload-files"), [file("a.dcm")]);
    await userEvent.click(screen.getByTestId("upload-send"));
    expect(await screen.findByTestId("upload-error")).toHaveTextContent("modality DX");
    expect(discard).toHaveBeenCalledWith("t", "u2");
    expect(screen.getByText("1 file, 0.0 MB chosen")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("upload-send")).toBeEnabled());
  });

  it("does not offer to upload files past a limit, and says which", async () => {
    vi.spyOn(api, "uploadInfo").mockResolvedValue({ ...INFO, limits: { ...LIMITS, file_mb: 0.000001 } });
    render(<UploadPanel token="t" onClose={() => {}} />);
    await screen.findByTestId("upload-drop");
    await userEvent.upload(screen.getByTestId("upload-files"), [file("a.dcm", 100)]);
    expect(screen.getByRole("alert")).toHaveTextContent("1 file is over");
    expect(screen.getByTestId("upload-send")).toBeDisabled();
  });

  it("closing before anything is submitted discards the open upload", async () => {
    vi.spyOn(api, "uploadInfo").mockResolvedValue(INFO);
    vi.spyOn(api, "openUpload").mockResolvedValue({ upload: "u3" });
    let release;
    vi.spyOn(api, "sendUploadFile").mockImplementation(() => new Promise((r) => { release = r; }));
    const discard = vi.spyOn(api, "discardUpload").mockResolvedValue({});
    const onClose = vi.fn();
    render(<UploadPanel token="t" onClose={onClose} />);
    await screen.findByTestId("upload-drop");
    await userEvent.upload(screen.getByTestId("upload-files"), [file("a.dcm")]);
    await userEvent.click(screen.getByTestId("upload-send"));
    await screen.findByTestId("upload-sending");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalled();
    expect(discard).toHaveBeenCalledWith("t", "u3");
    release({});
  });
});
