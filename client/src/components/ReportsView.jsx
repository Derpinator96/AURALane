import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";
import { CopyIcon, EyeIcon, FilterIcon, PrintIcon, SearchIcon } from "./Icons.jsx";
import { Overlay, PopoverButton, Segmented } from "./ui.jsx";
import { laneName } from "../worklist.js";
import { PatientLabel } from "../names.jsx";

const STATUS = { draft: "Draft", reviewed: "Reviewed" };
const HEADING = /^[A-Z][A-Z0-9 &/,-]{2,}$/;

const esc = (t) => String(t).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

// Print through a plain window holding only the report, so the page around it
// (the worklist, the top bar) is not on the paper.
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

// A saved report, read in the proportional face with its section headings set apart.
function ReportText({ text }) {
  return (
    <div className="report-text" data-testid="report-text">
      {text.split("\n").map((line, i) => (HEADING.test(line)
        ? <div key={i} className="report-heading">{line}</div>
        : <div key={i} className="report-line">{line || " "}</div>))}
    </div>
  );
}

// The signed-in radiologist's reports, newest first: the latest saved version of
// each study, from the reports store (a draft saved, or a review marked). Filter by
// status, search, open one to read, copy or print.
export default function ReportsView({ token }) {
  const [reports, setReports] = useState(null);
  const [counts, setCounts] = useState({});
  const [status, setStatus] = useState("all");
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(null);
  const [note, setNote] = useState(null);
  const [query, setQuery] = useState("");
  const [lane, setLane] = useState("ALL");
  const [exam, setExam] = useState("ALL");

  useEffect(() => {
    let live = true;
    setReports(null);
    api.reports(token, status === "all" ? null : status)
      .then((res) => { if (live) { setReports(res.reports || []); if (status === "all") setCounts(res.counts || {}); } })
      .catch((e) => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [token, status]);

  const total = (counts.draft || 0) + (counts.reviewed || 0);
  const lanes = useMemo(() => [...new Set((reports || []).map((r) => r.lane).filter(Boolean))], [reports]);
  const exams = useMemo(() => [...new Set((reports || []).map((r) => r.exam || r.modality).filter(Boolean))], [reports]);
  const shown = useMemo(() => {
    const q = query.toLowerCase().trim();
    return (reports || []).filter((r) => (lane === "ALL" || r.lane === lane)
      && (exam === "ALL" || (r.exam || r.modality) === exam)
      && (!q || [r.patient_id, r.study, r.exam, r.driving_finding].some((v) => v && String(v).toLowerCase().includes(q))));
  }, [reports, query, lane, exam]);
  const filters = [lane !== "ALL", exam !== "ALL"].filter(Boolean).length;

  async function copy(text) {
    try {
      await navigator.clipboard.writeText(text);
      setNote("Copied");
    } catch {
      setNote("The browser did not allow copying; select the text instead");
    }
  }
  const openReport = (key) => { setOpen(key); setNote(null); };
  const current = open && (reports || []).find((x) => `${x.study}/${x.version}` === open);

  return (
    <section className="panel queue reports-view" data-testid="reports-view" aria-label="Reports">
      <div className="qhead">
        <Segmented label="Report status" value={status} onChange={(id) => { setStatus(id); setOpen(null); }} items={[
          { id: "all", label: "All", count: total, testid: "reports-all" },
          { id: "reviewed", label: "Reviewed", count: counts.reviewed || 0, testid: "reports-reviewed" },
          { id: "draft", label: "Drafts", count: counts.draft || 0, testid: "reports-draft" },
        ]} />
        <div className="qhead-right">
          <label className="searchpill">
            <SearchIcon size={16} />
            <input type="text" placeholder="Search reports" value={query} aria-label="Search reports"
                   onChange={(e) => setQuery(e.target.value)} className="search-input" />
          </label>
          <PopoverButton label="Filter" icon={<FilterIcon size={16} />} badge={filters || null}>
            <div className="pop-field"><span>Lane</span>
              <select value={lane} onChange={(e) => setLane(e.target.value)} aria-label="Report lane filter">
                <option value="ALL">All lanes</option>
                {lanes.map((l) => <option key={l} value={l}>{l}</option>)}
              </select>
            </div>
            <div className="pop-field"><span>Exam</span>
              <select value={exam} onChange={(e) => setExam(e.target.value)} aria-label="Report exam filter">
                <option value="ALL">All exams</option>
                {exams.map((x) => <option key={x} value={x}>{x}</option>)}
              </select>
            </div>
          </PopoverButton>
        </div>
      </div>

      {error && <p className="error" role="alert">Could not load your reports: {error}</p>}
      {!error && reports === null && <p className="note">Loading your reports.</p>}
      {reports && shown.length === 0 && (
        <p className="empty-line" data-testid="reports-empty">
          {status === "all" ? "No reports yet" : `No ${STATUS[status].toLowerCase()} reports`}
        </p>
      )}

      {shown.length > 0 && (
        <div className="report-list" data-testid="report-list" role="table" aria-label="Reports">
          <div className="report-head" role="row">
            <span role="columnheader">Saved (UTC)</span><span role="columnheader">Patient</span><span role="columnheader">Exam</span>
            <span role="columnheader">Driving finding</span><span role="columnheader">Lane</span><span role="columnheader">Status</span><span />
          </div>
          {shown.map((r) => {
            const key = `${r.study}/${r.version}`;
            return (
              <div key={key} className={`report-row ${open === key ? "selected" : ""}`} role="row" tabIndex={0} data-testid="report-row"
                   onClick={() => openReport(key)} onKeyDown={(e) => { if (e.key === "Enter") openReport(key); }}>
                <span className="mono" role="cell">{r.at?.slice(0, 16).replace("T", " ")}</span>
                <span role="cell"><PatientLabel id={r.patient_id} fallback={r.study} /></span>
                <span role="cell">{r.exam || r.modality}</span>
                <span className="finding-text" role="cell">{r.driving_finding || "--"}</span>
                <span role="cell"><span className={`lanetag lane-${r.lane}`}>{laneName(r.lane)}</span></span>
                <span role="cell"><span className={`chip chip-quiet status-${r.status === "reviewed" ? "ok" : "draft"}`}><span className="dot" />{STATUS[r.status] || r.status}</span></span>
                <span className="row-actions" role="cell">
                  <button type="button" className="circle circle-sm" aria-label="View report" title="View"
                          onClick={(e) => { e.stopPropagation(); openReport(key); }}><EyeIcon size={15} /></button>
                  <button type="button" className="circle circle-sm" aria-label="Copy report" title="Copy"
                          onClick={(e) => { e.stopPropagation(); copy(r.text); }}><CopyIcon size={15} /></button>
                </span>
              </div>
            );
          })}
        </div>
      )}
      {note && !current && <p className="chip chip-quiet" role="status">{note}</p>}

      {current && (
        <Overlay onClose={() => setOpen(null)}>
          <article className="modal-card wide-modal" role="dialog" aria-modal="true" data-testid="report-reader" aria-label="Report">
            <div className="modal-header">
              <div>
                <h2 className="modal-title">{current.exam || current.modality}, <PatientLabel id={current.patient_id} fallback={current.study} inline /></h2>
                <div className="crumbs">Reports <span aria-hidden="true">›</span>
                  <strong>{STATUS[current.status]}</strong> by {current.author_name || current.author}, version {Number(current.version)}</div>
              </div>
              <div className="modal-actions">
                <button type="button" className="pill pill-quiet" onClick={() => copy(current.text)}><CopyIcon size={15} />Copy</button>
                <button type="button" className="pill pill-quiet" onClick={() => { if (!printReport(current)) setNote("The browser blocked the print window"); }}><PrintIcon size={15} />Print</button>
                <button type="button" className="pill pill-primary" onClick={() => setOpen(null)}>Close</button>
              </div>
            </div>
            <ReportText text={current.text} />
            {note && <p className="chip chip-quiet" role="status">{note}</p>}
          </article>
        </Overlay>
      )}
    </section>
  );
}
