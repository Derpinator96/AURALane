import { arrivalsByHour, readerLoad, summarize, waitText, WAITING_LANES } from "../dashboard.js";
import { ArrivalsChart, Gauge, MiniBars } from "./charts.jsx";
import { AlertIcon, CheckIcon, WorklistIcon } from "./Icons.jsx";
import { Monogram } from "./ui.jsx";

function Stat({ icon, label, value, meta, chart, onClick, pressed, testid }) {
  const body = (
    <>
      <div className="stat-top"><span className="stat-ico">{icon}</span><span className="stat-label">{label}</span></div>
      <div className="stat-mid"><span className="stat-value">{value}</span>{chart}</div>
      <div className="stat-meta">{meta}</div>
    </>
  );
  return onClick ? (
    <button type="button" className="card stat stat-btn" onClick={onClick} aria-pressed={pressed} data-testid={testid}>{body}</button>
  ) : (
    <div className="card stat" data-testid={testid}>{body}</div>
  );
}

// Critical, needs triage, agreement with the lane. The same counts the Reports
// "Worklist summary" used to show, now on the dashboard.
export function StatRow({ studies, laneLabels, onlyTriage, onToggleTriage }) {
  const s = summarize(studies);
  return (
    <div className="stat-row" data-testid="stat-row">
      <Stat testid="stat-critical" icon={<AlertIcon size={16} />} label="Critical" value={s.critical}
            meta={s.waitingCritical ? `oldest ${waitText(s.oldestMs)}` : "none waiting"}
            chart={<MiniBars label="Studies waiting per lane"
                             items={WAITING_LANES.map((k) => ({ key: k, label: laneLabels[k] || k, value: s.waiting[k] }))} />} />
      <Stat testid="stat-triage" icon={<WorklistIcon size={16} />} label="Needs triage" value={s.triage}
            meta={onlyTriage ? "showing these only" : `${s.waiting.ABSTAIN} unread`}
            onClick={onToggleTriage} pressed={onlyTriage} />
      <Stat testid="stat-agreement" icon={<CheckIcon size={16} />} label="Agreement with the lane"
            value={s.agreementRate == null ? "--" : `${s.agreementRate.toFixed(1)}%`}
            meta={`${s.verdicts} ${s.verdicts === 1 ? "verdict" : "verdicts"}`} />
    </div>
  );
}

const fmtDay = (day) =>
  new Date(`${day}T00:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });

export function ArrivalsCard({ studies, pools }) {
  const names = pools.map((p) => p.pool);
  const a = arrivalsByHour(studies, names);
  return (
    <section className="card arrivals-card" aria-label="Arrivals per hour" data-testid="arrivals-card">
      <div className="card-head">
        <h2 className="card-title">Arrivals per hour</h2>
        {a && <span className="meta">{fmtDay(a.day)}, UTC</span>}
      </div>
      {a ? (
        <>
          <ArrivalsChart hours={a.hours} pools={names} max={a.max} />
          <div className="legend">
            {pools.map((p, i) => (
              <span key={p.pool} className="chip chip-quiet"><span className={`dot series-dot-${i}`} />{p.label}</span>
            ))}
          </div>
        </>
      ) : <p className="note">No arrivals yet.</p>}
    </section>
  );
}

export function GaugeCard({ studies, scopeLabel }) {
  const s = summarize(studies);
  return (
    <section className="card gauge-card" aria-label="Queue" data-testid="gauge-card">
      <div className="card-head">
        <h2 className="card-title">Queue</h2>
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
