import { useMemo, useState } from "react";
import { api } from "../api.js";
import { ReaderPicker } from "./SimulatePanel.jsx";
import { Overlay } from "./ui.jsx";

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
    <Overlay onClose={onClose}>
      <div className="modal-card" role="dialog" aria-modal="true" aria-label="Distribute worklist" data-testid="distribute-panel">
        <div className="modal-header">
          <div>
            <h2 className="modal-title">Distribute worklist</h2>
            <div className="crumbs">Worklist <span aria-hidden="true">›</span> <strong>Distribute</strong></div>
          </div>
          <div className="modal-actions">
            {!result ? (
              <>
                <button type="button" className="pill pill-quiet" onClick={onClose}>Cancel</button>
                <button type="button" className="pill pill-primary" disabled={busy || gap || chosen.length === 0}
                        onClick={send} data-testid="distribute-send">Distribute</button>
              </>
            ) : (
              <button type="button" className="pill pill-primary" onClick={onClose}>Close</button>
            )}
          </div>
        </div>

        {!result && (
          <>
            <p className="meta" data-testid="distribute-summary">{unread.length} unread · split in priority order</p>
            <ReaderPicker readers={readers} chosen={chosen} setChosen={setChosen} pools={pools} />
            {error && <p className="error" role="alert">{error}</p>}
          </>
        )}
        {result && (
          <table className="simulate-counts" data-testid="distribute-result">
            <thead><tr><th>Reader</th><th className="num">Studies</th><th className="num">Critical</th></tr></thead>
            <tbody>
              {result.readers.map((r) => (
                <tr key={r.id}><td>{r.name}</td><td className="mono num">{r.studies}</td><td className="mono num">{r.critical}</td></tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Overlay>
  );
}
