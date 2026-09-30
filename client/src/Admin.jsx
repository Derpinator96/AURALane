import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { laneName, timeUTC } from "./worklist.js";
import { Assignments, Pipeline } from "./AdminOps.jsx";

// Admin screens. They show how the system is configured and what it did; they
// never open a study. Study IDs in the audit log are plain text, not links, and
// the API refuses an admin token on every study route in any case.
// Every number is the API's, read from stored rows or the registry.

function useLoad(load) {
  const [state, setState] = useState({ data: null, error: null });
  useEffect(() => {
    let live = true;
    load().then((data) => live && setState({ data, error: null }),
                (error) => live && setState({ data: null, error }));
    return () => { live = false; };
  }, [load]);
  return state;
}

function Loaded({ state, what, children }) {
  if (state.error) return <p className="error" role="alert">Could not load {what}: {String(state.error.message)}</p>;
  if (!state.data) return <p className="note">Loading {what}.</p>;
  return children(state.data);
}

const detailText = (d) =>
  Object.entries(d || {}).map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`).join("  ");

export function Audit({ load }) {
  const state = useLoad(load);
  return (
    <Loaded state={state} what="the audit log">
      {(d) => (
        <section className="panel">
          <div className="card-head">
            <span className="chip chip-quiet">Showing {d.events.length} of {d.total}, newest first</span>
          </div>
          <table className="admin" data-testid="audit">
            <thead><tr><th>Time (UTC)</th><th>Actor</th><th>Action</th><th>Study</th><th>Outcome</th><th>ms</th><th>Detail</th></tr></thead>
            <tbody>
              {d.events.map((e) => (
                <tr key={e.event_id}>
                  <td className="mono">{e.at?.slice(0, 10)} {timeUTC(e.at)}</td>
                  <td className="mono-id">{e.actor}</td>
                  <td>{e.action}</td>
                  <td className="mono-id">{e.study}</td>
                  <td>{e.outcome}</td>
                  <td className="mono num">{e.duration_ms}</td>
                  <td className="mono-id detail">{detailText(e.detail)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {d.events.length === 0 && <p className="empty-line">No audit events yet</p>}
        </section>
      )}
    </Loaded>
  );
}

export function LaneMix({ load }) {
  const state = useLoad(load);
  return (
    <Loaded state={state} what="the lane mix">
      {(d) => (
        <section className="panel">
          <div className="card-head">
            {d.placed_by_human != null && (
              <span className="chip" data-testid="placed-by-human">
                Placed by a human after the system abstained: <strong className="mono">{d.placed_by_human}</strong>
                {" "}of <span className="mono">{d.total}</span> studies
              </span>
            )}
          </div>
          <p className="note">{d.basis}.</p>
          <table className="admin" data-testid="lane-mix">
            <thead><tr><th>Lane</th><th>Studies</th><th>Share</th><th className="barcol" aria-hidden="true" /></tr></thead>
            <tbody>
              {d.lanes.map((l) => (
                <tr key={l.lane} className={`lane-${l.lane}`}>
                  <td className="lanetag">{laneName(l.lane, l.label)}</td>
                  <td className="mono num">{l.count}</td>
                  <td className="mono num">{l.percent == null ? "--" : `${l.percent}%`}</td>
                  <td className="barcol" aria-hidden="true"><span className="bar" style={{ width: `${l.percent || 0}%` }} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </Loaded>
  );
}

// Units of the brain anchors, as adapters/brats.py reads them.
const ANCHOR_UNITS = { enhancing_tumor: "cm3", edema_volume: "cm3", tumor_burden: "fraction of brain volume" };

export function Thresholds({ load }) {
  const state = useLoad(load);
  return (
    <Loaded state={state} what="the thresholds">
      {(d) => (
        <>
          <section className="panel">
            <div className="card-head">
              <h2 className="card-title">Lanes by acuity</h2>
              <span className="chip chip-quiet">Read only: a change re-lanes every study</span>
            </div>
            <table className="admin" data-testid="lane-floors">
              <thead><tr><th>Lane</th><th>Acuity at least</th><th>Clock</th></tr></thead>
              <tbody>
                {d.lanes.map((l) => (
                  <tr key={l.lane} className={`lane-${l.lane}`}>
                    <td className="lanetag">{laneName(l.lane)}</td><td className="mono num">{l.acuity_floor}</td><td>{l.clock}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
          <section className="panel">
            <h2 className="card-title">Abstention</h2>
            <p data-testid="abstain-band">
              If the driving finding's signal is between <span className="mono">{d.abstain_band[0]}</span> and{" "}
              <span className="mono">{d.abstain_band[1]}</span>, no lane is assigned and a radiologist places the study.
            </p>
          </section>
          <section className="panel">
            <h2 className="card-title">Operating points per model</h2>
            {d.models.map((m) => (
              <div key={m.id} className="opoints">
                <h3 className="mono-id">{m.id}</h3>
                {m.z_anchor && (
                  <p>Each finding is scored against its own reference distribution ({m.reference}). Signal is 0 at
                    z = <span className="mono">{m.z_anchor[0]}</span> and 1 at z = <span className="mono">{m.z_anchor[1]}</span>.</p>
                )}
                {m.anchors && (
                  <table className="admin">
                    <thead><tr><th>Finding</th><th>Signal 0 at</th><th>Signal 1 at</th><th>Unit</th></tr></thead>
                    <tbody>
                      {Object.entries(m.anchors).map(([k, [lo, hi]]) => (
                        <tr key={k}><td className="mono-id">{k}</td><td className="mono num">{lo}</td><td className="mono num">{hi}</td><td>{ANCHOR_UNITS[k] || ""}</td></tr>
                      ))}
                    </tbody>
                  </table>
                )}
                {m.anchors && Object.keys(m.urgency).filter((k) => !(k in m.anchors)).map((k) => (
                  <p key={k}><span className="mono-id">{k}</span> has no anchor of its own: {m.adapter} derives it from the anchored findings.</p>
                ))}
                {m.mask_check && (
                  <>
                    <p>Segmentation check, run before scoring. Failing any row sends the study to a radiologist as not automatically verified.</p>
                    <table className="admin" data-testid="mask-check">
                      <thead><tr><th>Criterion</th><th>Must be</th></tr></thead>
                      <tbody>
                        <tr><td>Share of predicted tumour inside the brain</td><td className="mono num">at least {m.mask_check.inside_brain_min}</td></tr>
                        <tr><td>Predicted edema on FLAIR, z against the rest of the brain</td><td className="mono num">above {m.mask_check.flair_edema_z_min}</td></tr>
                        <tr><td>Predicted enhancing tumour on T1c, z against the rest of the brain</td><td className="mono num">above {m.mask_check.t1c_et_z_min}</td></tr>
                        <tr><td>Largest connected piece, share of the whole tumour</td><td className="mono num">at least {m.mask_check.largest_component_min}</td></tr>
                      </tbody>
                    </table>
                    <p className="note">The largest-piece criterion is expected to misfire on multifocal disease; it abstains rather than ranks.</p>
                  </>
                )}
                {m.min_tumor_ml != null && (
                  <p>Whole tumour below <span className="mono">{m.min_tumor_ml}</span> ml abstains: the model was trained only on scans with tumours.</p>
                )}
              </div>
            ))}
          </section>
        </>
      )}
    </Loaded>
  );
}

export function Registry({ load }) {
  const state = useLoad(load);
  return (
    <Loaded state={state} what="the model registry">
      {(d) => (
        <div className="cards-grid">
          {d.models.map((m) => (
            <section key={m.id} className="panel model" data-testid="model">
              <h2 className="mono-id">{m.id}</h2>
              <dl>
                <dt>Modality</dt><dd>{m.modality} {m.body_part}</dd>
                <dt>Read by</dt><dd>{m.reading_pool} reading pool</dd>
                <dt>Runs on</dt><dd className="mono-id">{m.runtime}</dd>
                <dt>Input</dt><dd className="mono-id">{m.input.format}, {m.input.dims}D{m.input.channels ? `, ${m.input.channels.join(" ")}` : ""}</dd>
                <dt>Output</dt><dd className="mono-id">{m.output_type}</dd>
                <dt>Adapter</dt><dd className="mono-id">{m.adapter}</dd>
              </dl>
              <table className="admin">
                <thead><tr><th>Finding</th><th>Urgency weight</th></tr></thead>
                <tbody>
                  {Object.entries(m.urgency).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
                    <tr key={k}><td>{k}</td><td className="mono num">{v.toFixed(2)}</td></tr>
                  ))}
                </tbody>
              </table>
            </section>
          ))}
        </div>
      )}
    </Loaded>
  );
}

// Simulated intake: real studies from the API host's own corpus, ingested
// through the full pipeline in a shuffled arrival order. Every lane shown is a
// pipeline result; the only simulated thing is the order.
const INTAKE_COUNT = 30;

export function Intake({ load, start }) {
  const [state, setState] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    let timer;
    const poll = () => load().then((d) => {
      if (!live) return;
      setState(d);
      setError(null);
      if (d.running) timer = setTimeout(poll, 3000);
    }, (e) => live && setError(e));
    poll();
    return () => { live = false; clearTimeout(timer); };
  }, [load, busy]);

  async function onStart() {
    setBusy(true);
    try {
      setState(await start(INTAKE_COUNT));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  if (error && !state) return <p className="error" role="alert">Could not load the intake: {String(error.message)}</p>;
  if (!state) return <p className="note">Loading the intake.</p>;
  const c = state.catalogue || {};
  const items = state.items || [];
  return (
    <section className="panel" data-testid="intake">
      <div className="card-head">
        <button type="button" className="pill pill-primary" onClick={onStart} disabled={!state.available || state.running || busy}
                data-testid="intake-start">
          {state.running ? "Intake running" : `Ingest ${INTAKE_COUNT} studies`}
        </button>
      </div>
      <p className="meta">
        Corpus on this host: {c.CR ?? 0} chest, {c.MR ?? 0} brain MR, {c.CT ?? 0} head CT. Runtime: <span className="mono-id">{state.runtime}</span>.
        {" "}Lanes come from the models; only the arrival order is simulated.
      </p>
      {!state.available && <p className="error" data-testid="intake-unavailable">Not available on this API: {state.reason}.</p>}
      {error && <p className="error" role="alert">{String(error.message)}</p>}
      {state.total != null && (
        <>
          <p className="chip chip-quiet" data-testid="intake-progress">
            {state.running ? "Running" : "Finished"}: {state.done} scored, {state.failed} failed, of {state.total}
            {state.by ? `; started by ${state.by} at ${timeUTC(state.started_at)} UTC` : ""}.
          </p>
          <table className="admin">
            <thead><tr><th>#</th><th>Modality</th><th>Source</th><th>Status</th><th>Lane</th><th className="num">s</th></tr></thead>
            <tbody>
              {items.map((it, i) => (
                <tr key={i} className={it.lane ? `lane-${it.lane}` : ""}>
                  <td className="mono num">{i + 1}</td>
                  <td>{it.modality}</td>
                  <td className="mono-id detail">{it.source}</td>
                  <td>{it.status}{it.error ? `: ${it.error}` : ""}</td>
                  <td className="lanetag">{it.lane ? laneName(it.lane) : "--"}</td>
                  <td className="mono num">{it.seconds ?? "--"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}

// Access requests, for the super admin only. Approving confirms the account
// and puts it in the requested group; rejecting deletes it. Both are audited.
export function AccessRequests({ load, decide }) {
  const [state, setState] = useState({ data: null, error: null });
  const [busy, setBusy] = useState(null);
  const refresh = () => load().then((data) => setState({ data, error: null }),
                                    (error) => setState({ data: null, error }));
  useEffect(() => { refresh(); }, [load]);

  async function onDecide(username, decision) {
    setBusy(username);
    try {
      await decide(username, decision);
      await refresh();
    } catch (error) {
      setState((s) => ({ ...s, error }));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Loaded state={state} what="access requests">
      {(d) => (
        <section className="panel">
          <table className="admin" data-testid="access-requests">
            <thead><tr><th>Requested (UTC)</th><th>Username</th><th>Email</th><th>Role</th><th>Status</th><th /></tr></thead>
            <tbody>
              {d.requests.map((r) => (
                <tr key={r.username}>
                  <td className="mono">{r.requested_at?.slice(0, 10)} {timeUTC(r.requested_at)}</td>
                  <td className="mono-id">{r.username}</td>
                  <td className="mono-id">{r.email}</td>
                  <td>{r.role}</td>
                  <td>{r.status}{r.decided_by ? ` by ${r.decided_by}` : ""}</td>
                  <td>
                    {r.status === "pending" && (
                      <span className="row-actions">
                        <button type="button" className="pill pill-sm pill-primary" disabled={busy === r.username}
                                onClick={() => onDecide(r.username, "approve")}>Approve</button>
                        <button type="button" className="pill pill-sm" disabled={busy === r.username}
                                onClick={() => onDecide(r.username, "reject")}>Reject</button>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {d.requests.length === 0 && <p className="empty-line">No access requests</p>}
        </section>
      )}
    </Loaded>
  );
}

const TABS = [["pipeline", "Pipeline"], ["assignments", "Assignments"], ["audit", "Audit log"],
              ["lanes", "Lane mix"], ["thresholds", "Thresholds"], ["models", "Model registry"],
              ["intake", "Simulated intake"]];

// The top bar (Shell.jsx) lists these, grouped; the routes below are unchanged.
export const ADMIN_TABS = TABS;
export const ADMIN_GROUPS = [
  { label: "Operations", tabs: TABS.filter(([p]) => ["pipeline", "assignments", "audit", "intake"].includes(p)) },
  { label: "Model", tabs: TABS.filter(([p]) => ["lanes", "thresholds", "models"].includes(p)) },
  { label: "Access", tabs: [["access", "Waitlist"]] },
];

export default function Admin({ loadAudit, loadLaneMix, loadModels, loadIntake, startIntake,
                                superadmin = false, loadAccess, decideAccess,
                                loadPipeline, loadPipelineStudy, loadAssignments, reassign }) {
  const { pathname } = useLocation();
  const title = TABS.concat([["access", "Waitlist"]]).find(([p]) => pathname.startsWith(`/admin/${p}`))?.[1] || "Cloud console";
  useEffect(() => { document.title = `${title} · AURALane`; }, [title]);
  return (
    <main className="page adminpage">
      <header className="page-head"><h1 className="page-title">{title}</h1></header>
      <Routes>
        <Route index element={<Navigate to="/admin/pipeline" replace />} />
        <Route path="pipeline" element={loadPipeline
          ? <Pipeline load={loadPipeline} loadStudy={loadPipelineStudy} /> : <Navigate to="/admin/audit" replace />} />
        <Route path="assignments" element={loadAssignments
          ? <Assignments load={loadAssignments} reassign={reassign} /> : <Navigate to="/admin/audit" replace />} />
        <Route path="audit" element={<Audit load={loadAudit} />} />
        <Route path="lanes" element={<LaneMix load={loadLaneMix} />} />
        <Route path="thresholds" element={<Thresholds load={loadModels} />} />
        <Route path="models" element={<Registry load={loadModels} />} />
        <Route path="intake" element={<Intake load={loadIntake} start={startIntake} />} />
        {superadmin && <Route path="access" element={<AccessRequests load={loadAccess} decide={decideAccess} />} />}
        <Route path="*" element={<Navigate to="/admin/pipeline" replace />} />
      </Routes>
    </main>
  );
}
