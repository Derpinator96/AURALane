import { lazy, Suspense, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api.js";
import { DraftPanel, rationaleText } from "../Study.jsx";
import CtGradcamView, { CtGradcamCaption, hasCtGradcam } from "./CtGradcamView.jsx";
import { WorklistIcon } from "./Icons.jsx";

// Cornerstone (2D) and NiiVue (3D) load only when a study needs them.
const Viewer = lazy(() => import("../viewer/Viewer.jsx"));
const MriViewer3D = lazy(() => import("../viewer/MriViewer3D.jsx"));

const fmt = (v, d = 3) => (v == null ? "--" : Number(v).toFixed(d));

// The study's own images from the datastore (HealthImaging, Orthanc), first
// series, with the Grad-CAM layer pinned on top when it is on.
function SeriesView({ token, detail, overlay }) {
  const [instances, setInstances] = useState(null);
  const [error, setError] = useState(null);
  const series = detail.series?.[0];
  useEffect(() => {
    if (!series || !series.instance_count) return undefined;
    let live = true;
    setInstances(null);
    api.series(token, detail.study.study, series.series_uid)
      .then((d) => live && setInstances(d.instances))
      .catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [token, detail.study.study, series?.series_uid]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!series || !series.instance_count) {
    return <p className="note">{detail.datastore_note || "No images for this study in this runtime."}</p>;
  }
  if (error) return <p className="error">Could not load the images: {error}</p>;
  if (!instances) return <p className="note">Loading the images from the datastore.</p>;
  return (
    <Suspense fallback={<p className="note">Loading the viewer.</p>}>
      <Viewer instances={instances} overlay={overlay} label={series.description} />
    </Suspense>
  );
}

export default function LatestCasePanel({ studyId, token, onVerdictChange }) {
  const navigate = useNavigate();
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [showGradcam, setShowGradcam] = useState(true);
  const [opacity, setOpacity] = useState(0.6);
  const [no3D, setNo3D] = useState(false);

  useEffect(() => {
    if (!studyId) return undefined;
    let live = true;
    setLoading(true);
    setError(null);
    setNo3D(false);
    api.study(token, studyId)
      .then((d) => { if (live) { setDetail(d); setLoading(false); } })
      .catch((err) => { if (live) { setError(err.message || "Failed to load study details"); setLoading(false); } });
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
        <h3>Select a Study</h3>
        <p>Click any study row from the AI Worklist to inspect scans, AI findings, and volumetric measurements.</p>
      </div>
    );
  }
  if (loading) {
    return (
      <div className="case-details-loading">
        <div className="clinical-spinner"></div>
        <p>Loading case data for <span className="mono">{studyId}</span>.</p>
      </div>
    );
  }
  if (error || !detail) {
    return <div className="case-details-error"><p className="error-text">Could not load study {studyId}: {error}</p></div>;
  }

  const s = detail.study;
  const isMR = s.modality === "MR";
  const isCT = s.modality === "CT";
  const isCR = s.modality === "CR" || s.modality === "DX";
  const ev = detail.evidence || {};
  const urls = detail.evidence_urls || {};
  const v = s.verdict;
  const has3D = Boolean(ev.volumes) && !no3D;
  const heat = urls.gradcam_layer_png && ev.gradcam_box && ev.gradcam_coverage !== 0;
  const overlay = showGradcam && heat ? { url: urls.gradcam_layer_png, box: ev.gradcam_box, opacity } : null;

  return (
    <div className="latest-case-panel" data-testid="latest-case-panel">
      <div className="case-panel-header">
        <div className="header-meta">
          <div className="panel-title-row">
            <span className="live-dot"></span>
            <h2 className="panel-title">LATEST CASE DETAILS</h2>
            <button type="button" className="btn-analyse-case" data-testid="btn-analyse-header"
                    onClick={() => navigate(`/studies/${encodeURIComponent(studyId)}`)}>Analyse</button>
          </div>
          <div className="study-identifiers">
            <span className="patient-tag mono">{s.patient_id || s.study}</span>
            <span className="exam-tag">{s.exam || `${s.modality} Study`}</span>
            <span className="pool-tag">{s.pool} Pool</span>
            <span className="pool-tag">{s.assigned_name ? `Reader: ${s.assigned_name}` : "Unassigned"}</span>
          </div>
        </div>
        <div className={`lane-badge lane-${s.lane}`}>
          <span className="lane-text">{s.lane_label || s.lane}</span>
          {s.clock && <span className="lane-clock">SLA: {s.clock}</span>}
        </div>
      </div>

      <div className="case-panel-viewer-section">
        {isMR && (
          <div className="viewer-container mri-tumor-view" data-testid="mr-view">
            <div className="viewer-header-info">
              <span className="viewer-title">Brain MRI: 2D MPR and 3D volume (NiiVue)</span>
              <span className="viewer-hint">Axial, coronal, sagittal and 3D, synchronised</span>
            </div>
            {has3D ? (
              <Suspense fallback={<p className="note">Loading the 3D viewer.</p>}>
                <MriViewer3D studyId={studyId} token={token} onUnavailable={() => setNo3D(true)} />
              </Suspense>
            ) : (
              <>
                {urls.overlay_png && <img src={urls.overlay_png} alt="Segmentation overlay" className="cxr-base-img" />}
                <p className="note" data-testid="no-3d">
                  No 3D volume is stored for this study (ingested before volumes were kept, or its
                  mask failed the check). {urls.overlay_png ? "Showing the model's segmentation outline." : ""}
                </p>
              </>
            )}
            <p className="evidence-caption">{rationaleText(detail)}</p>
          </div>
        )}

        {isCR && (
          <div className="viewer-container cxr-view" data-testid="cxr-view">
            <div className="viewer-header-info">
              <span className="viewer-title">Chest Radiography</span>
              {heat && (
                <button type="button" className={`btn-gradcam-toggle ${showGradcam ? "active" : ""}`}
                        aria-pressed={showGradcam} onClick={() => setShowGradcam(!showGradcam)}
                        data-testid="gradcam-toggle">
                  {showGradcam ? "Grad-CAM Heatmap: ON" : "Grad-CAM Heatmap: OFF"}
                </button>
              )}
            </div>
            {showGradcam && heat && (
              <label className="slider-label">
                <span>Opacity {Math.round(opacity * 100)}%</span>
                <input type="range" min="0.1" max="1" step="0.05" value={opacity}
                       onChange={(e) => setOpacity(parseFloat(e.target.value))} aria-label="Grad-CAM opacity" />
              </label>
            )}
            <SeriesView token={token} detail={detail} overlay={overlay} />
            <p className="evidence-caption"><span className="bold">Grad-CAM Explanation:</span> {rationaleText(detail)}</p>
          </div>
        )}

        {isCT && (
          <div className="viewer-container ct-view" data-testid="ct-view">
            <div className="viewer-header-info">
              <span className="viewer-title">Head CT (Axial Non-Contrast)</span>
              <button type="button" className={`btn-gradcam-toggle ${showGradcam ? "active" : ""}`}
                      onClick={() => setShowGradcam(!showGradcam)} disabled={!hasCtGradcam(urls)}
                      data-testid="ct-gradcam-toggle">
                {showGradcam ? "Grad-CAM Heatmap: ON" : "Grad-CAM Heatmap: OFF"}
              </button>
            </div>
            {hasCtGradcam(urls) ? (
              <>
                <CtGradcamView evidence={ev} urls={urls} show={showGradcam} />
                <CtGradcamCaption evidence={ev} />
                {detail.decision_reason && <p className="evidence-caption">{detail.decision_reason}</p>}
              </>
            ) : (
              <>
                <SeriesView token={token} detail={detail} overlay={null} />
                <p className="note viewer-empty" data-testid="ct-no-gradcam">
                  {s.lane === "FAILED"
                    ? "Processing failed, so there is no Grad-CAM for this study."
                    : "No Grad-CAM image is stored for this study (scored before the CT endpoint drew one)."}
                </p>
                <p className="evidence-caption"><span className="bold">CT AI Finding:</span> {rationaleText(detail)}</p>
              </>
            )}
          </div>
        )}
      </div>

      <div className="case-panel-findings-section">
        <h3 className="section-heading">AI Triage Findings & Signals</h3>
        {detail.findings && detail.findings.length > 0 ? (
          <table className="findings-table">
            <thead><tr><th>Finding</th><th className="num">Signal</th><th className="num">Urgency</th></tr></thead>
            <tbody>
              {detail.findings.map((f) => (
                <tr key={f.name} className={f.name === s.driver ? "driver-row" : ""}>
                  <td className="finding-name">
                    {f.label || f.name}
                    {f.name === s.driver && <span className="driver-tag">Driving Finding</span>}
                  </td>
                  <td className="mono num">{fmt(f.signal)}</td>
                  <td className="mono num">{fmt(f.urgency, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="note">{s.abstain_reason || "No abnormal findings flagged by the model."}</p>
        )}
        {isMR && ev.volumes_cm3 && (
          <p className="note mono">
            Whole tumour {ev.volumes_cm3.whole_tumour} cm3, core {ev.volumes_cm3.tumour_core} cm3,
            enhancing {ev.volumes_cm3.enhancing} cm3 (the model's segmentation)
          </p>
        )}
      </div>

      {s.lane !== "FAILED" && (
        <div className="case-panel-verdict-section" data-testid="verdict-section">
          <div className="verdict-header">
            <span className="verdict-title">Triage Lane Assignment</span>
            <span className="verdict-status-note">
              {v ? `Status: ${v.value === "agree" ? "Agreed" : "Disagreed"} by ${v.by}` : "Pending Radiologist Verdict"}
            </span>
          </div>
          <div className="verdict-actions">
            <button type="button" disabled={busy} onClick={() => handleVerdict("agree")}
                    className={`btn-verdict btn-agree ${v?.value === "agree" ? "selected" : ""}`}>
              Agree with {s.lane_label || s.lane}
            </button>
            <button type="button" disabled={busy} onClick={() => handleVerdict("disagree")}
                    className={`btn-verdict btn-disagree ${v?.value === "disagree" ? "selected" : ""}`}>
              Disagree / Escalate
            </button>
          </div>
        </div>
      )}

      <DraftPanel detail={detail} saveDraft={(id, text, reviewed) => api.saveDraft(token, id, text, reviewed)} />

      <div className="case-panel-analyse-cta">
        <button type="button" className="btn-analyse-full" data-testid="btn-analyse-bottom"
                onClick={() => navigate(`/studies/${encodeURIComponent(studyId)}`)}>
          Analyse Case Scans in Full Detail
        </button>
      </div>
    </div>
  );
}
