import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { arrange, READ_FILTERS, SORTS, timeUTC, isUnread } from "./worklist.js";

const LANE_FILTERS = ["ALL", "CRITICAL", "URGENT", "EXPEDITED", "ROUTINE"];

function Acuity({ row }) {
  // Copied from the API. Abstained and failed studies have no lane, so no
  // acuity is shown for them, as in the round-2 queue.
  if (row.lane === "ABSTAIN" || row.lane === "FAILED" || row.acuity == null) return "--";
  return row.acuity.toFixed(1);
}

function Row({ row }) {
  const verdict = row.verdict ? `${row.verdict.value === "agree" ? "Agreed" : "Disagreed"}` : "Unread";
  return (
    <li className={`row lane-${row.lane}`} data-testid="study-row" data-study={row.study}>
      <Link to={`/studies/${encodeURIComponent(row.study)}`} className="rowlink">
        <span className="lanetag">{row.lane_label}</span>
        <span className="mono id">{row.patient_id || row.study}</span>
        <span className="exam">{row.exam}</span>
        <span className="mono time">{timeUTC(row.arrived)}</span>
        <span className="driver">{row.lane === "FAILED" ? row.error : row.driver_label || "--"}</span>
        <span className="mono acuity"><Acuity row={row} /></span>
        <span className={`read ${isUnread(row) ? "unread" : ""}`}>{verdict}</span>
        {row.source && (
          <span className="source" title={row.source}>{row.source.split(".")[0]}</span>
        )}
      </Link>
    </li>
  );
}

function Section({ s }) {
  return (
    <section className={`lane lane-${s.lane}`} data-testid={`section-${s.lane}`}>
      <h2>
        <span className="lanename">{s.label}</span>
        {s.clock && <span className="clock">{s.clock}</span>}
        <span className="mono count">({s.rows.length})</span>
      </h2>
      {s.lane === "ABSTAIN" && (
        <p className="why">Model confidence was not sufficient to assign a lane. A radiologist picks it.</p>
      )}
      {s.lane === "FAILED" && (
        <p className="why">Processing did not complete. The study is still in PACS; read it there.</p>
      )}
      <ul>{s.rows.map((r) => <Row key={r.study} row={r} />)}</ul>
    </section>
  );
}

export default function Worklist({ load }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [sort, setSort] = useState("priority");
  const [lane, setLane] = useState("ALL");
  const [read, setRead] = useState("all");

  useEffect(() => {
    let live = true;
    load().then((d) => live && setData(d)).catch((e) => live && setError(e));
    return () => { live = false; };
  }, [load]);

  const sections = useMemo(
    () => (data ? arrange(data.studies, data.lanes, { sort, lane, read }) : []),
    [data, sort, lane, read]);

  if (error) return <main className="worklist"><p className="error" role="alert">Could not load the worklist: {String(error.message)}</p></main>;
  if (!data) return <main className="worklist"><p>Loading worklist.</p></main>;

  return (
    <main className="worklist">
      <div className="controls">
        <label>Sort
          <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort">
            {Object.entries(SORTS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label>Lane
          <select value={lane} onChange={(e) => setLane(e.target.value)} aria-label="Lane filter">
            {LANE_FILTERS.map((l) => <option key={l} value={l}>{l === "ALL" ? "All lanes" : l}</option>)}
          </select>
        </label>
        <label>Status
          <select value={read} onChange={(e) => setRead(e.target.value)} aria-label="Read filter">
            {Object.entries(READ_FILTERS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <span className="note">Needs human triage is always shown and is not affected by filters.</span>
      </div>
      <div className="colhead" aria-hidden="true">
        <span>Lane</span><span>Patient (pseudonym)</span><span>Exam</span><span>Arrived UTC</span>
        <span>Driving finding</span><span>Acuity</span><span>Status</span><span />
      </div>
      {sections.map((s) => <Section key={s.lane} s={s} />)}
    </main>
  );
}
