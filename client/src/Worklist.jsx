import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { arrangePools, READ_FILTERS, SORTS, timeUTC, isUnread } from "./worklist.js";
import Sidebar from "./components/Sidebar.jsx";
import LatestCasePanel from "./components/LatestCasePanel.jsx";
import PatientHistoryView from "./components/PatientHistoryView.jsx";
import ReportsView from "./components/ReportsView.jsx";
import SettingsView from "./components/SettingsView.jsx";
import SimulatePanel from "./components/SimulatePanel.jsx";
import DistributePanel from "./components/DistributePanel.jsx";
import { BoardIcon, ClockIcon, ListIcon, SearchIcon, UserIcon, WorklistIcon } from "./components/Icons.jsx";
import { Slot } from "./Shell.jsx";
import { loadSettings } from "./settings.js";

const LANE_FILTERS = ["ALL", "CRITICAL", "URGENT", "EXPEDITED", "ROUTINE"];
const VIEW_KEY = "auralane.worklistView";

function loadView() {
  try {
    return localStorage.getItem(VIEW_KEY) === "board" ? "board" : "list";
  } catch {
    return "list";
  }
}

function Acuity({ row }) {
  if (row.lane === "ABSTAIN" || row.lane === "FAILED" || row.acuity == null) return "--";
  return Number(row.acuity).toFixed(1);
}

