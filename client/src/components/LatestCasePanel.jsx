import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api.js";
import MriViewer3D from "../viewer/MriViewer3D.jsx";
import CtGradcamView, { CtGradcamCaption, hasCtGradcam } from "./CtGradcamView.jsx";
import { WorklistIcon } from "./Icons.jsx";

const fmt = (v, d = 3) => (v == null ? "--" : Number(v).toFixed(d));

export default function LatestCasePanel({ studyId, token, onVerdictChange }) {
  const navigate = useNavigate();
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [showGradcam, setShowGradcam] = useState(true);

  useEffect(() => {
    if (!studyId) return;
    let live = true;
    setLoading(true);
    setError(null);

    api.study(token, studyId)
      .then((d) => {
        if (live) {
          setDetail(d);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (live) {
          setError(err.message || "Failed to load study details");
          setLoading(false);
        }
      });

    return () => {
      live = false;
    };
  }, [studyId, token]);

  const handleVerdict = async (value) => {
    if (!detail || busy) return;
    setBusy(true);
    try {
      const res = await api.verdict(token, studyId, value);
      setDetail((prev) => ({ ...prev, study: res.study }));
      if (onVerdictChange) onVerdictChange(studyId, res.study);
    } catch (err) {
      console.error("Verdict error:", err);
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
        <p>Loading real-time case data for <span className="mono">{studyId}</span>...</p>
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="case-details-error">
        <p className="error-text">Could not load study {studyId}: {error}</p>
      </div>
    );
  }

  const s = detail.study;
  const isAlz = Boolean(s.alzheimer || detail.alzheimer || (studyId && studyId.toLowerCase().includes("alz")));
  const isMR = s.modality === "MR";
  const isCT = s.modality === "CT";
  const isCR = s.modality === "CR" || s.modality === "DX" || s.modality === "X-RAY";

  const alz = s.alzheimer || detail.alzheimer;
  const ev = detail.evidence || {};
  const urls = detail.evidence_urls || {};
  const v = s.verdict;

  return (
    <div className="latest-case-panel" data-testid="latest-case-panel">
      {/* Panel Header */}
      <div className="case-panel-header">
        <div className="header-meta">
          <div className="panel-title-row">
            <span className="live-dot" title="Live Synced Case"></span>
            <h2 className="panel-title">LATEST CASE DETAILS</h2>
            <button
              type="button"
              className="btn-analyse-case"
              onClick={() => navigate(`/studies/${studyId}`)}
              title="Open case in full detailed clinical analysis view"
              data-testid="btn-analyse-header"
            >
              Analyse
            </button>
          </div>
          <div className="study-identifiers">
            <span className="patient-tag mono">{s.patient_id || s.study}</span>
            <span className="exam-tag">{s.exam || `${s.modality} Study`}</span>
            <span className="pool-tag">{s.pool} Pool</span>
          </div>
        </div>

        <div className={`lane-badge lane-${s.lane}`}>
          <span className="lane-text">{s.lane_label || s.lane}</span>
          {s.clock && <span className="lane-clock">SLA: {s.clock}</span>}
        </div>
      </div>

      {/* Dynamic Modality-Specific Viewer & Visual Explanation */}
      <div className="case-panel-viewer-section">
        {/* MODALITY 1: BRAIN TUMOR MRI (Multi-Sequence BraTS) */}
        {isMR && !isAlz && (
          <div className="viewer-container mri-tumor-view">
            <div className="viewer-header-info">
              <span className="viewer-title">Brain MRI — 2D MPR & 3D Volume Raymarching (NiiVue)</span>
              <span className="viewer-hint">Synchronized Axial / Coronal / Sagittal / 3D views</span>
            </div>
            <MriViewer3D studyId={studyId} isAlzheimer={false} />
          </div>
        )}

        {/* MODALITY 2: ALZHEIMER'S COGNITIVE MRI (T1-Only) */}
        {isMR && isAlz && (
          <div className="viewer-container mri-alzheimer-view">
            <div className="viewer-header-info alzheimer-banner">
              <span className="viewer-title">Cognitive Assessment Pipeline — T1-Weighted Structural MRI</span>
              <span className="viewer-note">Single-sequence T1 input (No tumor segmentation mask applied)</span>
            </div>
            <MriViewer3D studyId={studyId} isAlzheimer={true} />

            {/* Alzheimer Probabilities Breakdown Card */}
            {alz && (
              <div className="alzheimer-results-card" data-testid="alzheimer-card">
                <div className="alzheimer-header">
                  <div className="alzheimer-predicted">
                    <span className="alzheimer-label">Classification Output:</span>
                    <span className={`predicted-badge class-${alz.predicted_class}`}>
                      {alz.predicted_class === "AD" ? "Alzheimer's Disease (AD)" : alz.predicted_class === "MCI" ? "Mild Cognitive Impairment (MCI)" : "Cognitively Normal (CN)"}
                    </span>
                  </div>
                  <div className="model-chip">
                    {alz.model_name || "Rootstrap 3D DenseNet121"}
                  </div>
                </div>

                <div className="probability-bars">
                  <div className="prob-row">
                    <div className="prob-labels">
                      <span>P(AD) — Alzheimer's Disease:</span>
                      <span className="mono bold">{((alz.probabilities?.AD || 0) * 100).toFixed(1)}%</span>
                    </div>
                    <div className="progress-track">
                      <div
                        className="progress-fill fill-ad"
                        style={{ width: `${(alz.probabilities?.AD || 0) * 100}%` }}
                      ></div>
                    </div>
                  </div>

                  <div className="prob-row">
                    <div className="prob-labels">
                      <span>P(MCI) — Mild Cognitive Impairment:</span>
                      <span className="mono bold">{((alz.probabilities?.MCI || 0) * 100).toFixed(1)}%</span>
                    </div>
                    <div className="progress-track">
                      <div
                        className="progress-fill fill-mci"
                        style={{ width: `${(alz.probabilities?.MCI || 0) * 100}%` }}
                      ></div>
                    </div>
                  </div>

                  <div className="prob-row">
                    <div className="prob-labels">
                      <span>P(CN) — Cognitively Normal:</span>
                      <span className="mono bold">{((alz.probabilities?.CN || 0) * 100).toFixed(1)}%</span>
                    </div>
                    <div className="progress-track">
                      <div
                        className="progress-fill fill-cn"
                        style={{ width: `${(alz.probabilities?.CN || 0) * 100}%` }}
                      ></div>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* MODALITY 3: CHEST X-RAY (CXR) */}
        {isCR && (
          <div className="viewer-container cxr-view" data-testid="cxr-view">
            <div className="viewer-header-info">
              <span className="viewer-title">Chest Radiography (PA View)</span>
              <button
                type="button"
                className={`btn-gradcam-toggle ${showGradcam ? "active" : ""}`}
                onClick={() => setShowGradcam(!showGradcam)}
              >
                {showGradcam ? "Grad-CAM Heatmap: ON" : "Grad-CAM Heatmap: OFF"}
              </button>
            </div>

            <div className="cxr-canvas-wrapper">
              <img
                src={urls.gradcam_png || "/fixtures/frames/sample_cxr.png"}
                alt="Chest Radiograph"
                className="cxr-base-img"
              />
              {showGradcam && urls.gradcam_layer_png && (
                <img
                  src={urls.gradcam_layer_png}
                  alt="Grad-CAM Overlay"
                  className="cxr-overlay-img"
                />
              )}
            </div>

            {ev.gradcam_finding && (
              <p className="evidence-caption">
                <span className="bold">Grad-CAM Explanation:</span> Attention localized around{" "}
                <span className="highlight-text">{ev.gradcam_finding}</span> ({((ev.gradcam_coverage || 0.12) * 100).toFixed(1)}% coverage).
              </p>
            )}
          </div>
        )}

        {/* MODALITY 4: HEAD CT */}
        {isCT && (
          <div className="viewer-container ct-view" data-testid="ct-view">
            <div className="viewer-header-info">
              <span className="viewer-title">Head CT (Axial Non-Contrast)</span>
              <button
                type="button"
                className={`btn-gradcam-toggle ${showGradcam ? "active" : ""}`}
                onClick={() => setShowGradcam(!showGradcam)}
                disabled={!hasCtGradcam(urls)}
                data-testid="ct-gradcam-toggle"
              >
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
              <p className="note viewer-empty" data-testid="ct-no-gradcam">
                {s.lane === "FAILED"
                  ? "Processing failed, so there is no Grad-CAM for this study."
                  : "No Grad-CAM image is stored for this study."}
              </p>
            )}
          </div>
        )}
      </div>

      {/* Clinical Measurements & Findings Section */}
      <div className="case-panel-findings-section">
        <h3 className="section-heading">AI Triage Findings & Signals</h3>
        {detail.findings && detail.findings.length > 0 ? (
          <table className="findings-table">
            <thead>
              <tr>
                <th>Finding</th>
                <th className="num">Signal</th>
                <th className="num">Urgency</th>
              </tr>
            </thead>
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
          <p className="note">No abnormal findings flagged by automated model.</p>
        )}
      </div>

      {/* Clinician Verdict Interaction */}
      <div className="case-panel-verdict-section" data-testid="verdict-section">
        <div className="verdict-header">
          <span className="verdict-title">Triage Lane Assignment</span>
          <span className="verdict-status-note">
            {v ? `Status: ${v.value === "agree" ? "Agreed" : "Disagreed"} by ${v.by}` : "Pending Radiologist Verdict"}
          </span>
        </div>

        <div className="verdict-actions">
          <button
            type="button"
            className={`btn-verdict btn-agree ${v?.value === "agree" ? "selected" : ""}`}
            disabled={busy}
            onClick={() => handleVerdict("agree")}
          >
            Agree with {s.lane_label || s.lane}
          </button>
          <button
            type="button"
            className={`btn-verdict btn-disagree ${v?.value === "disagree" ? "selected" : ""}`}
            disabled={busy}
            onClick={() => handleVerdict("disagree")}
          >
            Disagree / Escalate
          </button>
        </div>
      </div>

      {/* Draft Clinical Note */}
      {detail.draft && (
        <details className="case-panel-draft">
          <summary>Preliminary Clinical Impression (Draft Note)</summary>
          <pre className="draft-content mono">{detail.draft}</pre>
        </details>
      )}

      {/* Full Detailed Analysis CTA */}
      <div className="case-panel-analyse-cta">
        <button
          type="button"
          className="btn-analyse-full"
          onClick={() => navigate(`/studies/${studyId}`)}
          title="Open complete multi-planar analysis workstation for this case"
          data-testid="btn-analyse-bottom"
        >
          Analyse Case Scans in Full Detail →
        </button>
      </div>
    </div>
  );
}
