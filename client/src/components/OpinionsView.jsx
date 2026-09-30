import { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import { laneName, timeUTC } from "../worklist.js";
import { ArrowUpRightIcon } from "./Icons.jsx";
import { OPINION_STATUS } from "./SecondOpinionBar.jsx";
import { Segmented, Spinner } from "./ui.jsx";

// The studies other radiologists asked this one to read (Received), and the ones this radiologist asked
// others about (Sent). Studies are grouped by reading pool and never mixed; each keeps the API's
// priority order, and the ones still waiting on a report come first.

const findingOf = (s) => (s.lane === "FAILED" ? s.error : s.driver_label || s.abstain_reason || "--");
const acuityOf = (s) => (s.lane === "ABSTAIN" || s.lane === "FAILED" || s.acuity == null ? "--" : Number(s.acuity).toFixed(1));

function byPool(items) {
  const pools = new Map();
  for (const x of items) {
    const pool = x.study.pool;
    if (!pools.has(pool)) pools.set(pool, []);
    pools.get(pool).push(x);
  }
  return [...pools].sort(([a], [b]) => a.localeCompare(b));
}

// A row of the same shape as the worklist's, so the two read as one list.
function Row({ study, selected, onOpen, status, who, at, note, sub, summary }) {
  return (
    <div className={`study-row lane-${study.lane} ${selected ? "selected" : ""}`} data-testid="opinion-row" data-study={study.study}
         onClick={() => onOpen(study.study)}>
      <div className="cell-finding">
        <span className="dot" aria-hidden="true" />
        <span className="finding-stack">
          <span className="finding-line">
            <span className="finding-text" title={findingOf(study)}>{findingOf(study)}</span>
            <span className="row-lane">{laneName(study.lane, study.lane_label)}</span>
          </span>
          {note && <span className="cell-note opinion-quote">{note}</span>}
          {sub && <span className="cell-note opinion-sub" title={sub}>{sub}</span>}
        </span>
      </div>
      <div className="cell-patient mono-id">{study.patient_id || study.study}</div>
      <div className="cell-modality"><span className="chip chip-quiet">{study.exam || study.modality}</span></div>
      <div className="cell-status">
        <span className={`chip chip-quiet opinion-${status}`} data-testid="opinion-status"><span className="dot" />{summary || OPINION_STATUS[status]}</span>
        {who && <span className="cell-reader" title={who}>{who}</span>}
      </div>
      <div className="cell-time mono" title={at}>{timeUTC(at)}</div>
      <div className="cell-acuity mono-id acuity">{acuityOf(study)}</div>
      <button type="button" className="circle circle-sm cell-open" aria-label={`Open ${study.patient_id || study.study}`} title="Open"
              onClick={(e) => { e.stopPropagation(); onOpen(study.study); }}>
        <ArrowUpRightIcon size={15} />
      </button>
    </div>
  );
}

export default function OpinionsView({ token, onOpen, selectedStudyId, refreshSeconds = 0 }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState("received");

  const load = useCallback(() => {
    api.secondOpinions(token).then((d) => { setData(d); setError(null); }).catch((e) => setError(e.message));
  }, [token]);
  // Again when the study sheet closes (a report may have been saved) and on the worklist's timer.
  useEffect(() => { if (!selectedStudyId) load(); }, [load, selectedStudyId]);
  useEffect(() => {
    if (!refreshSeconds) return undefined;
    const t = setInterval(() => { if (!document.hidden) load(); }, refreshSeconds * 1000);
    return () => clearInterval(t);
  }, [load, refreshSeconds]);

  if (error && !data) return <section className="panel" role="alert"><p className="error">Could not load second opinions: {error}</p></section>;
  if (!data) return <section className="panel opinions"><div className="loading-line"><Spinner label="Loading second opinions" /></div></section>;

  const received = data.received, sent = data.sent;
  const list = tab === "received" ? received : sent;
  return (
    <section className="panel queue opinions" data-testid="opinions-view" aria-label="Second opinions">
      <div className="qhead">
        <h2 className="card-title queue-title">{tab === "received" ? "Asked of you" : "Asked by you"}</h2>
        <div className="qhead-right">
          <Segmented small label="Second opinions" value={tab} onChange={setTab} items={[
            { id: "received", label: `Received (${received.length})`, testid: "opinion-tab-received" },
            { id: "sent", label: `Sent (${sent.length})`, testid: "opinion-tab-sent" },
          ]} />
        </div>
      </div>

      {list.length === 0 && (
        <div className="empty-line" data-testid="opinions-empty">
          {tab === "received" ? "No radiologist has asked you for a second opinion." : "You have not asked anyone for a second opinion."}
        </div>
      )}

      <div className="queue-container">
        {byPool(list).map(([pool, items]) => (
          <section key={pool} className="pool-group" data-testid={`opinion-pool-${pool}`} aria-label={`${pool} reading pool`}>
            <div className="pool-header">
              <h3 className="pool-title">{pool} pool</h3>
              <span className="chip chip-quiet">{items.length} {items.length === 1 ? "study" : "studies"}</span>
            </div>
            <div className="lane-group">
              {items.map((x) => tab === "received" ? (
                <Row key={x.study.study} study={x.study} selected={x.study.study === selectedStudyId} onOpen={onOpen}
                     status={x.opinion.status} who={`From ${x.opinion.requested_by_name || x.opinion.requested_by}`}
                     at={x.opinion.at} note={x.opinion.note} />
              ) : (
                <Row key={x.study.study} study={x.study} selected={x.study.study === selectedStudyId} onOpen={onOpen}
                     status={x.opinions.every((o) => o.status === "reported") ? "reported" : x.opinions.some((o) => o.status !== "waiting") ? "opened" : "waiting"}
                     summary={`${x.opinions.filter((o) => o.status === "reported").length} of ${x.opinions.length} reported`}
                     sub={`Asked ${x.opinions.map((o) => o.to_name || o.to).join(", ")}`} at={x.opinions[0].at} />
              ))}
            </div>
          </section>
        ))}
      </div>
    </section>
  );
}
