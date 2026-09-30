import { useState, useMemo } from "react";
import { laneName, timeUTC } from "../worklist.js";
import { ArrowUpRightIcon, SearchIcon } from "./Icons.jsx";

const studiesText = (n) => `${n} ${n === 1 ? "study" : "studies"}`;

// Patients on the left, the chosen patient's studies on the right. A row opens the study.
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
    <section className="panel history" data-testid="patient-history-view" aria-label="History">
      <div className="qhead">
        <h2 className="card-title queue-title">{selectedPatient === "ALL" ? "All studies" : selectedPatient}</h2>
        <label className="searchpill history-search">
          <SearchIcon size={16} />
          <input type="text" placeholder="Search patients" value={search} aria-label="Search patients"
                 onChange={(e) => setSearch(e.target.value)} className="search-input" />
        </label>
      </div>

      <div className="history-grid">
        <div className="patient-selector-col" role="list" aria-label="Patients">
          <button type="button" className={`patient-row ${selectedPatient === "ALL" ? "active" : ""}`}
                  onClick={() => setSelectedPatient("ALL")}>
            <span>All patients</span>
            <span className="chip chip-quiet">{filteredPatients.length}</span>
          </button>
          {filteredPatients.map((p) => (
            <button key={p.id} type="button" className={`patient-row ${selectedPatient === p.id ? "active" : ""}`}
                    onClick={() => setSelectedPatient(p.id)}>
              <span className="mono-id">{p.id}</span>
              <span className="chip chip-quiet">{studiesText(p.studies.length)}</span>
            </button>
          ))}
        </div>

        <div className="patient-timeline-col">
          {activeStudies.length === 0 && <p className="note empty-line">No studies</p>}
          {activeStudies.map((s) => (
            <div key={s.study} className={`history-row ${s.study === selectedStudyId ? "selected" : ""}`}
                 onClick={() => onSelectStudy(s.study)} data-testid="history-row">
              <span className="cell-time mono">{s.arrived ? `${s.arrived.slice(0, 10)} ${timeUTC(s.arrived)}` : "--"}</span>
              <span className={`lanetag lane-${s.lane}`}>{laneName(s.lane, s.lane_label)}</span>
              <span className="chip chip-quiet">{s.exam || s.modality}</span>
              <span className="mono-id cell-patient">{s.patient_id || s.study}</span>
              <span className="finding-text">{s.driver_label || s.driver || "--"}</span>
              <span className="mono-id cell-acuity">{s.acuity != null ? Number(s.acuity).toFixed(1) : "--"}</span>
              <button type="button" className="circle circle-sm" aria-label={`Open ${s.patient_id || s.study}`} title="Open"
                      onClick={(e) => { e.stopPropagation(); onSelectStudy(s.study); }}>
                <ArrowUpRightIcon size={15} />
              </button>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
