import { useEffect, useMemo, useState } from "react";
import { arrangePools, READ_FILTERS, SORTS, timeUTC, isUnread } from "./worklist.js";
import UploadModal from "./components/UploadModal.jsx";
import Sidebar from "./components/Sidebar.jsx";
import LatestCasePanel from "./components/LatestCasePanel.jsx";
import PatientHistoryView from "./components/PatientHistoryView.jsx";
import ReportsView from "./components/ReportsView.jsx";
import SettingsView from "./components/SettingsView.jsx";
import { SearchIcon } from "./components/Icons.jsx";
import { api } from "./api.js";

const LANE_FILTERS = ["ALL", "CRITICAL", "URGENT", "EXPEDITED", "ROUTINE"];

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
  const [showUpload, setShowUpload] = useState(false);
  const [quickLoading, setQuickLoading] = useState(false);
  const [detailsWidth, setDetailsWidth] = useState(580);

  const startResize = (e) => {
    e.preventDefault();
    const startX = e.clientX;
    const startWidth = detailsWidth;

    const onMouseMove = (moveEvent) => {
      const delta = startX - moveEvent.clientX;
      const newWidth = Math.max(350, Math.min(1000, startWidth + delta));
      setDetailsWidth(newWidth);
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

  const fetchWorklist = () => {
    load()
      .then((d) => {
        setData(d);
        // Default selected study to highest priority study if none selected
        if (!selectedStudyId && d.studies && d.studies.length > 0) {
          const topCritical = d.studies.find((s) => s.lane === "CRITICAL") || d.studies[0];
          setSelectedStudyId(topCritical.study);
        }
      })
      .catch((e) => setError(e));
  };

  useEffect(() => {
    let live = true;
    load()
      .then((d) => {
        if (live) {
          setData(d);
          if (d.studies && d.studies.length > 0) {
            // Find highest priority study for initial right panel
            const top = d.studies.find((s) => s.lane === "CRITICAL") || d.studies[0];
            setSelectedStudyId(top.study);
          }
        }
      })
      .catch((e) => live && setError(e));
    return () => {
      live = false;
    };
  }, [load]);

  const handleQuickLoadBrats = async () => {
    setQuickLoading(true);
    try {
      const res = await api.mriDemo(token);
      setSelectedStudyId(res.study.study);
      fetchWorklist();
    } catch (e) {
      console.error("BraTS quick load error:", e);
    } finally {
      setQuickLoading(false);
    }
  };

  const handleQuickLoadAlzheimer = async () => {
    setQuickLoading(true);
    try {
      const res = await api.alzheimerDemo(token);
      setSelectedStudyId(res.study.study);
      fetchWorklist();
    } catch (e) {
      console.error("Alzheimer quick load error:", e);
    } finally {
      setQuickLoading(false);
    }
  };

  const handleVerdictUpdate = (studyId, updatedStudy) => {
    setData((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        studies: prev.studies.map((s) => (s.study === studyId ? { ...s, ...updatedStudy } : s)),
      };
    });
  };

  // Filter studies based on specialty filter, search, and navigation
  const filteredStudies = useMemo(() => {
    if (!data || !data.studies) return [];
    let list = data.studies;

    // Specialty filter
    if (specialtyFilter === "MR_TUMOR") {
      list = list.filter((s) => s.modality === "MR" && !s.alzheimer && !s.study.toLowerCase().includes("alz"));
    } else if (specialtyFilter === "MR_ALZHEIMER") {
      list = list.filter((s) => s.alzheimer || s.study.toLowerCase().includes("alz"));
    } else if (specialtyFilter === "CR") {
      list = list.filter((s) => s.modality === "CR" || s.modality === "DX");
    } else if (specialtyFilter === "CT") {
      list = list.filter((s) => s.modality === "CT");
    }

    // Navigation filter
    if (activeNav === "recent") {
      list = list.filter((s) => !isUnread(s) || s.lane === "CRITICAL");
    }

    // Search query
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim();
      list = list.filter(
        (s) =>
          (s.patient_id && s.patient_id.toLowerCase().includes(q)) ||
          s.study.toLowerCase().includes(q) ||
          (s.exam && s.exam.toLowerCase().includes(q)) ||
          (s.driver && s.driver.toLowerCase().includes(q)) ||
          (s.driver_label && s.driver_label.toLowerCase().includes(q))
      );
    }

    return list;
  }, [data, specialtyFilter, activeNav, searchQuery]);

  const pools = useMemo(
    () => (data ? arrangePools(filteredStudies, data.pools, data.lanes, { sort, lane, read }) : []),
    [data, filteredStudies, sort, lane, read]
  );

  // Highest priority study for the prominent hero card
  const heroStudy = useMemo(() => {
    if (!filteredStudies || filteredStudies.length === 0) return null;
    return filteredStudies.find((s) => s.lane === "CRITICAL") || filteredStudies[0];
  }, [filteredStudies]);

  // Counts for sidebar badges
  const counts = useMemo(() => {
    if (!data || !data.studies) return { total: 0, recent: 0 };
    return {
      total: data.studies.length,
      recent: data.studies.filter((s) => !isUnread(s)).length,
    };
  }, [data]);

  if (error) {
    return (
      <main className="workstation-error">
        <p className="error" role="alert">
          Could not load the worklist: {String(error.message)}
        </p>
      </main>
    );
  }

  if (!data) {
    return (
      <main className="workstation-loading">
        <div className="clinical-spinner"></div>
        <p>Initializing AURALane Clinician Workstation...</p>
      </main>
    );
  }

  return (
    <div 
      className="workstation-layout" 
      data-testid="workstation-layout"
      style={{ gridTemplateColumns: `240px 1fr 6px ${detailsWidth}px` }}
    >
      {showUpload && (
        <UploadModal
          token={token}
          onClose={() => setShowUpload(false)}
          onStudyIngested={(study) => {
            if (study?.study) setSelectedStudyId(study.study);
            fetchWorklist();
          }}
        />
      )}

      {/* 1. PERSISTENT LEFT SIDEBAR */}
      <Sidebar
        activeNav={activeNav}
        onNavChange={setActiveNav}
        specialtyFilter={specialtyFilter}
        onSpecialtyChange={setSpecialtyFilter}
        counts={counts}
      />

      {/* 2. CENTRAL CONTENT AREA */}
      <main className="workstation-center" data-testid="workstation-center">
        {activeNav === "history" && (
          <PatientHistoryView
            studies={data.studies || []}
            onSelectStudy={(id) => setSelectedStudyId(id)}
            selectedStudyId={selectedStudyId}
          />
        )}

        {activeNav === "reports" && (
          <ReportsView
            token={token}
            studies={data.studies || []}
          />
        )}

        {activeNav === "settings" && (
          <SettingsView />
        )}

        {(activeNav === "worklist" || activeNav === "recent") && (
          <>
            {/* Central Header with Quick Actions */}
            <div className="center-header">
          <div>
            <h2 className="center-title">AI Worklist Queue</h2>
            <p className="center-subtitle">
              Prioritized by neural triage engine • High-urgency findings ranked automatically
            </p>
          </div>

          <div className="center-action-buttons">
            <button
              type="button"
              className="btn-action-primary"
              onClick={() => setShowUpload(true)}
              data-testid="btn-open-upload"
            >
              + Ingest Custom Study
            </button>
            <button
              type="button"
              className="btn-action-quick"
              onClick={handleQuickLoadBrats}
              disabled={quickLoading}
              title="Instantly load verified BraTS multi-sequence Brain Tumor case 00000057"
            >
              Demo: BraTS 00000057
            </button>
            <button
              type="button"
              className="btn-action-quick"
              onClick={handleQuickLoadAlzheimer}
              disabled={quickLoading}
              title="Instantly load verified Alzheimer's T1 cognitive test case AD_01"
            >
              Demo: Alzheimer AD_01
            </button>
          </div>
        </div>

        {/* Filter and Control Bar */}
        <div className="worklist-filter-bar">
          <div className="search-box">
            <span className="search-icon"><SearchIcon size={14} /></span>
            <input
              type="text"
              placeholder="Search patient, study ID, finding..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="search-input"
            />
            {searchQuery && (
              <button type="button" className="search-clear" onClick={() => setSearchQuery("")}>
                ✕
              </button>
            )}
          </div>

          <div className="filter-dropdowns">
            <label className="filter-item">
              <span>Lane:</span>
              <select value={lane} onChange={(e) => setLane(e.target.value)} aria-label="Lane filter">
                {LANE_FILTERS.map((l) => (
                  <option key={l} value={l}>
                    {l === "ALL" ? "All Lanes" : l}
                  </option>
                ))}
              </select>
            </label>

            <label className="filter-item">
              <span>Status:</span>
              <select value={read} onChange={(e) => setRead(e.target.value)} aria-label="Read filter">
                {Object.entries(READ_FILTERS).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </label>

            <label className="filter-item">
              <span>Sort:</span>
              <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort">
                {Object.entries(SORTS).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>

        {/* HIGHEST PRIORITY STUDY: HERO CARD (Visually Prominent) */}
        {heroStudy && (
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
                  <span className="driver-label-text">Driving Finding:</span>
                  <span className="bold highlight-driver">
                    {heroStudy.driver_label || heroStudy.driver || "Unremarkable"}
                  </span>
                </div>
              </div>

              <div className="hero-metrics">
                <div className="metric-box">
                  <span className="box-title">Acuity Score</span>
                  <span className="box-val mono bold"><Acuity row={heroStudy} /></span>
                </div>
                <div className="metric-box">
                  <span className="box-title">Confidence</span>
                  <span className="box-val mono">{heroStudy.confidence ? `${(heroStudy.confidence * 100).toFixed(0)}%` : "MONAI Vol"}</span>
                </div>
              </div>

              <div className="hero-action-col">
                <button
                  type="button"
                  className={`btn-hero-inspect ${selectedStudyId === heroStudy.study ? "active-inspect" : ""}`}
                  onClick={() => setSelectedStudyId(heroStudy.study)}
                >
                  {selectedStudyId === heroStudy.study ? "Active in Viewer" : "Inspect Case Scans →"}
                </button>
                <span className="hero-time mono">Arrived {timeUTC(heroStudy.arrived)} UTC</span>
              </div>
            </div>
          </section>
        )}

        {/* STUDY LIST QUEUE */}
        <div className="queue-container">
          <div className="queue-colhead" aria-hidden="true">
            <span>Lane / SLA</span>
            <span>Patient ID</span>
            <span>Modality</span>
            <span>AI Driving Finding</span>
            <span>Acuity</span>
            <span>Status</span>
            <span>Arrived</span>
          </div>

          {pools.map((p) => (
            <div key={p.pool} className="pool-group" data-testid={`pool-${p.pool}`}>
              <div className="pool-header">
                <span className="pool-title">{p.label} Reading Pool</span>
                <span className="pool-badge">{p.sections.reduce((acc, s) => acc + s.rows.length, 0)} Studies</span>
              </div>

              {p.sections.map((s) => (
                <div key={s.lane} className="lane-group">
                  {s.rows.map((row) => {
                    const isSelected = row.study === selectedStudyId;
                    const verdict = row.verdict ? (row.verdict.value === "agree" ? "Agreed" : "Disagreed") : "Unread";
                    return (
                      <div
                        key={row.study}
                        className={`study-row lane-${row.lane} ${isSelected ? "selected" : ""}`}
                        onClick={() => setSelectedStudyId(row.study)}
                        data-testid="study-row"
                        data-study={row.study}
                      >
                        <div className="cell-lane">
                          <span className={`lanetag lane-${row.lane}`}>{row.lane_label || row.lane}</span>
                          {row.clock && <span className="cell-clock mono">{row.clock}</span>}
                        </div>

                        <div className="cell-patient mono bold">
                          {row.patient_id || row.study}
                        </div>

                        <div className="cell-modality">
                          <span className={`mod-badge mod-${row.modality}`}>
                            {row.alzheimer ? "MR Brain (Alzheimer)" : row.exam || row.modality}
                          </span>
                        </div>

                        <div className="cell-finding">
                          <span className="finding-text" title={row.driver_label || row.driver || "--"}>
                            {row.lane === "FAILED" ? row.error : row.driver_label || row.driver || row.abstain_reason || "--"}
                          </span>
                        </div>

                        <div className="cell-acuity mono">
                          <Acuity row={row} />
                        </div>

                        <div className="cell-status">
                          <span className={`verdict-pill ${isUnread(row) ? "unread" : "reviewed"}`}>
                            {verdict}
                          </span>
                        </div>

                        <div className="cell-time mono">
                          {timeUTC(row.arrived)}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ))}
            </div>
          ))}
        </div>
          </>
        )}
      </main>

      {/* RESIZER */}
      <div 
        className="layout-resizer"
        onMouseDown={startResize}
        title="Drag to resize panel"
      />

      {/* 3. LATEST CASE DETAILS (PERSISTENT RIGHT PANEL) */}
      <aside className="workstation-details-panel" data-testid="workstation-details-panel">
        <LatestCasePanel
          studyId={selectedStudyId}
          token={token}
          onVerdictChange={handleVerdictUpdate}
        />
      </aside>
    </div>
  );
}
