import { useCallback, useEffect, useState } from "react";
import { timeUTC } from "./worklist.js";

// Admin: the pipeline as it runs, and who reads what. Both read only what the
// API computed from the audit trail and the worklist rows; study ids and lanes
// only, never a study's images or findings.

const POLL_MS = 2000;
const LANES = ["CRITICAL", "URGENT", "ABSTAIN", "EXPEDITED", "ROUTINE", "FAILED"];
const secs = (ms) => (ms == null ? "--" : ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`);
const short = (uid) => (uid && uid.length > 14 ? `...${uid.slice(-10)}` : uid);

function usePoll(load, ms = POLL_MS) {
  const [state, setState] = useState({ data: null, error: null });
  useEffect(() => {
    let live = true;
    const tick = () => load().then((data) => live && setState({ data, error: null }),
                                   (error) => live && setState((s) => ({ ...s, error })));
    tick();
    const t = setInterval(tick, ms);
    return () => { live = false; clearInterval(t); };
  }, [load, ms]);
  return state;
}

function Timeline({ study, load, onClose }) {
  const [t, setT] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { load(study).then(setT).catch((e) => setError(e.message)); }, [study, load]);
  const max = t ? Math.max(...t.steps.map((s) => s.duration_ms), 1) : 1;
  return (
    <section className="panel pipe-timeline" data-testid="pipeline-timeline" aria-label="Study timeline">
      <div className="pipe-timeline-head">
        <h3>Study <span className="mono-id">{short(study)}</span>{t && <> {t.modality}, <span className={`lanetag lane-${t.lane}`}>{t.lane}</span></>}</h3>
        <button type="button" className="pill pill-sm" onClick={onClose}>Close</button>
      </div>
      {error && <p className="error">{error}</p>}
      {t && (
        <>
          <p className="note">End to end {secs(t.end_to_end_ms)}, model {t.model_id || "--"}, run <span className="mono-id">{t.run_id}</span>.</p>
          <table className="admin pipe-steps">
            <thead><tr><th>Step</th><th>Service</th><th>Duration</th><th /></tr></thead>
            <tbody>
              {t.steps.map((s, i) => (
                <tr key={i} className={s.outcome !== "ok" ? "failed" : ""}>
                  <td>{s.action}{s.outcome !== "ok" && <strong> failed</strong>}</td>
                  <td>{s.service || "--"}</td>
                  <td className="mono num">{secs(s.duration_ms)}</td>
                  <td className="bar-cell"><div className="pipe-bar" style={{ width: `${(100 * s.duration_ms) / max}%` }} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {t.steps.some((s) => s.detail?.error) && (
            <p className="error">{t.steps.find((s) => s.detail?.error).detail.error}</p>
          )}
        </>
      )}
    </section>
  );
}

export function Pipeline({ load, loadStudy }) {
  const { data, error } = usePoll(load);
  const [open, setOpen] = useState(null);
  if (error && !data) return <p className="error" role="alert">Could not load the pipeline: {String(error.message)}</p>;
  if (!data) return <p>Loading the pipeline.</p>;
  const stages = data.stages;
  const idx = Object.fromEntries(stages.map((s, i) => [s.stage, i]));
  const running = data.batches.some((b) => b.running);

  return (
    <div className="pipeline-view" data-testid="pipeline-view">
      {running && <p className="chip pipe-running">A simulate batch is running</p>}

      <ol className="pipe-flow" data-testid="pipe-flow">
        {stages.map((s) => (
          <li key={s.stage} className={`card pipe-stage ${s.count === 0 && s.failed === 0 ? "idle" : ""}`}>
            <span className="pipe-label">{s.label}</span>
            <span className="pipe-service">{s.service || "no runs yet"}</span>
            <span className="pipe-count mono">{s.count}</span>
            <span className="pipe-times mono">median {secs(s.median_ms)}<br />last {secs(s.last_ms)}</span>
            {s.failed > 0 && <span className="pipe-failed">{s.failed} failed</span>}
          </li>
        ))}
      </ol>

      {data.overdue.length > 0 && (
        <div className="pipe-overdue" role="alert" data-testid="pipe-overdue">
          {data.overdue.length} critical {data.overdue.length === 1 ? "study has" : "studies have"} not been opened within the 15 minute clock:{" "}
          {data.overdue.map((o) => `${short(o.study)} (${o.assigned_name || o.assigned_to})`).join(", ")}.
        </div>
      )}

      <section className="panel">
      <h2 className="card-title">Simulated studies since this API started</h2>
      {data.live.length === 0 ? (
        <p className="empty-line">No simulate batch yet</p>
      ) : (
        <div className="pipe-live" data-testid="pipe-live">
          {data.live.map((l) => {
            const reached = l.stage ? idx[l.stage] : -1;
            return (
              <button type="button" key={l.study} className={`pipe-live-row ${l.failed ? "failed" : ""}`}
                      onClick={() => setOpen(l.study)} title="Show this study's timeline">
                <span className="pipe-live-id mono-id">{l.type} {short(l.study)}</span>
                <span className="pipe-track" style={{ gridTemplateColumns: `repeat(${stages.length}, 1fr)` }}>
                  {stages.map((s, i) => (
                    <span key={s.stage}
                          className={`pipe-cell ${i <= reached ? `on lane-${l.lane || "PENDING"}` : ""} ${i === reached && !l.done ? "head" : ""}`} />
                  ))}
                </span>
                <span className="pipe-live-state">
                  {l.failed ? "failed" : l.done ? <span className={`lanetag lane-${l.lane}`}>{l.lane}</span> : l.status}
                  {l.end_to_end_ms != null && <span className="mono"> {secs(l.end_to_end_ms)}</span>}
                </span>
              </button>
            );
          })}
        </div>
      )}
      </section>

      {open && <Timeline study={open} load={loadStudy} onClose={() => setOpen(null)} />}

      <div className="pipe-totals">
        <section className="panel">
          <h2 className="card-title">Today ({data.totals.day}, UTC): {data.totals.studies} studies</h2>
          <table className="admin" data-testid="pipe-today">
            <thead><tr><th>Modality</th>{LANES.map((l) => <th key={l}>{l === "ABSTAIN" ? "HUMAN" : l}</th>)}<th>End to end, median</th></tr></thead>
            <tbody>
              {[...new Set(data.totals.by_modality_lane.map((r) => r.modality))].map((m) => (
                <tr key={m}>
                  <td>{m}</td>
                  {LANES.map((l) => (
                    <td key={l} className="mono num">
                      {data.totals.by_modality_lane.find((r) => r.modality === m && r.lane === l)?.count || 0}
                    </td>
                  ))}
                  <td className="mono num">
                    {secs(data.totals.end_to_end_median_ms[m])}
                    {data.totals.end_to_end_n[m] ? <span className="note"> (n={data.totals.end_to_end_n[m]})</span> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
        <section className="panel">
          <h2 className="card-title">Latest runs</h2>
          {data.recent.length === 0 ? <p className="empty-line">No pipeline runs recorded</p> : (
            <table className="admin">
              <tbody>
                {data.recent.map((r) => (
                  <tr key={r.study} className="clickable" onClick={() => setOpen(r.study)}>
                    <td className="mono-id">{short(r.study)}</td><td>{r.modality}</td>
                    <td>{r.lane && <span className={`lanetag lane-${r.lane}`}>{r.lane}</span>}</td>
                    <td className="mono num">{secs(r.end_to_end_ms)}</td>
                    <td>{r.failed ? "failed" : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </div>
  );
}

export function Assignments({ load, reassign }) {
  const [tick, setTick] = useState(0);
  const loader = useCallback(() => load(), [load, tick]); // eslint-disable-line react-hooks/exhaustive-deps
  const { data, error } = usePoll(loader, 5000);
  const [msg, setMsg] = useState(null);
  if (error && !data) return <p className="error" role="alert">Could not load assignments: {String(error.message)}</p>;
  if (!data) return <p>Loading assignments.</p>;

  async function move(study, reader) {
    setMsg(null);
    try {
      await reassign(study, reader || null);
      setTick((t) => t + 1);
    } catch (e) {
      setMsg(e.message);
    }
  }

  return (
    <div className="assignments" data-testid="assignments">
      <section className="panel">
      {data.clock && <p className="meta">{data.clock}</p>}
      <table className="admin" data-testid="assignments-readers">
        <thead>
          <tr><th>Reader</th><th>Pools</th>{data.lanes.map((l) => <th key={l}>{data.lane_labels[l]}</th>)}
            <th>Total</th><th>Unread</th><th>Not opened in time</th></tr>
        </thead>
        <tbody>
          {data.readers.map((r) => (
            <tr key={r.id} className={r.overdue ? "overdue" : ""}>
              <td>{r.name}</td><td>{r.pools.join(", ")}</td>
              {data.lanes.map((l) => <td key={l} className="mono num">{r.lanes[l] || 0}</td>)}
              <td className="mono num">{r.total}</td><td className="mono num">{r.unread}</td>
              <td className="mono num">{r.overdue}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="chip chip-quiet">{data.unassigned} unassigned</p>
      </section>
      <section className="panel">
      {msg && <p className="error" role="alert">{msg}</p>}
      <table className="admin" data-testid="assignments-studies">
        <thead><tr><th>Study</th><th>Lane</th><th>Pool</th><th>Arrived UTC</th><th>Opened</th><th>Reader</th></tr></thead>
        <tbody>
          {data.studies.map((s) => (
            <tr key={s.study} className={s.overdue ? "overdue" : ""} data-testid="assignment-row">
              <td className="mono-id" title={s.study}>{short(s.study)}</td>
              <td><span className={`lanetag lane-${s.lane}`}>{s.lane_label}</span></td>
              <td>{s.pool}</td>
              <td className="mono">{timeUTC(s.arrived)}</td>
              <td>{s.read ? "read" : s.opened_at ? `opened ${timeUTC(s.opened_at)}` : s.overdue ? "not opened, past the clock" : "no"}</td>
              <td>
                <select value={s.assigned_to || ""} aria-label={`Reader for ${s.study}`}
                        onChange={(e) => move(s.study, e.target.value)}>
                  <option value="">Unassigned</option>
                  {data.readers.filter((r) => r.pools.includes(s.pool) || r.id === s.assigned_to)
                    .map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </section>
    </div>
  );
}
