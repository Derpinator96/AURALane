import { useCallback, useEffect, useMemo, useState } from "react";
import { arrangePools, READ_FILTERS, SORTS, timeUTC, isUnread } from "./worklist.js";
import Sidebar from "./components/Sidebar.jsx";
import LatestCasePanel from "./components/LatestCasePanel.jsx";
import PatientHistoryView from "./components/PatientHistoryView.jsx";
import ReportsView from "./components/ReportsView.jsx";
import SettingsView from "./components/SettingsView.jsx";
import SimulatePanel from "./components/SimulatePanel.jsx";
import DistributePanel from "./components/DistributePanel.jsx";
import { SearchIcon } from "./components/Icons.jsx";
import { loadSettings } from "./settings.js";

const LANE_FILTERS = ["ALL", "CRITICAL", "URGENT", "EXPEDITED", "ROUTINE"];

function Acuity({ row }) {
  // Copied from the API. Abstained and failed studies have no lane, so no
  // acuity is shown for them, as in the round-2 queue.
  if (row.lane === "ABSTAIN" || row.lane === "FAILED" || row.acuity == null) return "--";
  return Number(row.acuity).toFixed(1);
}

function Row({ row, selected, onSelect, me }) {
  const verdict = row.verdict ? (row.verdict.value === "agree" ? "Agreed" : "Disagreed") : "Unread";
  const who = row.assigned_to ? (row.assigned_to === me ? "You" : row.assigned_name || row.assigned_to) : "Unassigned";
  return (
    <div className={`study-row lane-${row.lane} ${selected ? "selected" : ""} ${row.overdue ? "overdue" : ""}`}
         onClick={() => onSelect(row.study)} data-testid="study-row" data-study={row.study}
         role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && onSelect(row.study)}>
      <div className="cell-lane">
        <span className={`lanetag lane-${row.lane}`}>{row.lane_label || row.lane}</span>
      </div>
      <div className="cell-patient mono bold">{row.patient_id || row.study}</div>
      <div className="cell-modality"><span className={`mod-badge mod-${row.modality}`}>{row.exam || row.modality}</span></div>
      <div className="cell-finding">
        <span className="finding-text" title={row.driver_label || row.abstain_reason || "--"}>
          {row.lane === "FAILED" ? row.error : row.driver_label || row.abstain_reason || "--"}
        </span>
      </div>
      <div className="cell-acuity mono acuity"><Acuity row={row} /></div>
      <div className="cell-assigned" data-testid="assigned">
        {who}{row.overdue && <span className="overdue-tag" title="Critical, not opened within its lane clock"> not opened</span>}
      </div>
      <div className="cell-status"><span className={`verdict-pill ${isUnread(row) ? "unread" : "reviewed"}`}>{verdict}</span></div>
      <div className="cell-time mono">{timeUTC(row.arrived)}</div>
    </div>
  );
}

function Section({ s, pool, children }) {
  return (
    <section className={`lane-group lane-${s.lane}`} data-testid={`section-${pool}-${s.lane}`}>
      <h3 className="lane-heading">
        <span className="lanename">{s.label}</span>
        {s.clock && <span className="clock">{s.clock}</span>}
        <span className="mono count">({s.rows.length})</span>
      </h3>
      {s.lane === "ABSTAIN" && (
        <p className="why">Model confidence was not sufficient to assign a lane. A radiologist picks it.</p>
      )}
      {s.lane === "FAILED" && (
        <p className="why">Processing did not complete. The study is still in PACS; read it there.</p>
      )}
      {children}
    </section>
  );
}

