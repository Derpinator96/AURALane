import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";

const STATUS = { draft: "Draft", reviewed: "Reviewed" };

const esc = (t) => String(t).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

// Print through a plain window holding only the report, so the page around it
// (the worklist, the sidebar) is not on the paper.
function printReport(r) {
  const w = window.open("", "_blank", "width=800,height=900");
  if (!w) return false;
  w.document.write(`<!doctype html><title>Report ${esc(r.patient_id || r.study)}</title>
    <style>body{font:14px/1.5 system-ui,sans-serif;margin:32px}pre{white-space:pre-wrap;font:13px/1.55 ui-monospace,monospace}
    h1{font-size:18px;margin:0 0 4px}p{color:#555;margin:0 0 16px}</style>
    <h1>${esc(r.exam || r.modality || "Report")}, ${esc(r.patient_id || r.study)}</h1>
    <p>${esc(STATUS[r.status] || r.status)} by ${esc(r.author_name || r.author)} at ${esc(r.at)}. Version ${Number(r.version)}.</p>
    <pre>${esc(r.text)}</pre>`);
  w.document.close();
  w.focus();
  w.print();
  return true;
}

// The signed-in radiologist's reports, newest first: the latest saved version of
// each study, from the reports store (a draft saved, or a review marked). Filter by
// status, open one to read, copy or print. Below it, a summary of the worklist.
export default function ReportsView({ token, studies = [], me }) {
  const [reports, setReports] = useState(null);
  const [counts, setCounts] = useState({});
  const [status, setStatus] = useState("all");
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(null);
  const [note, setNote] = useState(null);

  useEffect(() => {
    let live = true;
    setReports(null);
    api.reports(token, status === "all" ? null : status)
      .then((res) => { if (live) { setReports(res.reports || []); if (status === "all") setCounts(res.counts || {}); } })
      .catch((e) => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [token, status]);

  const stats = useMemo(() => {
    const total = studies.length;
    const by = (lane) => studies.filter((s) => s.lane === lane).length;
    const agreed = studies.filter((s) => s.verdict?.value === "agree").length;
    const reviewed = agreed + studies.filter((s) => s.verdict?.value === "disagree").length;
    return { total, critical: by("CRITICAL"), urgent: by("URGENT"),
             mine: me ? studies.filter((s) => s.assigned_to === me).length : 0,
             reviewed, agreementRate: reviewed > 0 ? ((agreed / reviewed) * 100).toFixed(1) : "--" };
  }, [studies, me]);

  const total = (counts.draft || 0) + (counts.reviewed || 0);

  async function copy(text) {
    try {
      await navigator.clipboard.writeText(text);
      setNote("Copied.");
    } catch {
      setNote("The browser did not allow copying; select the text instead.");
    }
  }

  return (
    <div className="reports-view" data-testid="reports-view">
      <div className="reports-header">
        <h2 className="center-title">Reports</h2>
        <p className="center-subtitle">The reports you saved as drafts or marked reviewed, newest first.</p>
      </div>

      <div className="report-filter" role="group" aria-label="Report status">
        {[["all", "All", total], ["reviewed", "Reviewed", counts.reviewed || 0], ["draft", "Drafts", counts.draft || 0]]
          .map(([id, label, n]) => (
            <button key={id} type="button" aria-pressed={status === id} onClick={() => { setStatus(id); setOpen(null); }}
                    data-testid={`reports-${id}`}>
              {label} <span className="count mono">{n}</span>
            </button>
          ))}
      </div>

      {error && <p className="error" role="alert">Could not load your reports: {error}</p>}
      {!error && reports === null && <p className="note">Loading your reports.</p>}
      {reports && reports.length === 0 && (
        <p className="note" data-testid="reports-empty">
          {status === "all" ? "No reports yet. Open a study, then save its draft or mark it reviewed."
                            : `No ${STATUS[status].toLowerCase()} reports.`}
        </p>
      )}

      {reports && reports.length > 0 && (
        <div className="report-list-wrap">
          <table className="report-list" data-testid="report-list">
            <thead>
              <tr><th>Saved (UTC)</th><th>Patient</th><th>Exam</th><th>Driving finding</th><th>Lane</th><th>Status</th></tr>
            </thead>
            <tbody>
              {reports.map((r) => {
                const key = `${r.study}/${r.version}`;
                return (
                  <tr key={key} className={open === key ? "selected" : ""} tabIndex={0} data-testid="report-row"
                      onClick={() => { setOpen(key); setNote(null); }}
                      onKeyDown={(e) => { if (e.key === "Enter") { setOpen(key); setNote(null); } }}>
                    <td className="mono">{r.at?.slice(0, 16).replace("T", " ")}</td>
                    <td className="mono">{r.patient_id || r.study}</td>
                    <td>{r.exam || r.modality}</td>
                    <td>{r.driving_finding || "--"}</td>
                    <td><span className={`lanetag lane-${r.lane}`}>{r.lane}</span></td>
                    <td><span className={`report-status status-${r.status}`}>{STATUS[r.status] || r.status}</span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {open && (() => {
            const r = reports.find((x) => `${x.study}/${x.version}` === open);
            if (!r) return null;
            return (
              <article className="report-reader" data-testid="report-reader" aria-label="Report">
                <header>
                  <div>
                    <h3>{r.exam || r.modality}, <span className="mono">{r.patient_id || r.study}</span></h3>
                    <p className="note">{STATUS[r.status]} by {r.author_name || r.author} at {r.at}. Version {Number(r.version)}.</p>
                  </div>
                  <div className="report-actions">
                    <button type="button" className="btn" onClick={() => copy(r.text)}>Copy</button>
                    <button type="button" className="btn" onClick={() => { if (!printReport(r)) setNote("The browser blocked the print window."); }}>Print</button>
                    <button type="button" className="btn" onClick={() => setOpen(null)}>Close</button>
                  </div>
                </header>
                <pre className="report-text mono" data-testid="report-text">{r.text}</pre>
                {note && <p className="note" role="status">{note}</p>}
              </article>
            );
          })()}
        </div>
      )}

      <div className="report-section">
        <h3 className="section-title">Worklist summary</h3>
        <div className="kpi-grid">
          <div className="kpi-card"><span className="kpi-label">On your worklist</span>
            <span className="kpi-value mono bold">{stats.total}</span>
            <span className="kpi-sub">{stats.mine} assigned to you</span></div>
          <div className="kpi-card"><span className="kpi-label">Critical</span>
            <span className="kpi-value mono bold">{stats.critical}</span></div>
          <div className="kpi-card"><span className="kpi-label">Urgent</span>
            <span className="kpi-value mono bold">{stats.urgent}</span></div>
          <div className="kpi-card"><span className="kpi-label">Agreement with the lane</span>
            <span className="kpi-value mono bold">{stats.agreementRate}{stats.reviewed ? "%" : ""}</span>
            <span className="kpi-sub">{stats.reviewed} verdicts submitted</span></div>
        </div>
      </div>
    </div>
  );
}
