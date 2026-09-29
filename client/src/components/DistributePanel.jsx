import { useMemo, useState } from "react";
import { api } from "../api.js";
import { ReaderPicker } from "./SimulatePanel.jsx";

// Deal every unread study among the chosen readers, critical first, round robin.
export default function DistributePanel({ token, readers, studies, onClose, onDone }) {
  const [chosen, setChosen] = useState(() => readers.map((r) => r.id));
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const unread = studies.filter((s) => !s.verdict && s.pool !== "Unassigned");
  const pools = useMemo(() => [...new Set(unread.map((s) => s.pool))], [unread]);
  const covered = new Set(readers.filter((r) => chosen.includes(r.id)).flatMap((r) => r.pools));
  const gap = pools.some((p) => !covered.has(p));

  async function send() {
    setBusy(true);
    setError(null);
    try {
      setResult(await api.distribute(token, chosen));
      if (onDone) onDone();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" role="dialog" aria-label="Distribute worklist"
           onClick={(e) => e.stopPropagation()} data-testid="distribute-panel">
        <div className="modal-header">
          <div>
            <h2 className="modal-title">Distribute worklist</h2>
            <p className="modal-subtitle">
              {unread.length} unread {unread.length === 1 ? "study" : "studies"}, dealt in priority order (critical first)
              round robin, so each reader gets the same count and a similar share of critical work. A study goes only to
              a reader whose pools include it. Studies you hand to another reader leave your worklist.
            </p>
          </div>
          <button type="button" className="btn-close" onClick={onClose} aria-label="Close">Close</button>
        </div>
        {!result && (
          <>
            <ReaderPicker readers={readers} chosen={chosen} setChosen={setChosen} pools={pools} />
            {error && <p className="error" role="alert">{error}</p>}
            <div className="modal-actions">
              <button type="button" onClick={onClose}>Cancel</button>
              <button type="button" className="btn-primary" disabled={busy || gap || chosen.length === 0}
                      onClick={send} data-testid="distribute-send">Distribute</button>
            </div>
          </>
        )}
        {result && (
          <>
            <table className="simulate-counts" data-testid="distribute-result">
              <thead><tr><th>Reader</th><th className="num">Studies</th><th className="num">Critical</th></tr></thead>
              <tbody>
                {result.readers.map((r) => (
                  <tr key={r.id}><td>{r.name}</td><td className="mono num">{r.studies}</td><td className="mono num">{r.critical}</td></tr>
                ))}
              </tbody>
            </table>
            <div className="modal-actions"><button type="button" onClick={onClose}>Close</button></div>
          </>
        )}
      </div>
    </div>
  );
}
