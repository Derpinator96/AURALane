import { useEffect, useState } from "react";
import { api } from "../api.js";
import { askForSecondOpinion } from "./SecondOpinionBar.jsx";

const LANES = [["CRITICAL", "Critical"], ["URGENT", "Urgent"], ["EXPEDITED", "Expedited"], ["ROUTINE", "Routine"]];

// The driver's signal against the band where the model does not commit: a track from 0 to
// 1, the band shaded, and a marker where the signal is.
function Band({ lo, hi, value }) {
  const pct = (v) => `${Math.max(0, Math.min(1, v)) * 100}%`;
  return (
    <div className="band" role="img" aria-label={`Signal ${value.toFixed(2)} in the ${lo.toFixed(2)} to ${hi.toFixed(2)} band`}>
      <span className="band-zone" style={{ left: pct(lo), width: `${(hi - lo) * 100}%` }} />
      <span className="band-marker" style={{ left: pct(value) }} />
    </div>
  );
}

// The Abstention Tray, for a study the system did not place: why it did not, then
// the three things a reader can do about it. Assigning a lane and marking it inadequate are audited by
// the API and take effect at once; getting a second opinion opens the same dialog every study has, and
// the study stays where it is.
//
//   onChanged(study)   the study's new row (view) after an action
export default function AbstentionTray({ detail, token, onChanged }) {
  const s = detail.study;
  const [action, setAction] = useState(null);         // "lane" | "inadequate"
  const [lane, setLane] = useState("URGENT");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    setAction(null); setReason(""); setError(null);
  }, [s.study]);

  if (s.lane !== "ABSTAIN") return null;

  const [lo, hi] = detail.abstain_band || [0.35, 0.6];
  const driverFinding = detail.findings?.find((f) => f.name === s.driver);
  const why = s.abstain_reason || "The system did not record a reason.";

  async function run(fn, done) {
    setBusy(true);
    setError(null);
    try {
      const res = await fn();
      done(res);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const need = (label) => reason.trim().length < 3 && `${label} needs a short reason.`;

  return (
    <section className="card tray" data-testid="abstention-tray" aria-label="Abstention Tray">
      <h3 className="sec-title">Abstention Tray</h3>
      <div className="abstain-why" data-testid="abstain-why">
        {driverFinding ? (
          <>
            <p>
              {driverFinding.label}: signal <strong className="mono">{Number(driverFinding.signal).toFixed(2)}</strong> against
              the <span className="mono">{lo.toFixed(2)}</span> to <span className="mono">{hi.toFixed(2)}</span> band
            </p>
            <Band lo={lo} hi={hi} value={Number(driverFinding.signal)} />
          </>
        ) : null}
        {/* The band sentence above already says it; anything the system recorded
            beyond that (the brain mask checks, the volume gate) is shown as written. */}
        {!(driverFinding && /band where the model does not commit/.test(why)) && (
          <p className="note" data-testid="abstain-reason">{why}</p>
        )}
      </div>

      {!action && (
        <div className="tray-actions" role="group" aria-label="Abstention actions">
          <button type="button" className="pill pill-primary" onClick={() => setAction("lane")} data-testid="tray-lane">Assign a lane</button>
          <button type="button" className="pill" onClick={askForSecondOpinion} data-testid="tray-second">Get a second opinion</button>
          <button type="button" className="pill" onClick={() => setAction("inadequate")} data-testid="tray-inadequate">Mark technically inadequate</button>
        </div>
      )}

      {action === "lane" && (
        <form className="tray-form" onSubmit={(e) => {
          e.preventDefault();
          if (need("A lane")) return;
          run(() => api.setLane(token, s.study, lane, reason.trim()), (res) => onChanged(res.study));
        }}>
          <div className="lane-picker" role="radiogroup" aria-label="Lane">
            {LANES.map(([id, label]) => (
              <label key={id} className={`lanetag lane-${id} pickable ${lane === id ? "on" : ""}`}>
                <input type="radio" className="sr-only" name="lane" value={id} checked={lane === id} onChange={() => setLane(id)} />
                {label}
              </label>
            ))}
          </div>
          <label className="field-label">Reason (required)
            <input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500}
                   aria-label="Reason for the lane" data-testid="tray-reason" />
          </label>
          <div className="tray-buttons">
            <button type="button" className="pill pill-quiet" onClick={() => setAction(null)}>Cancel</button>
            <button type="submit" className="pill pill-primary" disabled={busy || Boolean(need("A lane"))}
                    data-testid="tray-lane-confirm">Place in {LANES.find(([id]) => id === lane)[1]}</button>
          </div>
        </form>
      )}

      {action === "inadequate" && (
        <form className="tray-form" onSubmit={(e) => {
          e.preventDefault();
          if (need("Marking a study inadequate")) return;
          run(() => api.markInadequate(token, s.study, reason.trim()), (res) => onChanged(res.study));
        }}>
          <label className="field-label">Why it is technically inadequate (required)
            <input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500}
                   aria-label="Reason it is inadequate" data-testid="tray-reason" />
          </label>
          <div className="tray-buttons">
            <button type="button" className="pill pill-quiet" onClick={() => setAction(null)}>Cancel</button>
            <button type="submit" className="pill pill-primary" disabled={busy || Boolean(need("Marking a study inadequate"))}
                    data-testid="tray-inadequate-confirm">Move to Repeat imaging</button>
          </div>
        </form>
      )}

      {error && <p className="error" role="alert">{error}</p>}
    </section>
  );
}

// What a study that a reader placed or set aside says about itself.
export function HumanLaneNote({ study }) {
  if (study.human_lane) {
    return (
      <p className="human-lane-note" data-testid="human-lane-note">
        Lane set by <strong>{study.human_lane.by_name || study.human_lane.by}</strong>: {study.human_lane.reason}.
        {study.abstain_reason ? <span className="note"> The system had abstained: {study.abstain_reason}</span> : null}
      </p>
    );
  }
  if (study.repeat_imaging) {
    return (
      <p className="human-lane-note" data-testid="repeat-note">
        Marked technically inadequate by <strong>{study.repeat_imaging.by_name || study.repeat_imaging.by}</strong>:
        {" "}{study.repeat_imaging.reason}. Waiting for repeat imaging.
      </p>
    );
  }
  if (study.second_read) {
    return (
      <p className="human-lane-note" data-testid="second-read-note">
        Second read requested by {study.second_read.requested_by_name || study.second_read.requested_by}.
      </p>
    );
  }
  return null;
}
