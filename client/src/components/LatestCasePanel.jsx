import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api.js";
import { DraftPanel, rationaleText } from "../Study.jsx";
import { WorklistIcon } from "./Icons.jsx";

const fmt = (v, d = 3) => (v == null ? "--" : Number(v).toFixed(d));

// The selected study beside the worklist: its rationale image, findings, the
// verdict and the draft. Opening it in full loads the images.
export default function LatestCasePanel({ studyId, token, onVerdictChange }) {
  const navigate = useNavigate();
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [showRationale, setShowRationale] = useState(true);

  useEffect(() => {
    if (!studyId) return undefined;
    let live = true;
    setDetail(null);
    setError(null);
    api.study(token, studyId)
      .then((d) => live && setDetail(d))
      .catch((err) => live && setError(err.message || "failed"));
    return () => { live = false; };
  }, [studyId, token]);

  const handleVerdict = async (value) => {
    if (!detail || busy) return;
    setBusy(true);
    try {
      const res = await api.verdict(token, studyId, value);
      setDetail((prev) => ({ ...prev, study: res.study }));
      if (onVerdictChange) onVerdictChange(studyId, res.study);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  if (!studyId) {
    return (
      <div className="case-details-empty">
        <div className="empty-icon"><WorklistIcon size={32} /></div>
        <h3>No study selected</h3>
        <p>Select a row to see its rationale, findings and draft.</p>
      </div>
    );
  }
  if (error) return <div className="case-details-error"><p className="error-text">Could not load study {studyId}: {error}</p></div>;
  if (!detail) return <div className="case-details-loading"><p>Loading <span className="mono">{studyId}</span>.</p></div>;

  const s = detail.study;
  const ev = detail.evidence || {};
  const urls = detail.evidence_urls || {};
  const v = s.verdict;
  const heat = urls.gradcam_layer_png && ev.gradcam_coverage !== 0;

  return (
    <div className="latest-case-panel" data-testid="latest-case-panel">
      <div className="case-panel-header">
        <div className="header-meta">
          <div className="panel-title-row">
            <h2 className="panel-title">Selected study</h2>
            <button type="button" className="btn-analyse-case" data-testid="btn-analyse-header"
                    onClick={() => navigate(`/studies/${encodeURIComponent(studyId)}`)}>Open</button>
          </div>
          <div className="study-identifiers">
            <span className="patient-tag mono">{s.patient_id || s.study}</span>
            <span className="exam-tag">{s.exam || s.modality}</span>
            <span className="pool-tag">{s.pool} pool</span>
            {s.assigned_name && <span className="pool-tag">Assigned to {s.assigned_name}</span>}
          </div>
        </div>
        <div className={`lane-badge lane-${s.lane}`}>
          <span className="lane-text">{s.lane_label || s.lane}</span>
          {s.clock && <span className="lane-clock">{s.clock}</span>}
        </div>
      </div>

      <div className="case-panel-viewer-section" data-testid="case-rationale">
        <div className="viewer-header-info">
          <span className="viewer-title">Triage rationale</span>
          {(heat || urls.overlay_png) && (
            <button type="button" className={`btn-gradcam-toggle ${showRationale ? "active" : ""}`}
                    aria-pressed={showRationale} onClick={() => setShowRationale((x) => !x)}>
              {showRationale ? "ON" : "OFF"}
            </button>
          )}
        </div>
        {showRationale && heat && urls.gradcam_png && (
          <img src={urls.gradcam_png} alt={`Grad-CAM for ${ev.gradcam_finding}`} className="cxr-base-img" />
        )}
        {showRationale && urls.overlay_png && (
          <img src={urls.overlay_png} alt="Segmentation overlay" className="cxr-base-img" />
        )}
        <p className="evidence-caption">{rationaleText(detail)}</p>
      </div>

      <div className="case-panel-findings-section">
        <h3 className="section-heading">Findings</h3>
        {detail.findings && detail.findings.length > 0 ? (
          <table className="findings-table">
            <thead><tr><th>Finding</th><th className="num">Signal</th><th className="num">Urgency</th></tr></thead>
            <tbody>
              {detail.findings.map((f) => (
                <tr key={f.name} className={f.name === s.driver ? "driver-row" : ""}>
                  <td className="finding-name">
                    {f.label || f.name}
                    {f.name === s.driver && <span className="driver-tag">Driving finding</span>}
                  </td>
                  <td className="mono num">{fmt(f.signal)}</td>
                  <td className="mono num">{fmt(f.urgency, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="note">{s.abstain_reason || "No findings reported."}</p>
        )}
      </div>

      {s.lane !== "FAILED" && (
        <div className="case-panel-verdict-section" data-testid="verdict-section">
          <div className="verdict-header">
            <span className="verdict-title">Your call on the lane</span>
            <span className="verdict-status-note">
              {v ? `${v.value === "agree" ? "Agreed" : "Disagreed"} by ${v.by}` : "No verdict yet"}
            </span>
          </div>
          <div className="verdict-actions">
            <button type="button" disabled={busy} onClick={() => handleVerdict("agree")}
                    className={`btn-verdict btn-agree ${v?.value === "agree" ? "selected" : ""}`}>
              Agree with {s.lane_label || s.lane}
            </button>
            <button type="button" disabled={busy} onClick={() => handleVerdict("disagree")}
                    className={`btn-verdict btn-disagree ${v?.value === "disagree" ? "selected" : ""}`}>
              Disagree
            </button>
          </div>
        </div>
      )}

      <DraftPanel detail={detail}
                  saveDraft={(id, text, reviewed) => api.saveDraft(token, id, text, reviewed)} />
    </div>
  );
}