export default function Worklist({ load, token }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [sort, setSort] = useState("priority");
  const [lane, setLane] = useState("ALL");
  const [read, setRead] = useState("all");
  const [chosenScope, setScope] = useState(null);     // "mine" | "department"
  const [searchQuery, setSearchQuery] = useState("");
  const [activeNav, setActiveNav] = useState("worklist");
  const [modality, setModality] = useState("ALL");
  const [selectedStudyId, setSelectedStudyId] = useState(null);
  const [panel, setPanel] = useState(null);           // "simulate" | "distribute"
  const [refresh, setRefresh] = useState(() => loadSettings().refreshSeconds);

  const fetchWorklist = useCallback(() => {
    load().then((d) => setData(d)).catch((e) => setError(e));
  }, [load]);

  useEffect(() => { fetchWorklist(); }, [fetchWorklist]);

  useEffect(() => {
    if (!refresh) return undefined;
    const t = setInterval(fetchWorklist, refresh * 1000);
    return () => clearInterval(t);
  }, [fetchWorklist, refresh]);

  // Mine by default when the API says who this is; the department queue otherwise.
  const scope = chosenScope ?? (data?.me ? "mine" : "department");

  const handleVerdictUpdate = (studyId, updated) => {
    setData((prev) => prev && { ...prev, studies: prev.studies.map((s) => (s.study === studyId ? { ...s, ...updated } : s)) });
  };

  const visible = useMemo(() => {
    if (!data?.studies) return [];
    let list = data.studies;
    if (scope === "mine" && data.me) list = list.filter((s) => s.assigned_to === data.me);
    if (modality !== "ALL") list = list.filter((s) => s.modality === modality || (modality === "CR" && s.modality === "DX"));
    if (activeNav === "recent") list = list.filter((s) => !isUnread(s));
    const q = searchQuery.toLowerCase().trim();
    if (q) {
      list = list.filter((s) => [s.patient_id, s.study, s.exam, s.driver_label, s.assigned_name]
        .some((v) => v && String(v).toLowerCase().includes(q)));
    }
    return list;
  }, [data, scope, modality, activeNav, searchQuery]);

  const pools = useMemo(
    () => (data ? arrangePools(visible, data.pools, data.lanes, { sort, lane, read }) : []),
    [data, visible, sort, lane, read]);

  // The head of the queue: the first row in priority order, which is what
  // reordering means. Not a flag: it is simply next.
  const next = useMemo(() => visible.find((s) => isUnread(s)) || null, [visible]);

  const counts = useMemo(() => ({
    total: visible.length,
    recent: visible.filter((s) => !isUnread(s)).length,
  }), [visible]);

  if (error) {
    return <main className="workstation-error"><p className="error" role="alert">Could not load the worklist: {String(error.message)}</p></main>;
  }
  if (!data) return <main className="workstation-loading"><p>Loading worklist.</p></main>;

  const readers = data.readers || [];
  const mineCount = data.me ? data.studies.filter((s) => s.assigned_to === data.me).length : 0;

  return (
    <div className="workstation-layout" data-testid="workstation-layout">
      {panel === "simulate" && (
        <SimulatePanel token={token} readers={readers} onClose={() => setPanel(null)} onProgress={fetchWorklist} />
      )}
      {panel === "distribute" && (
        <DistributePanel token={token} readers={readers} studies={data.studies}
                         onClose={() => setPanel(null)} onDone={fetchWorklist} />
      )}

      <Sidebar activeNav={activeNav} onNavChange={setActiveNav} specialtyFilter={modality}
               onSpecialtyChange={setModality} counts={counts} />

      <main className="workstation-center" data-testid="workstation-center">
        {activeNav === "history" && (
          <PatientHistoryView studies={visible} onSelectStudy={setSelectedStudyId} selectedStudyId={selectedStudyId} />
        )}
        {activeNav === "reports" && <ReportsView token={token} studies={data.studies} me={data.me} />}
        {activeNav === "settings" && <SettingsView onChange={(s) => setRefresh(s.refreshSeconds)} />}

        {(activeNav === "worklist" || activeNav === "recent") && (
          <>
            <div className="center-header">
              <div>
                <h2 className="center-title">{activeNav === "recent" ? "Read studies" : "Worklist"}</h2>
                <p className="center-subtitle">In priority order within each reading pool. Critical first.</p>
              </div>
              <div className="center-action-buttons">
                <button type="button" className="btn-action-primary" onClick={() => setPanel("simulate")}
                        data-testid="btn-simulate">Simulate ingest</button>
                <button type="button" className="btn-action-quick" onClick={() => setPanel("distribute")}
                        disabled={readers.length === 0} data-testid="btn-distribute">Distribute worklist</button>
              </div>
            </div>

            <div className="worklist-filter-bar">
              {data.me && (
                <div className="scope-toggle" role="group" aria-label="Whose studies">
                  <button type="button" aria-pressed={scope === "mine"} onClick={() => setScope("mine")}
                          data-testid="scope-mine">Mine ({mineCount})</button>
                  <button type="button" aria-pressed={scope === "department"} onClick={() => setScope("department")}
                          data-testid="scope-department">Department ({data.studies.length})</button>
                </div>
              )}
              <div className="search-box">
                <span className="search-icon"><SearchIcon size={14} /></span>
                <input type="text" placeholder="Search patient, study, finding, reader" value={searchQuery}
                       onChange={(e) => setSearchQuery(e.target.value)} className="search-input" aria-label="Search" />
                {searchQuery && <button type="button" className="search-clear" onClick={() => setSearchQuery("")}>Clear</button>}
              </div>
              <div className="filter-dropdowns">
                <label className="filter-item"><span>Lane</span>
                  <select value={lane} onChange={(e) => setLane(e.target.value)} aria-label="Lane filter">
                    {LANE_FILTERS.map((l) => <option key={l} value={l}>{l === "ALL" ? "All lanes" : l}</option>)}
                  </select>
                </label>
                <label className="filter-item"><span>Status</span>
                  <select value={read} onChange={(e) => setRead(e.target.value)} aria-label="Read filter">
                    {Object.entries(READ_FILTERS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </label>
                <label className="filter-item"><span>Sort</span>
                  <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort">
                    {Object.entries(SORTS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </label>
              </div>
            </div>
            <p className="note">
              Grouped by reading pool because a neuroradiologist reads the MRI and a chest radiologist reads the X-ray;
              studies are ranked within a pool, never across. Needs human triage is always shown and is not affected by filters.
            </p>

            {scope === "mine" && mineCount === 0 && (
              <p className="note" data-testid="mine-empty">
                Nothing is assigned to you.{" "}
                <button type="button" className="linklike" onClick={() => setScope("department")}>Show the department queue</button>
              </p>
            )}

            {next && activeNav === "worklist" && (
              <section className="hero-case-card" data-testid="hero-study-card">
                <div className="hero-badge-strip">
                  <span className="hero-alert-badge">NEXT TO READ</span>
                  <span className={`lanetag lane-${next.lane}`}>{next.lane_label || next.lane}</span>
                  {next.clock && <span className="hero-clock">{next.clock}</span>}
                </div>
                <div className="hero-content-grid">
                  <div className="hero-main-info">
                    <div className="hero-patient-id mono">{next.patient_id || next.study}</div>
                    <div className="hero-exam-name">{next.exam}</div>
                    <div className="hero-driver"><span className="driver-label-text">Driving finding:</span>{" "}
                      <span className="bold highlight-driver">{next.driver_label || next.abstain_reason || "--"}</span></div>
                  </div>
                  <div className="hero-metrics">
                    <div className="metric-box"><span className="box-title">Acuity</span>
                      <span className="box-val mono bold"><Acuity row={next} /></span></div>
                  </div>
                  <div className="hero-action-col">
                    <button type="button" className="btn-hero-inspect" onClick={() => setSelectedStudyId(next.study)}>Select</button>
                    <span className="hero-time mono">Arrived {timeUTC(next.arrived)} UTC</span>
                  </div>
                </div>
              </section>
            )}

            <div className="queue-container">
              <div className="queue-colhead" aria-hidden="true">
                <span>Lane</span><span>Patient (pseudonym)</span><span>Exam</span><span>Driving finding</span>
                <span>Acuity</span><span>Reader</span><span>Status</span><span>Arrived UTC</span>
              </div>
              {pools.map((p) => (
                <section key={p.pool} className="pool-group" data-testid={`pool-${p.pool}`} aria-label={`${p.label} reading pool`}>
                  <div className="pool-header">
                    <h2 className="pool-title">{p.label}</h2>
                    <span className="pool-badge">{p.sections.reduce((a, s) => a + s.rows.length, 0)} studies</span>
                  </div>
                  {p.sections.map((s) => (
                    <Section key={s.lane} s={s} pool={p.pool}>
                      {s.rows.map((row) => (
                        <Row key={row.study} row={row} me={data.me} selected={row.study === selectedStudyId}
                             onSelect={setSelectedStudyId} />
                      ))}
                    </Section>
                  ))}
                </section>
              ))}
            </div>
          </>
        )}
      </main>

      <aside className="workstation-details-panel" data-testid="workstation-details-panel">
        <LatestCasePanel studyId={selectedStudyId} token={token} onVerdictChange={handleVerdictUpdate} />
      </aside>
    </div>
  );
}
