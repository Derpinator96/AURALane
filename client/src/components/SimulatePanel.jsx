import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api.js";

const POLL_MS = 2000;
const STATUS = { queued: "Queued", receiving: "Receiving", running: "In the pipeline", done: "On the worklist", failed: "Failed" };

// Readers chosen for a batch or a deal. Says, before anything is sent, which
// pool no chosen reader covers.
export function ReaderPicker({ readers, chosen, setChosen, pools = [] }) {
  const covered = new Set(readers.filter((r) => chosen.includes(r.id)).flatMap((r) => r.pools));
  const gaps = chosen.length ? pools.filter((p) => !covered.has(p)) : [];
  const toggle = (id) => setChosen((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id]));
  return (
    <fieldset className="reader-picker" data-testid="reader-picker">
      <legend>Readers ({chosen.length} of {readers.length})</legend>
      {readers.length === 0 && <p className="note">No radiologist accounts found.</p>}
      {readers.map((r) => (
        <label key={r.id} className="reader-option">
          <input type="checkbox" checked={chosen.includes(r.id)} onChange={() => toggle(r.id)} />
          <span>{r.name}</span> <span className="note">{r.pools.join(", ")}</span>
        </label>
      ))}
      {gaps.length > 0 && (
        <p className="error" role="alert" data-testid="pool-gap">
          No chosen reader reads the {gaps.join(" or ")} pool. Add one, or those studies cannot be sent.
        </p>
      )}
    </fieldset>
  );
}

export default function SimulatePanel({ token, readers, onClose, onProgress }) {
  const [info, setInfo] = useState(null);
  const [counts, setCounts] = useState({ chest: 3, brain: 1, ct: 1 });
  const [chosen, setChosen] = useState(() => readers.map((r) => r.id));
  const [estimate, setEstimate] = useState(null);
  const [batch, setBatch] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const finished = useRef(0);

  useEffect(() => {
    api.simulateInfo(token).then(setInfo).catch((e) => setError(e.message));
  }, [token]);

  useEffect(() => {
    if (!info?.available) return undefined;
    const t = setTimeout(() => {
      api.simulateEstimate(token, counts).then(setEstimate).catch(() => setEstimate(null));
    }, 250);
    return () => clearTimeout(t);
  }, [token, counts, info]);

  // Poll the batch; reload the worklist whenever another study finishes.
  useEffect(() => {
    if (!batch?.running) return undefined;
    const t = setInterval(async () => {
      try {
        const b = await api.simulateStatus(token, batch.batch);
        setBatch(b);
        const done = b.items.filter((i) => i.status === "done" || i.status === "failed").length;
        if (done !== finished.current) {
          finished.current = done;
          if (onProgress) onProgress();
        }
      } catch (e) {
        setError(e.message);
      }
    }, POLL_MS);
    return () => clearInterval(t);
  }, [token, batch, onProgress]);

  const types = info?.types || [];
  const pools = useMemo(() => [...new Set(types.filter((t) => counts[t.type] > 0).map((t) => t.pool))], [types, counts]);
  const covered = new Set(readers.filter((r) => chosen.includes(r.id)).flatMap((r) => r.pools));
  const gap = chosen.length > 0 && pools.some((p) => !covered.has(p));
  const total = Object.values(counts).reduce((a, b) => a + b, 0);

  async function send() {
    setBusy(true);
    setError(null);
    try {
      finished.current = 0;
      setBatch(await api.simulate(token, counts, chosen));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card wide-modal" role="dialog" aria-label="Simulate ingest"
           onClick={(e) => e.stopPropagation()} data-testid="simulate-panel">
        <div className="modal-header">
          <div>
            <h2 className="modal-title">Simulate ingest</h2>
            <p className="modal-subtitle">
              Studies from the staged pool, already de-identified at the edge, sent through the full
              pipeline: {info?.runtime === "aws"
                ? "HealthImaging import, the chest Lambda or a SageMaker async endpoint, triage, DynamoDB, evidence to S3"
                : "Orthanc import, in-process models, triage, DynamoDB Local"}.
            </p>
          </div>
          <button type="button" className="btn-close" onClick={onClose} aria-label="Close">Close</button>
        </div>

        {error && <p className="error" role="alert">{error}</p>}
        {!info && !error && <p className="note">Checking the pool.</p>}
        {info && !info.available && (
          <p className="note" data-testid="simulate-unavailable">Not available here: {info.reason}</p>
        )}

        {info?.available && !batch && (
          <>
            <table className="simulate-counts">
              <thead><tr><th>Study type</th><th>Reading pool</th><th className="num">Staged</th><th className="num">Send</th></tr></thead>
              <tbody>
                {types.map((t) => (
                  <tr key={t.type}>
                    <td>{t.label}</td><td>{t.pool}</td><td className="mono num">{t.staged}</td>
                    <td className="num">
                      <input type="number" min="0" max={Math.min(t.cap, t.staged)} value={counts[t.type]}
                             aria-label={`${t.label} count`} className="count-input"
                             onChange={(e) => setCounts((c) => ({ ...c, [t.type]: Math.max(0, Math.min(Math.min(t.cap, t.staged), Number(e.target.value) || 0)) }))} />
                      <span className="note"> max {Math.min(t.cap, t.staged)}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="note">
              TODO: Alzheimer T1 MR, once its model weights exist.
            </p>

            <ReaderPicker readers={readers} chosen={chosen} setChosen={setChosen} pools={pools} />
            <p className="note">
              Each study is assigned as it finishes: to the chosen reader with the fewest so far, then the fewest in its lane.
              Choose no reader to leave them unassigned.
            </p>

            {estimate && (
              <div className="estimate" data-testid="simulate-estimate">
                <h3>Estimated AWS cost: <span className="mono">${estimate.total_usd.toFixed(2)}</span></h3>
                <ul>
                  {estimate.lines.map((l) => (
                    <li key={l.type}><strong>{l.label} x{l.count}: ${l.usd.toFixed(4)}</strong>. {l.basis}.</li>
                  ))}
                </ul>
                <p className="note">{estimate.note}</p>
              </div>
            )}

            <div className="modal-actions">
              <button type="button" onClick={onClose}>Cancel</button>
              <button type="button" className="btn-primary" disabled={busy || gap || total === 0}
                      onClick={send} data-testid="simulate-send">
                Send {total} {total === 1 ? "study" : "studies"}
              </button>
            </div>
          </>
        )}

        {batch && (
          <div data-testid="simulate-progress">
            <p className="note">
              Batch <span className="mono">{batch.batch}</span>{batch.running ? ", running" : ", finished"}.
              Studies appear on the worklist as each one finishes.
            </p>
            <table className="simulate-counts">
              <thead><tr><th>Type</th><th>Study</th><th>Status</th><th>Lane</th><th>Reader</th></tr></thead>
              <tbody>
                {batch.items.map((i) => (
                  <tr key={i.run_id}>
                    <td>{i.type}</td>
                    <td className="mono" title={i.study}>{i.study.slice(-12)}</td>
                    <td>{STATUS[i.status] || i.status}{i.error ? `: ${i.error}` : ""}</td>
                    <td>{i.lane ? <span className={`lanetag lane-${i.lane}`}>{i.lane}</span> : "--"}</td>
                    <td>{readers.find((r) => r.id === i.assigned_to)?.name || (i.assigned_to ? i.assigned_to : "--")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="modal-actions">
              <button type="button" onClick={onClose}>{batch.running ? "Close, keep running" : "Close"}</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
