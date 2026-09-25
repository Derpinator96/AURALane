import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { timeUTC } from "./worklist.js";

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
  if (!state.data) return <p>Loading {what}.</p>;
  return children(state.data);
}

const detailText = (d) =>
  Object.entries(d || {}).map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`).join("  ");

export function Audit({ load }) {
  const state = useLoad(load);
  return (
    <Loaded state={state} what="the audit log">
      {(d) => (
        <>
          <p className="note">Append only: the table refuses updates and deletes. Newest first; showing {d.events.length} of {d.total}.</p>
          <table className="admin" data-testid="audit">
            <thead><tr><th>Time (UTC)</th><th>Actor</th><th>Action</th><th>Study</th><th>Outcome</th><th>ms</th><th>Detail</th></tr></thead>
            <tbody>
              {d.events.map((e) => (
                <tr key={e.event_id}>
                  <td className="mono">{e.at?.slice(0, 10)} {timeUTC(e.at)}</td>
                  <td className="mono">{e.actor}</td>
                  <td>{e.action}</td>
                  <td className="mono">{e.study}</td>
                  <td>{e.outcome}</td>
                  <td className="mono num">{e.duration_ms}</td>
                  <td className="mono detail">{detailText(e.detail)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {d.events.length === 0 && <p>No audit events yet.</p>}
        </>
      )}
    </Loaded>
  );
}

export function LaneMix({ load }) {
  const state = useLoad(load);
  return (
    <Loaded state={state} what="the lane mix">
      {(d) => (
        <>
          <p className="note">{d.basis}.</p>
          <table className="admin" data-testid="lane-mix">
            <thead><tr><th>Lane</th><th>Studies</th><th>Share</th><th className="barcol" aria-hidden="true" /></tr></thead>
            <tbody>
              {d.lanes.map((l) => (
                <tr key={l.lane} className={`lane-${l.lane}`}>
                  <td className="lanetag">{l.label}</td>
                  <td className="mono num">{l.count}</td>
                  <td className="mono num">{l.percent == null ? "--" : `${l.percent}%`}</td>
                  <td className="barcol" aria-hidden="true"><span className="bar" style={{ width: `${l.percent || 0}%` }} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
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
          <p className="note">
            Read only. Lane floors and the abstention band are set in triage.py, operating points in
            models/registry.json. Changing one re-lanes every study, so it is a reviewed code change,
            not a setting.
          </p>
          <h2>Lanes by acuity</h2>
          <table className="admin" data-testid="lane-floors">
            <thead><tr><th>Lane</th><th>Acuity at least</th><th>Clock</th></tr></thead>
            <tbody>
              {d.lanes.map((l) => (
                <tr key={l.lane} className={`lane-${l.lane}`}>
                  <td className="lanetag">{l.lane}</td><td className="mono num">{l.acuity_floor}</td><td>{l.clock}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h2>Abstention</h2>
          <p data-testid="abstain-band">
            If the driving finding's signal is between <span className="mono">{d.abstain_band[0]}</span> and{" "}
            <span className="mono">{d.abstain_band[1]}</span>, no lane is assigned and a radiologist places the study.
          </p>
          <h2>Operating points per model</h2>
          {d.models.map((m) => (
            <div key={m.id} className="opoints">
              <h3 className="mono">{m.id}</h3>
              {m.z_anchor && (
                <p>Each finding is scored against its own reference distribution ({m.reference}). Signal is 0 at
                  z = <span className="mono">{m.z_anchor[0]}</span> and 1 at z = <span className="mono">{m.z_anchor[1]}</span>.</p>
              )}
              {m.anchors && (
                <table className="admin">
                  <thead><tr><th>Finding</th><th>Signal 0 at</th><th>Signal 1 at</th><th>Unit</th></tr></thead>
                  <tbody>
                    {Object.entries(m.anchors).map(([k, [lo, hi]]) => (
                      <tr key={k}><td className="mono">{k}</td><td className="mono num">{lo}</td><td className="mono num">{hi}</td><td>{ANCHOR_UNITS[k] || ""}</td></tr>
                    ))}
                  </tbody>
                </table>
              )}
              {m.anchors && Object.keys(m.urgency).filter((k) => !(k in m.anchors)).map((k) => (
                <p key={k}><span className="mono">{k}</span> has no anchor of its own: {m.adapter} derives it from the anchored findings.</p>
              ))}
              {m.min_tumor_ml != null && (
                <p>Whole tumour below <span className="mono">{m.min_tumor_ml}</span> ml abstains: the model was trained only on scans with tumours.</p>
              )}
            </div>
          ))}
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
        <>
          <p className="note">From models/registry.json, validated at startup. Adding a model is an entry and an adapter; triage does not change.</p>
          {d.models.map((m) => (
            <div key={m.id} className="model" data-testid="model">
              <h2 className="mono">{m.id}</h2>
              <dl>
                <dt>Modality</dt><dd>{m.modality} {m.body_part}</dd>
                <dt>Read by</dt><dd>{m.reading_pool} reading pool</dd>
                <dt>Runs on</dt><dd className="mono">{m.runtime}</dd>
                <dt>Input</dt><dd className="mono">{m.input.format}, {m.input.dims}D{m.input.channels ? `, ${m.input.channels.join(" ")}` : ""}</dd>
                <dt>Output</dt><dd className="mono">{m.output_type}</dd>
                <dt>Adapter</dt><dd className="mono">{m.adapter}</dd>
              </dl>
              <table className="admin">
                <thead><tr><th>Finding</th><th>Urgency weight</th></tr></thead>
                <tbody>
                  {Object.entries(m.urgency).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
                    <tr key={k}><td>{k}</td><td className="mono num">{v.toFixed(2)}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </>
      )}
    </Loaded>
  );
}

const TABS = [["audit", "Audit log"], ["lanes", "Lane mix"], ["thresholds", "Thresholds"], ["models", "Model registry"]];

export default function Admin({ loadAudit, loadLaneMix, loadModels }) {
  return (
    <main className="adminpage">
      <nav className="tabs" aria-label="Admin">
        {TABS.map(([path, label]) => <NavLink key={path} to={`/admin/${path}`}>{label}</NavLink>)}
      </nav>
      <p className="note">Admins configure and audit the system. Studies are opened by radiologists only.</p>
      <Routes>
        <Route index element={<Navigate to="audit" replace />} />
        <Route path="audit" element={<Audit load={loadAudit} />} />
        <Route path="lanes" element={<LaneMix load={loadLaneMix} />} />
        <Route path="thresholds" element={<Thresholds load={loadModels} />} />
        <Route path="models" element={<Registry load={loadModels} />} />
        <Route path="*" element={<Navigate to="audit" replace />} />
      </Routes>
    </main>
  );
}
