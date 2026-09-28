import { useState, useMemo } from "react";
import { timeUTC } from "../worklist.js";
import { SearchIcon } from "./Icons.jsx";

export default function PatientHistoryView({ studies = [], onSelectStudy, selectedStudyId }) {
  const [selectedPatient, setSelectedPatient] = useState("ALL");
  const [search, setSearch] = useState("");

  const patients = useMemo(() => {
    const map = new Map();
    for (const s of studies) {
      const pid = s.patient_id || s.study;
      if (!map.has(pid)) {
        map.set(pid, { id: pid, studies: [] });
      }
      map.get(pid).studies.push(s);
    }
    return Array.from(map.values());
  }, [studies]);

  const filteredPatients = useMemo(() => {
    let list = patients;
    if (search.trim()) {
      const q = search.toLowerCase().trim();
      list = list.filter((p) => p.id.toLowerCase().includes(q));
    }
    return list;
  }, [patients, search]);

  const activeStudies = useMemo(() => {
    if (selectedPatient === "ALL") return studies;
    const match = patients.find((p) => p.id === selectedPatient);
    return match ? match.studies : [];
  }, [patients, selectedPatient, studies]);

  return (
    <div className="patient-history-view" data-testid="patient-history-view">
      <div className="history-header">
        <div>
          <h2 className="center-title">All Cases & Patient History</h2>
          <p className="center-subtitle">
            Longitudinal patient imaging records across all diagnostic modalities
          </p>
        </div>

        <div className="search-box patient-search">
          <span className="search-icon"><SearchIcon size={14} /></span>
          <input
            type="text"
            placeholder="Search patient pseudonym..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="search-input"
          />
        </div>
      </div>

      <div className="history-content-grid">
        {/* Patient Selection Column */}
        <div className="patient-selector-col">
          <div className="col-heading">Patients ({filteredPatients.length})</div>
          <button
            type="button"
            className={`patient-tab ${selectedPatient === "ALL" ? "active" : ""}`}
            onClick={() => setSelectedPatient("ALL")}
          >
            <span>All Patients</span>
            <span className="patient-count">{studies.length}</span>
          </button>
          {filteredPatients.map((p) => (
            <button
              key={p.id}
              type="button"
              className={`patient-tab ${selectedPatient === p.id ? "active" : ""}`}
              onClick={() => setSelectedPatient(p.id)}
            >
              <span className="mono bold">{p.id}</span>
              <span className="patient-count">{p.studies.length} studies</span>
            </button>
          ))}
        </div>

        {/* Timeline / Studies Column */}
        <div className="patient-timeline-col">
          <div className="col-heading">
            {selectedPatient === "ALL" ? "All Diagnostic Studies" : `Imaging History for ${selectedPatient}`}
          </div>

          <div className="timeline-list">
            {activeStudies.map((s) => {
              const isSelected = s.study === selectedStudyId;
              return (
                <div
                  key={s.study}
                  className={`timeline-card ${isSelected ? "selected" : ""}`}
                  onClick={() => onSelectStudy(s.study)}
                >
                  <div className="timeline-card-header">
                    <span className="timeline-date mono">Arrived {timeUTC(s.arrived)} UTC</span>
                    <span className={`lanetag lane-${s.lane}`}>{s.lane_label || s.lane}</span>
                  </div>

                  <div className="timeline-main">
                    <div className="timeline-modality">
                      <span className={`mod-badge mod-${s.modality}`}>
                        {s.alzheimer ? "MR Brain (Cognitive)" : s.exam || s.modality}
                      </span>
                      <span className="timeline-patient mono">{s.patient_id || s.study}</span>
                    </div>

                    <div className="timeline-driver">
                      <span className="bold">{s.driver_label || s.driver || "Unremarkable"}</span>
                      {s.acuity != null && <span className="acuity-chip mono">Acuity: {Number(s.acuity).toFixed(1)}</span>}
                    </div>
                  </div>

                  <div className="timeline-actions">
                    <button
                      type="button"
                      className="btn-timeline-inspect"
                      onClick={(e) => {
                        e.stopPropagation();
                        onSelectStudy(s.study);
                      }}
                    >
                      {isSelected ? "Active in Viewer ✓" : "Load in Case Details →"}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
