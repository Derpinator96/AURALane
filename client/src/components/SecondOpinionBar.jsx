import { useEffect, useState } from "react";
import { api } from "../api.js";
import { timeUTC } from "../worklist.js";
import { UsersIcon } from "./Icons.jsx";
import { Overlay } from "./ui.jsx";

// Where a request has got to, from the radiologist asked.
export const OPINION_STATUS = { waiting: "Waiting", opened: "Opened", draft: "Draft saved", reported: "Reported" };

// Sending a study to another radiologist, as mail: choose who, write a message if wanted, send. Only those
// who read the study's pool, and have not been sent it, are offered. Anything on screen can open it
// (the abstention tray's button does) with askForSecondOpinion().
const ASK = "auralane:ask-opinion";
export const askForSecondOpinion = () => window.dispatchEvent(new CustomEvent(ASK));

function AskDialog({ detail, token, me, onClose, onSent }) {
  const s = detail.study;
  const [readers, setReaders] = useState(null);
  const [chosen, setChosen] = useState([]);
  const [note, setNote] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const asked = new Set((detail.opinions || []).map((o) => o.to));

  useEffect(() => {
    let live = true;
    api.readers(token).then((r) => live && setReaders(r.readers)).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [token]);

  const options = (readers || []).filter((r) => r.id !== me && !asked.has(r.id) && r.pools.includes(s.pool));
  const toggle = (id) => setChosen((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id]));

  async function send() {
    setBusy(true);
    setError(null);
    try {
      await api.requestOpinions(token, s.study, chosen, note.trim());
      onSent();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <Overlay onClose={onClose}>
      <div className="modal-card" role="dialog" aria-modal="true" aria-label="Get a second opinion" data-testid="ask-opinion-dialog">
        <div className="modal-header">
          <div>
            <h2 className="modal-title">Get a second opinion</h2>
            <div className="crumbs"><span className="mono-id">{s.patient_id || s.study}</span> <span aria-hidden="true">›</span> <strong>{s.pool} pool</strong></div>
            <p className="meta">It stays on your worklist.</p>
          </div>
          <div className="modal-actions">
            <button type="button" className="pill pill-quiet" onClick={onClose}>Cancel</button>
            <button type="button" className="pill pill-primary" disabled={busy || chosen.length === 0} onClick={send}
                    data-testid="opinion-send">Send{chosen.length > 1 ? ` to ${chosen.length}` : ""}</button>
          </div>
        </div>

        <fieldset className="reader-picker" data-testid="opinion-readers">
          <legend>To ({chosen.length} chosen)</legend>
          {readers && options.length === 0 && (
            <p className="note" data-testid="opinion-no-readers">
              {asked.size ? "Everyone who reads the " : "No other radiologist reads the "}{s.pool} pool {asked.size ? "has been asked." : "yet."}
            </p>
          )}
          <div className="reader-grid">
            {options.map((r) => (
              <label key={r.id} className="reader-option">
                <input type="checkbox" checked={chosen.includes(r.id)} onChange={() => toggle(r.id)} />
                <span className="reader-name">{r.name}</span>
                <span className="meta">{r.pools.join(", ")}</span>
              </label>
            ))}
          </div>
        </fieldset>

        <label className="field-label">Message (optional)
          <textarea value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} rows={4}
                    aria-label="Message for the radiologists" data-testid="opinion-note" />
        </label>
        {error && <p className="error" role="alert">{error}</p>}
      </div>
    </Overlay>
  );
}

// On a study: who has been asked for a second opinion and how far each has got, who asked you, and, for
// the reader of the study, the button that asks more radiologists. Their reports are in the report
// dropdown under the draft.
export default function SecondOpinionBar({ detail, token, me, onChanged }) {
  const [asking, setAsking] = useState(false);
  const ops = detail.opinions || [];
  const from = detail.my_opinion;
  const canAsk = detail.can_request_opinion !== false;

  useEffect(() => {
    if (!canAsk) return undefined;
    const open = () => setAsking(true);
    window.addEventListener(ASK, open);
    return () => window.removeEventListener(ASK, open);
  }, [canAsk]);

  if (!ops.length && !from && !canAsk) return null;

  return (
    <section className="opinion-bar" data-testid="opinion-bar" aria-label="Second opinions">
      {from && (
        <p className="opinion-from" data-testid="opinion-from">
          Second opinion requested by <strong>{from.requested_by_name || from.requested_by}</strong> at {timeUTC(from.at)} UTC
          {from.note && <q className="opinion-note">{from.note}</q>}
        </p>
      )}
      {ops.length > 0 && (
        <div className="opinion-summary">
          <span className="opinion-count" data-testid="opinion-count">
            Sent to {ops.length} {ops.length === 1 ? "radiologist" : "radiologists"}
          </span>
          <ul className="opinion-people">
            {ops.map((o) => (
              <li key={o.to} className={`chip chip-quiet opinion-${o.status}`} data-testid="opinion-person"
                  title={`Sent by ${o.requested_by_name || o.requested_by} at ${timeUTC(o.at)} UTC${o.note ? `: ${o.note}` : ""}`}>
                <span className="dot" aria-hidden="true" />
                {o.to === me ? "You" : o.to_name || o.to}
                <span className="opinion-state">{OPINION_STATUS[o.status]}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {canAsk && (
        <button type="button" className="pill pill-sm opinion-ask" onClick={() => setAsking(true)} data-testid="ask-opinion">
          <UsersIcon size={15} />{ops.length ? "Send to another radiologist" : "Get a second opinion"}
        </button>
      )}
      {asking && (
        <AskDialog detail={detail} token={token} me={me} onClose={() => setAsking(false)}
                   onSent={() => { setAsking(false); if (onChanged) onChanged(detail.study); }} />
      )}
    </section>
  );
}