export default function Worklist({ load, token }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [sort, setSort] = useState("priority");
  const [lane, setLane] = useState("ALL");
  const [read, setRead] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [activeNav, setActiveNav] = useState("worklist");
  const [specialtyFilter, setSpecialtyFilter] = useState("ALL");
  const [selectedStudyId, setSelectedStudyId] = useState(null);
  const [panel, setPanel] = useState(null);             // "simulate" | "distribute"
  const [chosenScope, setScope] = useState(null);       // "mine" | "all"
  const [detailsWidth, setDetailsWidth] = useState(580);
  const [refresh, setRefresh] = useState(() => loadSettings().refreshSeconds);
  const [view, setViewState] = useState(loadView);        // "list" | "board"
  const setView = (v) => {
    setViewState(v);
    try {
      localStorage.setItem(VIEW_KEY, v);
    } catch {
      // Storage unavailable: the choice lasts until reload.
    }
  };

  const startResize = (e) => {
    e.preventDefault();
    const startX = e.clientX;
    const startWidth = detailsWidth;
    const onMouseMove = (moveEvent) => {
      const delta = startX - moveEvent.clientX;
      setDetailsWidth(Math.max(350, Math.min(1000, startWidth + delta)));
    };
    const onMouseUp = () => {
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
      document.body.style.cursor = "default";
    };
    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
    document.body.style.cursor = "col-resize";
  };

  // A failed refresh (the API restarting, a dropped connection) keeps the list on
  // screen and says so; the next refresh clears it. Only a failed first load
  // shows the error, and that retries every few seconds.
  const [stale, setStale] = useState(false);
  const loaded = useRef(false);
  const fetchWorklist = useCallback(() => {
    load().then((d) => { loaded.current = true; setData(d); setError(null); setStale(false); })
      .catch((e) => { if (loaded.current) setStale(true); else setError(e); });
  }, [load]);

  useEffect(() => { fetchWorklist(); }, [fetchWorklist]);

  useEffect(() => {
    if (!refresh && !error) return undefined;
    const t = setInterval(fetchWorklist, (error ? 5 : refresh) * 1000);
    return () => clearInterval(t);
  }, [fetchWorklist, refresh, error]);

  const mine = useMemo(() => (data?.me ? (data.studies || []).filter((s) => s.assigned_to === data.me) : []),
    [data]);
  // My studies when something is assigned to me; otherwise the whole queue.
  const scope = chosenScope ?? (mine.length ? "mine" : "all");

  // Default selection: the highest-priority study in view, once.
  useEffect(() => {
    if (selectedStudyId || !data?.studies?.length) return;
    const list = scope === "mine" && mine.length ? mine : data.studies;
    const top = list.find((s) => s.lane === "CRITICAL") || list[0];
    if (top) setSelectedStudyId(top.study);
  }, [data, scope, mine, selectedStudyId]);

  const handleVerdictUpdate = (studyId, updatedStudy) => {
    setData((prev) => prev && {
      ...prev, studies: prev.studies.map((s) => (s.study === studyId ? { ...s, ...updatedStudy } : s)),
    });
  };

  const filteredStudies = useMemo(() => {
    if (!data || !data.studies) return [];
    let list = scope === "mine" ? mine : data.studies;
    if (specialtyFilter === "MR") list = list.filter((s) => s.modality === "MR");
    else if (specialtyFilter === "CR") list = list.filter((s) => s.modality === "CR" || s.modality === "DX");
    else if (specialtyFilter === "CT") list = list.filter((s) => s.modality === "CT");
    if (activeNav === "recent") list = list.filter((s) => !isUnread(s));
    const q = searchQuery.toLowerCase().trim();
    if (q) {
      list = list.filter((s) => [s.patient_id, s.study, s.exam, s.driver, s.driver_label, s.assigned_name]
        .some((v) => v && String(v).toLowerCase().includes(q)));
    }
    return list;
  }, [data, scope, mine, specialtyFilter, activeNav, searchQuery]);

  const pools = useMemo(
    () => (data ? arrangePools(filteredStudies, data.pools, data.lanes, { sort, lane, read }) : []),
    [data, filteredStudies, sort, lane, read]);

  const heroStudy = useMemo(() => {
    const unread = filteredStudies.filter((s) => isUnread(s));
    return unread.find((s) => s.lane === "CRITICAL") || unread[0] || null;
  }, [filteredStudies]);

  const counts = useMemo(() => ({
    total: filteredStudies.length,
    recent: filteredStudies.filter((s) => !isUnread(s)).length,
  }), [filteredStudies]);

  if (error) {
    return (
      <main className="workstation-error">
        <p className="error" role="alert">Could not load the worklist: {String(error.message)}</p>
      </main>
    );
  }
  if (!data) {
    return (
      <main className="workstation-loading">
        <div className="clinical-spinner"></div>
        <p>Loading the worklist.</p>
      </main>
    );
  }

  const readers = data.readers || [];
  const who = (row) => (row.assigned_to
    ? (row.assigned_to === data.me ? "You" : row.assigned_name || row.assigned_to) : "Unassigned");

  return (
    <div className="workstation-layout" data-testid="workstation-layout"
         style={{ gridTemplateColumns: `minmax(0, 1fr) 6px ${detailsWidth}px` }}>
      {panel === "simulate" && (
        <SimulatePanel token={token} readers={readers} onClose={() => setPanel(null)} onProgress={fetchWorklist} />
      )}
      {panel === "distribute" && (
        <DistributePanel token={token} readers={readers} studies={data.studies}
                         onClose={() => setPanel(null)} onDone={fetchWorklist} />
      )}

      <Sidebar activeNav={activeNav} onNavChange={setActiveNav} specialtyFilter={specialtyFilter}
               onSpecialtyChange={setSpecialtyFilter} counts={counts} />

      <main className="workstation-center" data-testid="workstation-center">
        {stale && <p className="note" role="status">Lost contact with the API. Showing the last list; retrying.</p>}
        {activeNav === "history" && (
          <PatientHistoryView studies={filteredStudies} onSelectStudy={setSelectedStudyId}
                              selectedStudyId={selectedStudyId} />
        )}
        {activeNav === "reports" && <ReportsView token={token} studies={data.studies} me={data.me} />}
        {activeNav === "settings" && <SettingsView onChange={(s) => setRefresh(s.refreshSeconds)} />}

        {(activeNav === "worklist" || activeNav === "recent") && (
          <>
            <div className="center-header">
              <div>
                <h2 className="center-title">AI Worklist Queue</h2>
                <p className="center-subtitle">Grouped by reading pool because a neuroradiologist reads the MRI and a chest radiologist reads the X-ray; studies are ranked within a pool, never across.</p>
              </div>
              <Slot name="actions">
                <div className="center-action-buttons">
                  <button type="button" className="btn" onClick={() => setPanel("distribute")}
                          disabled={readers.length === 0} data-testid="btn-distribute">Distribute worklist</button>
                  <button type="button" className="btn btn-primary" onClick={() => setPanel("simulate")}
                          data-testid="btn-simulate">Simulate ingest</button>
                </div>
              </Slot>
            </div>

            <div className="worklist-filter-bar">
              {data.me && (
                <div className="scope-toggle" role="group" aria-label="Whose studies">
                  <button type="button" aria-pressed={scope === "mine"} onClick={() => setScope("mine")}
                          data-testid="scope-mine">My studies ({mine.length})</button>
                  <button type="button" aria-pressed={scope === "all"} onClick={() => setScope("all")}
                          data-testid="scope-department">All studies ({data.studies.length})</button>
                </div>
              )}
              <div className="search-box">
                <span className="search-icon"><SearchIcon size={14} /></span>
                <input type="text" placeholder="Search patient, study ID, finding, reader" value={searchQuery}
                       onChange={(e) => setSearchQuery(e.target.value)} className="search-input" aria-label="Search" />
                {searchQuery && <button type="button" className="search-clear" onClick={() => setSearchQuery("")}>Clear</button>}
              </div>
              <div className="filter-dropdowns">
                <label className="filter-item"><span>Lane:</span>
                  <select value={lane} onChange={(e) => setLane(e.target.value)} aria-label="Lane filter">
                    {LANE_FILTERS.map((l) => <option key={l} value={l}>{l === "ALL" ? "All lanes" : l}</option>)}
                  </select>
                </label>
                <label className="filter-item"><span>Status:</span>
                  <select value={read} onChange={(e) => setRead(e.target.value)} aria-label="Read filter">
                    {Object.entries(READ_FILTERS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </label>
                <label className="filter-item"><span>Sort:</span>
                  <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort">
                    {Object.entries(SORTS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </label>
              </div>
              <div className="view-toggle" role="group" aria-label="Worklist view">
                <button type="button" className="icon-btn" aria-pressed={view === "list"} title="List view"
                        aria-label="List view" onClick={() => setView("list")} data-testid="view-list">
                  <ListIcon size={16} />
                </button>
                <button type="button" className="icon-btn" aria-pressed={view === "board"} title="Board view"
                        aria-label="Board view" onClick={() => setView("board")} data-testid="view-board">
                  <BoardIcon size={16} />
                </button>
              </div>
            </div>

            {scope === "mine" && mine.length === 0 && (
              <p className="note" data-testid="mine-empty">
                Nothing is assigned to you.{" "}
                <button type="button" className="linklike" onClick={() => setScope("all")}>Show all studies</button>
              </p>
            )}

            {heroStudy && activeNav === "worklist" && (
              <section className="hero-case-card" data-testid="hero-study-card">
                <div className="hero-badge-strip">
                  <span className="hero-alert-badge">TOP PRIORITY AI TRIAGE</span>
                  <span className={`lanetag lane-${heroStudy.lane}`}>{heroStudy.lane_label || heroStudy.lane}</span>
                  {heroStudy.clock && <span className="hero-clock">SLA TARGET: {heroStudy.clock}</span>}
                </div>
                <div className="hero-content-grid">
                  <div className="hero-main-info">
                    <div className="hero-patient-id mono">{heroStudy.patient_id || heroStudy.study}</div>
                    <div className="hero-exam-name">{heroStudy.exam}</div>
                    <div className="hero-driver">
                      <span className="driver-label-text">Driving Finding:</span>{" "}
                      <span className="bold highlight-driver">{heroStudy.driver_label || heroStudy.abstain_reason || "--"}</span>
                    </div>
                  </div>
                  <div className="hero-metrics">
                    <div className="metric-box">
                      <span className="box-title">Acuity Score</span>
                      <span className="box-val mono bold"><Acuity row={heroStudy} /></span>
                    </div>
                    <div className="metric-box">
                      <span className="box-title">Confidence</span>
                      <span className="box-val mono">
                        {heroStudy.confidence != null ? `${(heroStudy.confidence * 100).toFixed(0)}%` : "--"}
                      </span>
                    </div>
                  </div>
                  <div className="hero-action-col">
                    <button type="button"
                            className={`btn-hero-inspect ${selectedStudyId === heroStudy.study ? "active-inspect" : ""}`}
                            onClick={() => setSelectedStudyId(heroStudy.study)}>
                      {selectedStudyId === heroStudy.study ? "Active in Viewer" : "Inspect Case Scans"}
                    </button>
                    <span className="hero-time mono">Arrived {timeUTC(heroStudy.arrived)} UTC</span>
                  </div>
                </div>
              </section>
            )}

            <p className="note">
              Needs human triage is always shown and is not affected by filters.
            </p>

            {view === "board" && (
              <div className="board" data-testid="board">
                {(data.lanes || []).map((l) => {
                  const cards = pools.flatMap((p) => p.sections.flatMap((s) => s.rows)).filter((r) => r.lane === l.lane);
                  if (l.pinned && l.lane !== "ABSTAIN" && cards.length === 0) return null;
                  return (
                    <section key={l.lane} className={`board-col lane-${l.lane}`} data-testid={`board-col-${l.lane}`}
                             aria-label={l.label}>
                      <h3 className="board-col-head">
                        <span className="lane-dot" aria-hidden="true" />
                        <span className="lanename">{l.label}</span>
                        <span className="count mono">{cards.length}</span>
                        {l.clock && <span className="clock mono">{l.clock}</span>}
                      </h3>
                      {l.lane === "ABSTAIN" && (
                        <p className="lane-explain-why">Model confidence was not sufficient to assign a lane. A radiologist picks it.</p>
                      )}
                      {cards.map((row) => (
                        <article key={row.study} className={`board-card ${row.study === selectedStudyId ? "selected" : ""}`}
                                 data-testid="board-card" data-study={row.study}>
                          <div className="card-head">
                            <span className="card-title">
                              {row.lane === "FAILED" ? row.error : row.driver_label || row.abstain_reason || "--"}
                            </span>
                            <span className="tag">{row.exam || row.modality}</span>
                          </div>
                          <div className="card-meta"><UserIcon size={14} /><span className="mono">{row.patient_id || row.study}</span></div>
                          <div className="card-meta"><ClockIcon size={14} /><span className="mono">{timeUTC(row.arrived)} UTC</span></div>
                          <div className="card-meta"><WorklistIcon size={14} />
                            <span>Acuity <span className="mono"><Acuity row={row} /></span></span></div>
                          <div className="card-meta"><UserIcon size={14} /><span>{who(row)}</span></div>
                          {row.overdue && l.lane === "CRITICAL" && (
                            <div className="card-alert">Not opened within the {l.clock || "lane"} clock</div>
                          )}
                          <button type="button" className="btn card-open" onClick={() => setSelectedStudyId(row.study)}>
                            Open study
                          </button>
                        </article>
                      ))}
                    </section>
                  );
                })}
              </div>
            )}

            {view === "list" && <div className="queue-container">
              <div className="queue-colhead" aria-hidden="true">
                <span>Lane / SLA</span><span>Patient ID</span><span>Modality</span><span>AI Driving Finding</span>
                <span>Acuity</span><span>Status / Reader</span><span>Arrived</span>
              </div>
              {pools.map((p) => (
                <section key={p.pool} className="pool-group" data-testid={`pool-${p.pool}`} aria-label={`${p.label} reading pool`}>
                  <div className="pool-header">
                    <h2 className="pool-title">{p.label} Reading Pool</h2>
                    <span className="pool-badge">{p.sections.reduce((a, s) => a + s.rows.length, 0)} Studies</span>
                  </div>
                  {p.sections.map((s) => (
                    <section key={s.lane} className={`lane-group lane-${s.lane}`} data-testid={`section-${p.pool}-${s.lane}`}>
                      <h3 className="lane-group-heading">
                        <span className="lanename">{s.label}</span>
                        {s.clock && <span className="clock mono"> • {s.clock}</span>}
                        <span className="mono count"> ({s.rows.length})</span>
                      </h3>
                      {s.lane === "ABSTAIN" && (
                        <p className="lane-explain-why">Model confidence was not sufficient to assign a lane. A radiologist picks it.</p>
                      )}
                      {s.lane === "FAILED" && (
                        <p className="lane-explain-why">Processing did not complete. The study is still in PACS; read it there.</p>
                      )}
                      {s.rows.map((row) => {
                        const isSelected = row.study === selectedStudyId;
                        const verdict = row.verdict ? (row.verdict.value === "agree" ? "Agreed" : "Disagreed") : "Unread";
                        return (
                          <div key={row.study}
                               className={`study-row lane-${row.lane} ${isSelected ? "selected" : ""} ${row.overdue ? "overdue" : ""}`}
                               onClick={() => setSelectedStudyId(row.study)}
                               data-testid="study-row" data-study={row.study}>
                            <div className="cell-lane">
                              <span className={`lanetag lane-${row.lane}`}>{row.lane_label || row.lane}</span>
                              {row.clock && <span className="cell-clock mono">{row.clock}</span>}
                            </div>
                            <div className="cell-patient mono bold">{row.patient_id || row.study}</div>
                            <div className="cell-modality">
                              <span className={`mod-badge mod-${row.modality}`}>{row.exam || row.modality}</span>
                            </div>
                            <div className="cell-finding">
                              <span className="finding-text" title={row.driver_label || row.abstain_reason || "--"}>
                                {row.lane === "FAILED" ? row.error : row.driver_label || row.abstain_reason || "--"}
                              </span>
                            </div>
                            <div className="cell-acuity mono acuity"><Acuity row={row} /></div>
                            <div className="cell-status">
                              <span className={`verdict-pill ${isUnread(row) ? "unread" : "reviewed"}`}>{verdict}</span>
                              <span className="cell-reader" data-testid="assigned">
                                {who(row)}{row.overdue && <strong className="overdue-tag"> not opened</strong>}
                              </span>
                            </div>
                            <div className="cell-time mono">{timeUTC(row.arrived)}</div>
                          </div>
                        );
                      })}
                    </section>
                  ))}
                </section>
              ))}
            </div>}
          </>
        )}
      </main>

      <div className="layout-resizer" onMouseDown={startResize} title="Drag to resize panel" />

      <aside className="workstation-details-panel" data-testid="workstation-details-panel">
        <LatestCasePanel studyId={selectedStudyId} token={token} onVerdictChange={handleVerdictUpdate} />
      </aside>
    </div>
  );
}
