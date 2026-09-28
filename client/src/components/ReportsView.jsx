import { useEffect, useState, useMemo } from "react";
import { api } from "../api.js";

export default function ReportsView({ token, studies = [] }) {
  const [auditEvents, setAuditEvents] = useState([]);
  const [loadingAudit, setLoadingAudit] = useState(false);

  useEffect(() => {
    let live = true;
    setLoadingAudit(true);
    api.audit(token)
      .then((res) => {
        if (live && res && res.events) {
          setAuditEvents(res.events);
          setLoadingAudit(false);
        }
      })
      .catch(() => {
        if (live) setLoadingAudit(false);
      });
    return () => {
      live = false;
    };
  }, [token]);

  const stats = useMemo(() => {
    const total = studies.length;
    const critical = studies.filter((s) => s.lane === "CRITICAL").length;
    const urgent = studies.filter((s) => s.lane === "URGENT").length;
    const expedited = studies.filter((s) => s.lane === "EXPEDITED").length;
    const routine = studies.filter((s) => s.lane === "ROUTINE").length;
    const abstain = studies.filter((s) => s.lane === "ABSTAIN").length;

    const agreed = studies.filter((s) => s.verdict?.value === "agree").length;
    const disagreed = studies.filter((s) => s.verdict?.value === "disagree").length;
    const reviewed = agreed + disagreed;
    const agreementRate = reviewed > 0 ? ((agreed / reviewed) * 100).toFixed(1) : "--";

    return {
      total,
      critical,
      urgent,
      expedited,
      routine,
      abstain,
      agreed,
      disagreed,
      reviewed,
      agreementRate,
    };
  }, [studies]);

  return (
    <div className="reports-view" data-testid="reports-view">
      <div className="reports-header">
        <h2 className="center-title">Clinical Performance & Audit Reports</h2>
        <p className="center-subtitle">
          Real-time triage quality metrics, lane allocation distributions, and tamper-evident audit logs
        </p>
      </div>

      {/* KPI Stats Grid */}
      <div className="kpi-grid">
        <div className="kpi-card">
          <span className="kpi-label">Total Studies Triaged</span>
          <span className="kpi-value mono bold">{stats.total}</span>
          <span className="kpi-sub">Across 4 modalities</span>
        </div>

        <div className="kpi-card card-critical">
          <span className="kpi-label">Critical Priority (&lt; 15 min)</span>
          <span className="kpi-value mono bold">{stats.critical}</span>
          <span className="kpi-sub">{((stats.critical / (stats.total || 1)) * 100).toFixed(0)}% of queue</span>
        </div>

        <div className="kpi-card card-urgent">
          <span className="kpi-label">Urgent Priority (&lt; 1 hr)</span>
          <span className="kpi-value mono bold">{stats.urgent}</span>
          <span className="kpi-sub">{((stats.urgent / (stats.total || 1)) * 100).toFixed(0)}% of queue</span>
        </div>

        <div className="kpi-card card-agreement">
          <span className="kpi-label">Radiologist Agreement</span>
          <span className="kpi-value mono bold">{stats.agreementRate}%</span>
          <span className="kpi-sub">{stats.reviewed} verdicts submitted</span>
        </div>
      </div>

      {/* Lane Mix Breakdown */}
      <div className="report-section">
        <h3 className="section-title">Priority Lane Distribution</h3>
        <div className="lane-mix-bars">
          {[
            { label: "Critical", count: stats.critical, color: "var(--lane-critical-solid)" },
            { label: "Urgent", count: stats.urgent, color: "var(--lane-urgent-solid)" },
            { label: "Expedited", count: stats.expedited, color: "var(--lane-expedited-solid)" },
            { label: "Routine", count: stats.routine, color: "var(--lane-routine-solid)" },
            { label: "Abstain", count: stats.abstain, color: "var(--lane-abstain-solid)" },
          ].map((item) => {
            const pct = stats.total > 0 ? (item.count / stats.total) * 100 : 0;
            return (
              <div key={item.label} className="lane-bar-row">
                <div className="lane-bar-labels">
                  <span className="bold">{item.label}</span>
                  <span className="mono">{item.count} ({pct.toFixed(1)}%)</span>
                </div>
                <div className="lane-bar-track">
                  <div
                    className="lane-bar-fill"
                    style={{ width: `${pct}%`, background: item.color }}
                  ></div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Audit Log Table */}
      <div className="report-section">
        <h3 className="section-title">Audit Trail (Immutable Regulatory Ledger)</h3>
        {loadingAudit ? (
          <p className="note">Loading audit logs...</p>
        ) : auditEvents.length === 0 ? (
          <p className="note">No audit events recorded yet.</p>
        ) : (
          <table className="audit-table">
            <thead>
              <tr>
                <th>Timestamp (UTC)</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Study Ref</th>
                <th>Outcome</th>
              </tr>
            </thead>
            <tbody>
              {auditEvents.slice(0, 15).map((e, idx) => (
                <tr key={e.event_id || idx}>
                  <td className="mono">{e.at?.slice(0, 19).replace("T", " ")}</td>
                  <td>{e.actor}</td>
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
