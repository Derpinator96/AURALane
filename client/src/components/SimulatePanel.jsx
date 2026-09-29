import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api.js";
import { PlusIcon } from "./Icons.jsx";
import { Overlay } from "./ui.jsx";

const POLL_MS = 2000;
const STATUS = { queued: "Queued", receiving: "Receiving", running: "In the pipeline", done: "On the worklist", failed: "Failed" };

// Readers chosen for a batch or a deal, as a checklist with round checks. Says, before
// anything is sent, which pool no chosen reader covers.
export function ReaderPicker({ readers, chosen, setChosen, pools = [] }) {
  const covered = new Set(readers.filter((r) => chosen.includes(r.id)).flatMap((r) => r.pools));
  const gaps = chosen.length ? pools.filter((p) => !covered.has(p)) : [];
  const toggle = (id) => setChosen((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id]));
  return (
    <fieldset className="reader-picker" data-testid="reader-picker">
      <legend>Readers ({chosen.length} of {readers.length})</legend>
      {readers.length === 0 && <p className="note">No radiologist accounts found.</p>}
      <div className="reader-grid">
        {readers.map((r) => (
          <label key={r.id} className="reader-option">
            <input type="checkbox" checked={chosen.includes(r.id)} onChange={() => toggle(r.id)} />
            <span className="reader-name">{r.name}</span>
            <span className="meta">{r.pools.join(", ")}</span>
          </label>
        ))}
      </div>
      {gaps.length > 0 && (
        <p className="error" role="alert" data-testid="pool-gap">
          No chosen reader reads the {gaps.join(" or ")} pool. Add one, or those studies cannot be sent.
        </p>
      )}
    </fieldset>
  );
}

// A count with a minus and a plus, and the number itself typed or stepped.
function Stepper({ value, max, label, onChange }) {
  const set = (n) => onChange(Math.max(0, Math.min(max, n)));
  return (
    <span className="stepper">
      <button type="button" className="circle circle-sm" aria-label={`Fewer ${label}`} disabled={value <= 0} onClick={() => set(value - 1)}>
        <span aria-hidden="true">−</span>
      </button>
      <input type="number" min="0" max={max} value={value} aria-label={`${label} count`} className="count-input"
             onChange={(e) => set(Number(e.target.value) || 0)} />
      <button type="button" className="circle circle-sm" aria-label={`More ${label}`} disabled={value >= max} onClick={() => set(value + 1)}>
        <PlusIcon size={14} />
      </button>
    </span>
  );
}

export default function SimulatePanel({ token, readers, me = null, onClose, onProgress }) {
  const [info, setInfo] = useState(null);
  const [counts, setCounts] = useState({ chest: 3, brain: 1, ct: 1 });
  // A study appears on the worklist of the reader it is sent to, so the default is
  // the signed-in reader alone; add others to share the batch equally.
  const [chosen, setChosen] = useState(() => (readers.some((r) => r.id === me) ? [me] : readers.map((r) => r.id)));
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
  const canSend = Boolean(info?.available) && !busy && !gap && total > 0 && chosen.length > 0;

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
    <Overlay onClose={onClose}>
      <div className="modal-card wide-modal" role="dialog" aria-modal="true" aria-label="Simulate ingest" data-testid="simulate-panel">
        <div className="modal-header">
          <div>
            <h2 className="modal-title">Simulate ingest</h2>
            <div className="crumbs">Worklist <span aria-hidden="true">›</span> <strong>Simulate ingest</strong></div>
          </div>
          <div className="modal-actions">
            {!batch ? (
              <>
                <button type="button" className="pill pill-quiet" onClick={onClose}>Cancel</button>
                <button type="button" className="pill pill-primary" disabled={!canSend} onClick={send} data-testid="simulate-send">
                  Send {total} {total === 1 ? "study" : "studies"}
                </button>
              </>
            ) : (
              <button type="button" className="pill pill-primary" onClick={onClose}>{batch.running ? "Close, keep running" : "Close"}</button>
            )}
          </div>
        </div>

        {error && <p className="error" role="alert">{error}</p>}
        {!info && !error && <p className="note">Checking the pool.</p>}
        {info && !info.available && (
          <p className="note" data-testid="simulate-unavailable">Not available here: {info.reason}</p>
        )}

        {info?.available && !batch && (
          <>
            <div className="sim-types">
              {types.map((t) => (
                <div key={t.type} className="sim-type">
                  <span className="sim-type-name"><strong>{t.label}</strong><span className="meta">{t.pool} pool · {t.staged} staged</span></span>
                  <Stepper value={counts[t.type]} max={Math.min(t.cap, t.staged)} label={t.label}
                           onChange={(n) => setCounts((c) => ({ ...c, [t.type]: n }))} />
                </div>
              ))}
            </div>

            <ReaderPicker readers={readers} chosen={chosen} setChosen={setChosen} pools={pools} />
            <p className="meta" data-testid="share-summary">
              {chosen.length === 0
                ? "Choose at least one radiologist"
                : `${total} ${total === 1 ? "study" : "studies"} to ${chosen.length} ${chosen.length === 1 ? "reader" : "readers"}`}
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
          </>
        )}

        {batch && (
          <div data-testid="simulate-progress">
            <p className="meta">
              Batch <span className="mono-id">{batch.batch}</span> · {batch.running ? "running" : "finished"}
            </p>
            <table className="simulate-counts">
              <thead><tr><th>Type</th><th>Study</th><th>Status</th><th>Lane</th><th>Reader</th></tr></thead>
              <tbody>
                {batch.items.map((i) => (
                  <tr key={i.run_id}>
                    <td>{i.type}</td>
                    <td className="mono-id" title={i.study}>{i.study.slice(-12)}</td>
                    <td>{STATUS[i.status] || i.status}{i.error ? `: ${i.error}` : ""}</td>
                    <td>{i.lane ? <span className={`lanetag lane-${i.lane}`}>{i.lane}</span> : "--"}</td>
                    <td>{readers.find((r) => r.id === i.assigned_to)?.name || (i.assigned_to ? i.assigned_to : "--")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Overlay>
  );
}
