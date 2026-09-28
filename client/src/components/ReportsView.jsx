import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";

// A reader's own activity: lane counts from the worklist they can see, and
// their own audit events (verdicts, opens, drafts, assignments they made). The
// full audit log is admin only.
export default function ReportsView({ token, studies = [], me }) {
  const [history, setHistory] = useState({ events: null, error: null });

  useEffect(() => {
    let live = true;
    api.myHistory(token)
      .then((d) => live && setHistory({ events: d.events, error: null }))
      .catch((e) => live && setHistory({ events: [], error: e.message }));
    return () => { live = false; };
  }, [token]);

  const stats = useMemo(() => {
    const mine = studies.filter((s) => s.assigned_to === me);
    const count = (lane) => mine.filter((s) => s.lane === lane).length;
    const agreed = mine.filter((s) => s.verdict?.value === "agree").length;
    const disagreed = mine.filter((s) => s.verdict?.value === "disagree").length;
    return { total: mine.length, lanes: ["CRITICAL", "URGENT", "ABSTAIN", "EXPEDITED", "ROUTINE"].map((l) => [l, count(l)]),
             agreed, disagreed, unread: mine.length - agreed - disagreed };
  }, [studies, me]);

  return (
    <div className="reports-view" data-testid="reports-view">
      <div className="reports-header">
        <h2 className="center-title">My activity</h2>
        <p className="center-subtitle">Studies assigned to you, and what you did. Counted from the worklist and the audit log.</p>
      </div>

      <div className="kpi-grid">
        <div className="kpi-card"><span className="kpi-label">Assigned to you</span>
          <span className="kpi-value mono bold">{stats.total}</span></div>
        <div className="kpi-card"><span className="kpi-label">Unread</span>
          <span className="kpi-value mono bold">{stats.unread}</span></div>
        <div className="kpi-card"><span className="kpi-label">You agreed with the lane</span>
          <span className="kpi-value mono bold">{stats.agreed}</span></div>
        <div className="kpi-card"><span className="kpi-label">You disagreed</span>
          <span className="kpi-value mono bold">{stats.disagreed}</span></div>
      </div>

      <div className="report-section">
        <h3 className="section-title">Your studies by lane</h3>
        <table className="audit-table" data-testid="my-lanes">
          <tbody>
            {stats.lanes.map(([lane, n]) => (
              <tr key={lane}><td><span className={`lanetag lane-${lane}`}>{lane === "ABSTAIN" ? "NEEDS HUMAN TRIAGE" : lane}</span></td>
                <td className="mono num">{n}</td></tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="report-section">
        <h3 className="section-title">Your audit events</h3>
        {history.error && <p className="error">Could not load your history: {history.error}</p>}
        {history.events === null ? (
          <p className="note">Loading.</p>
        ) : history.events.length === 0 ? (
          <p className="note">No events recorded for you yet.</p>
        ) : (
          <table className="audit-table" data-testid="my-history">
            <thead><tr><th>Time (UTC)</th><th>Action</th><th>Study</th><th>Outcome</th></tr></thead>
            <tbody>
              {history.events.slice(0, 50).map((e) => (
                <tr key={e.event_id}>
                  <td className="mono">{e.at?.slice(0, 19).replace("T", " ")}</td>
                  <td><span className="action-tag">{e.action}</span></td>
                  <td className="mono">{e.study || "--"}</td>
                  <td>{e.outcome}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
