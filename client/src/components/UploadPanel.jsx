import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { UploadIcon } from "./Icons.jsx";
import { Overlay } from "./ui.jsx";
import { PatientLabel } from "../names.jsx";
import { laneName } from "../worklist.js";

const POLL_MS = 2000;
const PARALLEL = 4;
const STATUS = { queued: "Queued", receiving: "Preparing", running: "In the pipeline", done: "On your worklist", failed: "Failed" };

const megabytes = (bytes) => (bytes / 2 ** 20 >= 10 ? Math.round(bytes / 2 ** 20) : (bytes / 2 ** 20).toFixed(1));

// What is wrong with the chosen files before any is sent, from the limits the API states.
export function fileProblems(files, limits) {
  if (!limits) return [];
  const out = [];
  const total = files.reduce((n, f) => n + f.size, 0);
  if (files.length > limits.files) out.push(`${files.length} files; at most ${limits.files} in one upload.`);
  const big = files.filter((f) => f.size > limits.file_mb * 2 ** 20).length;
  if (big) out.push(`${big} ${big === 1 ? "file is" : "files are"} over ${limits.file_mb} MB.`);
  if (total > limits.total_mb * 2 ** 20) out.push(`${megabytes(total)} MB in all; at most ${limits.total_mb} MB in one upload.`);
  return out;
}

