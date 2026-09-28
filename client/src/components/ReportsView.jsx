import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";

// Counts from the worklist the API returned, and this reader's own audit
// events (the full audit log is admin only).
export default function ReportsView({ token, studies = [], me }) {
  const [auditEvents, setAuditEvents] = useState([]);
  const [loadingAudit, setLoadingAudit] = useState(true);
  const [auditError, setAuditError] = useState(null);

  useEffect(() => {
    let live = true;
    api.myHistory(token)
      .then((res) => { if (live) { setAuditEvents(res.events || []); setLoadingAudit(false); } })
      .catch((e) => { if (live) { setAuditError(e.message); setLoadingAudit(false); } });
    return () => { live = false; };
  }, [token]);

  const stats = useMemo(() => {
    const total = studies.length;
    const by = (lane) => studies.filter((s) => s.lane === lane).length;
    const agreed = studies.filter((s) => s.verdict?.value === "agree").length;
    const disagreed = studies.filter((s) => s.verdict?.value === "disagree").length;
    const reviewed = agreed + disagreed;
    return {
      total, critical: by("CRITICAL"), urgent: by("URGENT"), expedited: by("EXPEDITED"),
      routine: by("ROUTINE"), abstain: by("ABSTAIN"), failed: by("FAILED"),
      modalities: new Set(studies.map((s) => s.modality).filter(Boolean)).size,
      mine: me ? studies.filter((s) => s.assigned_to === me).length : 0,
      agreed, reviewed, agreementRate: reviewed > 0 ? ((agreed / reviewed) * 100).toFixed(1) : "--",
    };
  }, [studies, me]);

  const pct = (n) => ((n / (stats.total || 1)) * 100).toFixed(0);

  return (
    <div className="reports-view" data-testid="reports-view">
      <div className="reports-header">
        <h2 className="center-title">Clinical Performance & Audit Reports</h2>
        <p className="center-subtitle">Lane allocation and verdicts across the worklist, and your own audit trail</p>
      </div>

      <div className="kpi-grid">
        <div className="kpi-card">
          <span className="kpi-label">Total Studies Triaged</span>
          <span className="kpi-value mono bold">{stats.total}</span>
          <span className="kpi-sub">Across {stats.modalities} modalities; {stats.mine} assigned to you</span>
        </div>
        <div className="kpi-card card-critical">
          <span className="kpi-label">Critical Priority (&lt; 15 min)</span>
          <span className="kpi-value mono bold">{stats.critical}</span>
          <span className="kpi-sub">{pct(stats.critical)}% of queue</span>
        </div>
        <div className="kpi-card card-urgent">
          <span className="kpi-label">Urgent Priority (&lt; 1 hr)</span>
          <span className="kpi-value mono bold">{stats.urgent}</span>
          <span className="kpi-sub">{pct(stats.urgent)}% of queue</span>
        </div>
        <div className="kpi-card card-agreement">
          <span className="kpi-label">Radiologist Agreement</span>
          <span className="kpi-value mono bold">{stats.agreementRate}{stats.reviewed ? "%" : ""}</span>
          <span className="kpi-sub">{stats.reviewed} verdicts submitted</span>
        </div>
      </div>

      <div className="report-section">
        <h3 className="section-title">Priority Lane Distribution</h3>
        <div className="lane-mix-bars" data-testid="lane-bars">
          {[
            { label: "Critical", count: stats.critical, color: "var(--lane-critical-solid)" },
            { label: "Urgent", count: stats.urgent, color: "var(--lane-urgent-solid)" },
            { label: "Expedited", count: stats.expedited, color: "var(--lane-expedited-solid)" },
            { label: "Routine", count: stats.routine, color: "var(--lane-routine-solid)" },
            { label: "Needs human triage", count: stats.abstain, color: "var(--lane-abstain-solid)" },
            { label: "Pipeline failed", count: stats.failed, color: "#52525b" },
          ].map((item) => {
            const p = stats.total > 0 ? (item.count / stats.total) * 100 : 0;
            return (
              <div key={item.label} className="lane-bar-row">
                <div className="lane-bar-labels">
                  <span className="bold">{item.label}</span>
                  <span className="mono">{item.count} ({p.toFixed(1)}%)</span>
                </div>
                <div className="lane-bar-track">
                  <div className="lane-bar-fill" style={{ width: `${p}%`, background: item.color }}></div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="report-section">
        <h3 className="section-title">Your Audit Trail</h3>
        {auditError && <p className="error">Could not load your audit events: {auditError}</p>}
        {loadingAudit ? (
          <p className="note">Loading audit events.</p>
        ) : auditEvents.length === 0 ? (
          <p className="note">No audit events recorded for you yet.</p>
        ) : (
          <table className="audit-table" data-testid="my-history">
            <thead>
              <tr><th>Timestamp (UTC)</th><th>Action</th><th>Study Ref</th><th>Outcome</th></tr>
            </thead>
            <tbody>
              {auditEvents.slice(0, 25).map((e, idx) => (
                <tr key={e.event_id || idx}>
                  <td className="mono">{e.at?.slice(0, 19).replace("T", " ")}</td>
                  <td><span className="action-tag">{e.action}</span></td>
                  <td className="mono">{e.study || "--"}</td>
                  <td><span className={`outcome-pill outcome-${e.outcome}`}>{e.outcome}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
