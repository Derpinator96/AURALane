import { readerLoad, summarize, waitText, waitingByLane } from "../dashboard.js";
import { laneName } from "../worklist.js";
import { Gauge } from "./charts.jsx";
import { AlertIcon, CheckIcon, WorklistIcon } from "./Icons.jsx";
import { Monogram } from "./ui.jsx";

function Stat({ icon, label, value, meta, onClick, pressed, testid }) {
  const body = (
    <>
      <div className="stat-top"><span className="stat-ico">{icon}</span><span className="stat-label">{label}</span></div>
      <div className="stat-mid"><span className="stat-value">{value}</span></div>
      <div className="stat-meta">{meta}</div>
    </>
  );
  return onClick ? (
    <button type="button" className="card stat stat-btn" onClick={onClick} aria-pressed={pressed} data-testid={testid}>{body}</button>
  ) : (
    <div className="card stat" data-testid={testid}>{body}</div>
  );
}

// Critical, the Abstention Tray, agreement with the lane. The same counts the Reports
// "Worklist summary" used to show, now on the dashboard.
export function StatRow({ studies, onlyTriage, onToggleTriage }) {
  const s = summarize(studies);
  return (
    <div className="stat-row" data-testid="stat-row">
      <Stat testid="stat-critical" icon={<AlertIcon size={16} />} label="Critical" value={s.critical}
            meta={s.waitingCritical ? `oldest unread ${waitText(s.oldestMs)}` : "none waiting"} />
      <Stat testid="stat-triage" icon={<WorklistIcon size={16} />} label="Abstention Tray" value={s.triage}
            meta={onlyTriage ? "Showing these only" : `${s.waiting.ABSTAIN} unread`}
            onClick={onToggleTriage} pressed={onlyTriage} />
      <Stat testid="stat-agreement" icon={<CheckIcon size={16} />} label="Agreement with the lane"
            value={s.agreementRate == null ? "--" : `${s.agreementRate.toFixed(1)}%`}
            meta={s.verdicts ? `${s.verdicts} ${s.verdicts === 1 ? "verdict" : "verdicts"}` : "No verdicts yet"} />
    </div>
  );
}

// Unread studies per lane and the longest wait in each: the number the queue exists to bring down.
export function WaitingCard({ studies, laneLabels, scopeLabel }) {
  const rows = waitingByLane(studies);
  const max = Math.max(1, ...rows.map((r) => r.count));
  return (
    <section className="card waiting-card" aria-label="Waiting by lane" data-testid="waiting-card">
      <div className="card-head">
        <h2 className="card-title">Waiting by lane</h2>
        <span className="meta">{scopeLabel}</span>
      </div>
      <ul className="wait-list">
        {rows.map((r) => (
          <li key={r.lane} className={`wait-row lane-${r.lane}`} data-testid={`wait-${r.lane}`}>
            <span className="dot" aria-hidden="true" />
            <span className="wait-name">
              <strong>{laneName(r.lane, laneLabels[r.lane])}</strong>
              <span className="meta">{!r.count ? "None waiting" : r.oldestMs == null ? "Waiting" : `Oldest ${waitText(r.oldestMs)}`}</span>
            </span>
            <span className="wait-track" aria-hidden="true">
              <span className="wait-fill" style={{ width: `${r.count ? Math.max(3, (r.count / max) * 100) : 0}%` }} />
            </span>
            <span className="wait-count">{r.count}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function GaugeCard({ studies, scopeLabel }) {
  const s = summarize(studies);
  return (
    <section className="card gauge-card" aria-label="Read progress" data-testid="gauge-card">
      <div className="card-head">
        <h2 className="card-title">Read progress</h2>
        <span className="meta">{scopeLabel}</span>
      </div>
      <Gauge read={s.read} unread={s.unread} />
      <div className="legend">
        <span className="chip chip-quiet"><span className="dot series-dot-0" />Read {s.read}</span>
        <span className="chip chip-quiet"><span className="dot series-dot-idle" />Unread {s.unread}</span>
      </div>
    </section>
  );
}

// From api.readers and the rows' assigned_to. No photos and no availability: the API has neither.
export function ReadersCard({ readers, studies }) {
  const list = readerLoad(readers, studies);
  return (
    <section className="card readers-card" aria-label="Readers" data-testid="readers-card">
      <div className="card-head"><h2 className="card-title">Readers</h2><span className="meta">{list.length}</span></div>
      {list.length === 0 ? <p className="note">No radiologist accounts found.</p> : (
        <ul className="readers">
          {list.map((r) => (
            <li key={r.id} className="reader-row" data-testid="reader-row">
              <Monogram name={r.name} />
              <span className="reader-who"><strong>{r.name}</strong><span className="meta">{r.pools.join(", ")}</span></span>
              <span className={`chip ${r.unread ? "" : "chip-quiet"}`}>{r.unread} unread</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