// Upload your own studies: choose DICOM files (a study's folder) or chest X-ray images, send them, and
// watch each study go through the pipeline onto your worklist. The API sorts the files into studies; the
// pipeline removes identifiers before anything is stored. A file's name is never sent.
export default function UploadPanel({ token, onClose, onProgress }) {
  const [info, setInfo] = useState(null);
  const [files, setFiles] = useState([]);
  const [phase, setPhase] = useState("choose");          // "choose" | "sending" | "processing"
  const [sent, setSent] = useState(0);
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [over, setOver] = useState(false);
  const fileInput = useRef(null);
  const folderInput = useRef(null);
  const openUpload = useRef(null);                       // the upload id while files are being sent
  const cancelled = useRef(false);
  const finished = useRef(0);

  useEffect(() => {
    api.uploadInfo(token).then(setInfo).catch((e) => setError(e.message));
  }, [token]);

  // Poll the upload; reload the worklist whenever another study finishes.
  useEffect(() => {
    if (phase !== "processing" || !status?.running) return undefined;
    const t = setInterval(async () => {
      try {
        const s = await api.uploadStatus(token, status.upload);
        setStatus(s);
        const done = s.items.filter((i) => i.status === "done" || i.status === "failed").length;
        if (done !== finished.current) {
          finished.current = done;
          if (onProgress) onProgress();
        }
      } catch (e) {
        setError(e.message);
      }
    }, POLL_MS);
    return () => clearInterval(t);
  }, [token, phase, status, onProgress]);

  const limits = info?.limits;
  const problems = fileProblems(files, limits);
  const total = files.reduce((n, f) => n + f.size, 0);
  const canSend = Boolean(info?.available) && phase === "choose" && files.length > 0 && problems.length === 0;

  const add = (list) => {
    const added = Array.from(list || []).filter((f) => f.size > 0);       // a dropped folder arrives empty
    if (added.length) setFiles((f) => [...f, ...added]);
    setError(null);
  };

  async function discardOpen() {
    const id = openUpload.current;
    openUpload.current = null;
    if (id) await api.discardUpload(token, id).catch(() => {});
  }

  async function send() {
    setError(null);
    cancelled.current = false;
    finished.current = 0;
    setSent(0);
    setPhase("sending");
    try {
      const { upload } = await api.openUpload(token);
      openUpload.current = upload;
      let next = 0;
      let count = 0;
      const worker = async () => {
        while (!cancelled.current && next < files.length) {
          const n = next++;
          await api.sendUploadFile(token, upload, n, files[n]);
          count += 1;
          setSent(count);
        }
      };
      await Promise.all(Array.from({ length: Math.min(PARALLEL, files.length) }, worker));
      if (cancelled.current) return;
      const state = await api.submitUpload(token, upload);
      openUpload.current = null;                       // submitted: the API owns it now
      setStatus(state);
      setPhase("processing");
    } catch (e) {
      // Nothing half-sent is left on the API: the upload is dropped and the files stay chosen.
      cancelled.current = true;
      await discardOpen();
      setError(e.message);
      setPhase("choose");
    }
  }

  function close() {
    cancelled.current = true;
    discardOpen();
    onClose();
  }

  const items = status?.items || [];
  const reads = (info?.pools || []).join(" and ");

  return (
    <Overlay onClose={close}>
      <div className="modal-card wide-modal" role="dialog" aria-modal="true" aria-label="Upload study" data-testid="upload-panel">
        <div className="modal-header">
          <div>
            <h2 className="modal-title">Upload study</h2>
            <div className="crumbs">Worklist <span aria-hidden="true">›</span> <strong>Upload study</strong></div>
          </div>
          <div className="modal-actions">
            {phase === "processing" ? (
              <button type="button" className="pill pill-primary" onClick={close}>{status?.running ? "Close, keep running" : "Close"}</button>
            ) : (
              <>
                <button type="button" className="pill pill-quiet" onClick={close}>Cancel</button>
                <button type="button" className="pill pill-primary" disabled={!canSend} onClick={send} data-testid="upload-send">
                  {canSend ? `Upload ${files.length} ${files.length === 1 ? "file" : "files"}` : "Upload"}
                </button>
              </>
            )}
          </div>
        </div>

        {error && <p className="error" role="alert" data-testid="upload-error">{error}</p>}
        {!info && !error && <p className="note">Checking the upload service.</p>}
        {info && !info.available && (
          <p className="note" data-testid="upload-unavailable">
            <strong>Upload is unavailable in this environment.</strong>{" "}
            {info.reason.charAt(0).toUpperCase() + info.reason.slice(1)}{/[.!?]$/.test(info.reason) ? "" : "."}
          </p>
        )}

        {info?.available && phase !== "processing" && (
          <>
            <div className={`upload-drop${over ? " over" : ""}`} data-testid="upload-drop"
                 onDragOver={(e) => { e.preventDefault(); setOver(true); }}
                 onDragLeave={() => setOver(false)}
                 onDrop={(e) => { e.preventDefault(); setOver(false); if (phase === "choose") add(e.dataTransfer.files); }}>
              <UploadIcon size={22} />
              <strong>{files.length ? `${files.length} ${files.length === 1 ? "file" : "files"}, ${megabytes(total)} MB chosen` : "Drop files here"}</strong>
              <div className="drop-actions">
                <button type="button" className="pill" disabled={phase !== "choose"} onClick={() => fileInput.current?.click()}>Choose files</button>
                <button type="button" className="pill" disabled={phase !== "choose"} onClick={() => folderInput.current?.click()}>Choose a folder</button>
                {files.length > 0 && phase === "choose" && (
                  <button type="button" className="pill pill-quiet" onClick={() => setFiles([])}>Clear</button>
                )}
              </div>
              <input ref={fileInput} type="file" multiple aria-label="Choose files" data-testid="upload-files"
                     onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
              <input ref={folderInput} type="file" multiple webkitdirectory="" aria-label="Choose a folder" data-testid="upload-folder"
                     onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
            </div>

            {problems.map((p) => <p key={p} className="error" role="alert">{p}</p>)}

            {phase === "sending" && (
              <div data-testid="upload-sending">
                <p className="meta">Sending files: {sent} of {files.length}</p>
                <div className="upload-bar" role="progressbar" aria-label="Files sent" aria-valuemin={0}
                     aria-valuemax={files.length} aria-valuenow={sent}>
                  <span style={{ width: `${files.length ? (100 * sent) / files.length : 0}%` }} />
                </div>
              </div>
            )}

            <ul className="upload-accepts">
              {(info.accepts || []).map((a) => <li key={a}>{a}</li>)}
              <li>Each study goes on your worklist{reads ? ` (you read ${reads})` : ""}, in the pool its modality belongs to: chest X-ray in Chest, brain MR and head CT in Neuro.</li>
            </ul>
            <p className="note" data-testid="upload-privacy">
              Upload public, synthetic or openly licensed studies only. Identifiers in the DICOM header are removed, and text
              burned into the pixels is masked by OCR, before anything is stored or indexed. The masking catches most text and
              not all of it. The API keeps the files only until they are handed to the pipeline, then deletes them.
              At most {limits.files} files, {limits.file_mb} MB each and {limits.total_mb} MB in all.
            </p>
          </>
        )}

        {phase === "processing" && status && (
          <div data-testid="upload-progress">
            <p className="meta">
              {items.length} {items.length === 1 ? "study" : "studies"} · {status.running ? "running" : "finished"}
              {status.skipped > 0 && ` · ${status.skipped} ${status.skipped === 1 ? "file was" : "files were"} not a study image and skipped`}
            </p>
            <div className="table-scroll">
            <table className="simulate-counts">
              <thead><tr><th>Study</th><th>Type</th><th>Files</th><th>Status</th><th>Lane</th></tr></thead>
              <tbody>
                {items.map((i) => (
                  <tr key={i.n}>
                    <td>{i.patient_id ? <PatientLabel id={i.patient_id} /> : `Study ${i.n}`}</td>
                    <td>{i.label}</td>
                    <td>{i.files}</td>
                    <td>{STATUS[i.status] || i.status}{i.error ? `: ${i.error}` : ""}</td>
                    <td>{i.lane ? <span className={`lanetag lane-${i.lane}`}>{laneName(i.lane)}</span> : "--"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          </div>
        )}
      </div>
    </Overlay>
  );
}
