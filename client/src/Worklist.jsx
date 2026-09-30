import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { arrangePools, isUnread } from "./worklist.js";
import { displayName } from "./dashboard.js";
import Sidebar, { TITLES } from "./components/Sidebar.jsx";
import LatestCasePanel from "./components/LatestCasePanel.jsx";
import PatientHistoryView from "./components/PatientHistoryView.jsx";
import ReportsView from "./components/ReportsView.jsx";
import SettingsView from "./components/SettingsView.jsx";
import SimulatePanel from "./components/SimulatePanel.jsx";
import DistributePanel from "./components/DistributePanel.jsx";
import QueueCard from "./components/QueueCard.jsx";
import { GaugeCard, ReadersCard, StatRow, WaitingCard } from "./components/DashboardCards.jsx";
import ErrorBoundary, { Failed } from "./components/ErrorBoundary.jsx";
import { CloseIcon, PlayIcon, UsersIcon } from "./components/Icons.jsx";
import { Overlay } from "./components/ui.jsx";
import { loadSettings } from "./settings.js";

const VIEW_KEY = "auralane.worklistView";

function loadView() {
  try {
    return localStorage.getItem(VIEW_KEY) === "board" ? "board" : "list";
  } catch {
    return "list";
  }
}

export default function Worklist({ load, token }) {
  const location = useLocation();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [sort, setSort] = useState("priority");
  const [lane, setLane] = useState("ALL");
  const [read, setRead] = useState("all");
  const [query, setQuery] = useState("");
  const [activeNav, setActiveNav] = useState("worklist");
  const [specialty, setSpecialty] = useState("ALL");
  const [selectedStudyId, setSelectedStudyId] = useState(null);
  const [panel, setPanel] = useState(null);             // "simulate" | "distribute"
  const [chosenScope, setScope] = useState(null);       // "mine" | "all"
  const [refresh, setRefresh] = useState(() => loadSettings().refreshSeconds);
  const [poolTab, setPoolTab] = useState("ALL");        // "ALL" or a pool name
  const [onlyTriage, setOnlyTriage] = useState(false);
  const [view, setViewState] = useState(loadView);      // "list" | "board"
  const searchRef = useRef(null);
  const setView = (v) => {
    setViewState(v);
    try {
      localStorage.setItem(VIEW_KEY, v);
    } catch {
      // Storage unavailable: the choice lasts until reload.
    }
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

  // Refresh on a timer, but only while this tab is visible; coming back to the tab
  // refreshes at once.
  useEffect(() => {
    if (!refresh && !error) return undefined;
    const t = setInterval(() => { if (!document.hidden) fetchWorklist(); }, (error ? 5 : refresh) * 1000);
    const onVisible = () => { if (!document.hidden) fetchWorklist(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(t);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [fetchWorklist, refresh, error]);

  // The top bar's search button: go to the worklist tab and put the cursor in its search field.
  useEffect(() => {
    const go = () => { setActiveNav("worklist"); setTimeout(() => searchRef.current?.focus(), 30); };
    window.addEventListener("auralane:search", go);
    if (location.state?.focusSearch) go();
    return () => window.removeEventListener("auralane:search", go);
  }, [location.state]);

  useEffect(() => { document.title = `${TITLES[activeNav]} · AURALane`; }, [activeNav]);

  const mine = useMemo(() => (data?.me ? (data.studies || []).filter((s) => s.assigned_to === data.me) : []),
    [data]);
  // My studies when something is assigned to me; otherwise the whole queue.
  const scope = chosenScope ?? (mine.length ? "mine" : "all");
  const scopeStudies = useMemo(() => (scope === "mine" ? mine : data?.studies || []), [scope, mine, data]);

  const handleVerdictUpdate = (studyId, updatedStudy) => {
    setData((prev) => prev && {
      ...prev, studies: prev.studies.map((s) => (s.study === studyId ? { ...s, ...updatedStudy } : s)),
    });
  };

  const filteredStudies = useMemo(() => {
    let list = scopeStudies;
    if (specialty === "MR") list = list.filter((s) => s.modality === "MR");
    else if (specialty === "CR") list = list.filter((s) => s.modality === "CR" || s.modality === "DX");
    else if (specialty === "CT") list = list.filter((s) => s.modality === "CT");
    if (activeNav === "recent") list = list.filter((s) => !isUnread(s));
    const q = query.toLowerCase().trim();
    if (q) {
      list = list.filter((s) => [s.patient_id, s.study, s.exam, s.driver, s.driver_label, s.assigned_name]
        .some((v) => v && String(v).toLowerCase().includes(q)));
    }
    return list;
  }, [scopeStudies, specialty, activeNav, query]);

  const pools = useMemo(
    () => (data ? arrangePools(filteredStudies, data.pools, data.lanes,
                               { sort, lane, read, only: onlyTriage ? "ABSTAIN" : null }) : []),
    [data, filteredStudies, sort, lane, read, onlyTriage]);

  // The study to read next: the first unread critical one, else the first unread. Its row
  // is the first of its pool and lane, and is raised.
  const nextUpId = useMemo(() => {
    const unread = filteredStudies.filter((s) => isUnread(s));
    return (unread.find((s) => s.lane === "CRITICAL") || unread[0])?.study ?? null;
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
  const laneLabels = Object.fromEntries((data.lanes || []).map((l) => [l.lane, l.label]));
  const who = (row) => (row.assigned_to
    ? (row.assigned_to === data.me ? "You" : row.assigned_name || row.assigned_to) : "Unassigned");
  const name = displayName(data.me, readers);
  const onWorklist = activeNav === "worklist";

  const queue = (
    <QueueCard
      title={onWorklist ? "Worklist" : "Read cases"} recent={activeNav === "recent"}
      data={data} scope={scope} setScope={setScope} mine={mine} pools={pools}
      poolTab={poolTab} setPoolTab={setPoolTab} view={view} setView={setView}
      filteredStudies={filteredStudies} selectedStudyId={selectedStudyId} onSelect={setSelectedStudyId}
      nextUpId={onWorklist ? nextUpId : null} query={query} setQuery={setQuery} searchRef={searchRef}
      filters={{ lane, setLane, read, setRead, sort, setSort, specialty, setSpecialty }}
      onlyTriage={onlyTriage} clearTriage={() => setOnlyTriage(false)} who={who} />
  );

  return (
    <div className="page" data-testid="workstation-layout">
      {panel === "simulate" && (
        <SimulatePanel token={token} readers={readers} me={data.me} onClose={() => setPanel(null)} onProgress={fetchWorklist} />
      )}
      {panel === "distribute" && (
        <DistributePanel token={token} readers={readers} studies={data.studies}
                         onClose={() => setPanel(null)} onDone={fetchWorklist} />
      )}

      <Sidebar activeNav={activeNav} onNavChange={setActiveNav} counts={counts} />

      <header className="page-head">
        <h1 className="page-title">
          {onWorklist ? (name ? `Welcome back, ${name}` : "Welcome back") : TITLES[activeNav]}
        </h1>
        {onWorklist && (
          <div className="page-actions">
            <button type="button" className="pill pill-primary" onClick={() => setPanel("simulate")}
                    data-testid="btn-simulate"><PlayIcon size={15} />Simulate ingest</button>
            <button type="button" className="pill" onClick={() => setPanel("distribute")}
                    disabled={readers.length === 0} data-testid="btn-distribute"><UsersIcon size={16} />Distribute worklist</button>
          </div>
        )}
      </header>

      {stale && <p className="note" role="status">Lost contact with the API. Showing the last list; retrying.</p>}

      {activeNav === "history" && (
        <PatientHistoryView studies={filteredStudies} onSelectStudy={setSelectedStudyId}
                            selectedStudyId={selectedStudyId} />
      )}
      {activeNav === "reports" && <ReportsView token={token} />}
      {activeNav === "settings" && <SettingsView onChange={(s) => setRefresh(s.refreshSeconds)} />}

      {onWorklist && (
        <div className="dash">
          <div className="dash-main">
            <StatRow studies={scopeStudies} onlyTriage={onlyTriage}
                     onToggleTriage={() => {
                       setOnlyTriage((v) => !v);
                       document.querySelector('[data-testid="queue-card"]')?.scrollIntoView?.({ block: "start" });
                     }} />
            <div className="chart-row">
              <WaitingCard studies={scopeStudies} laneLabels={laneLabels} scopeLabel={scope === "mine" ? "My worklist" : "All studies"} />
              <GaugeCard studies={scopeStudies} scopeLabel={scope === "mine" ? "My worklist" : "All studies"} />
            </div>
            {queue}
          </div>
          <aside className="dash-side"><ReadersCard readers={readers} studies={data.studies} /></aside>
        </div>
      )}
      {activeNav === "recent" && queue}

      {selectedStudyId && (
        <Overlay side="right" onClose={() => setSelectedStudyId(null)}>
          <aside className="sheet" data-testid="workstation-details-panel" role="dialog" aria-modal="true" aria-label="Study details">
            <button type="button" className="circle sheet-close" onClick={() => setSelectedStudyId(null)}
                    aria-label="Close study panel" title="Close (Esc)" data-testid="close-panel">
              <CloseIcon size={18} />
            </button>
            <ErrorBoundary key={selectedStudyId} fallback={({ reset }) => <Failed what="This study" onRetry={reset} />}>
              <LatestCasePanel studyId={selectedStudyId} token={token} me={data.me}
                               onVerdictChange={handleVerdictUpdate} onChanged={fetchWorklist}
                               onLeft={() => setSelectedStudyId(null)} />
            </ErrorBoundary>
          </aside>
        </Overlay>
      )}
    </div>
  );
}
