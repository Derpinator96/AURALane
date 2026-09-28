import { lazy, Suspense, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import CtGradcamView, { hasCtGradcam } from "./components/CtGradcamView.jsx";
import { timeUTC } from "./worklist.js";
import { CheckIcon, ClockIcon } from "./components/Icons.jsx";

// The viewer pulls in Cornerstone and its codecs; load it only on this page.
const Viewer = lazy(() => import("./viewer/Viewer.jsx"));
const MriViewer3D = lazy(() => import("./viewer/MriViewer3D.jsx"));

const fmt = (v, d = 3) => (v == null ? "--" : Number(v).toFixed(d));

function Patient({ study }) {
  return <span className="mono bold">{study.patient_id || study.study}</span>;
}

function Rationale({ detail, on, onToggle }) {
  const ev = detail.evidence || {};
  const urls = detail.evidence_urls || {};
  const available = Boolean(urls.gradcam_layer_png || urls.overlay_png);
  return (
    <div className="rationale">
      <button
        type="button"
        aria-pressed={on}
        disabled={!available}
        onClick={onToggle}
        data-testid="rationale-toggle"
        className="btn-rationale-toggle"
      >
        Triage rationale: {on ? "ON" : "OFF"}
      </button>
      {!available && <span className="note">No rationale image for this study.</span>}
      {on && urls.gradcam_layer_png && (
        <p className="note" data-testid="rationale-caption">
          {ev.gradcam_coverage === 0
            ? `Grad-CAM found no region at or above the display threshold for ${ev.gradcam_finding} on this image, so nothing is drawn. `
            : `Grad-CAM for ${ev.gradcam_finding}, drawn on ${(ev.gradcam_coverage * 100).toFixed(1)}% of the model's view. `}
          A sanity check on why the study was placed where it was, not a localisation.
          {ev.gradcam_note ? ` ${ev.gradcam_note}` : ""}
        </p>
      )}
    </div>
  );
}

function Verdict({ study, onVerdict, busy }) {
  const v = study.verdict;
  return (
    <div className="study-verdict-section">
      <div className="verdict-header">
        <h4 className="verdict-heading">Radiologist Decision Support</h4>
        <span className="verdict-sub">Audit Record</span>
      </div>
      <div className="verdict-action-buttons">
        <button
          type="button"
          disabled={busy}
          aria-pressed={v?.value === "agree"}
          onClick={() => onVerdict("agree")}
          className={`btn-verdict btn-agree ${v?.value === "agree" ? "selected" : ""}`}
        >
          {v?.value === "agree" && <CheckIcon size={14} />} Agree (Accept Triage)
        </button>
        <button
          type="button"
          disabled={busy}
          aria-pressed={v?.value === "disagree"}
          onClick={() => onVerdict("disagree")}
          className={`btn-verdict btn-disagree ${v?.value === "disagree" ? "selected" : ""}`}
        >
          {v?.value === "disagree" && <CheckIcon size={14} />} Disagree (Override)
        </button>
      </div>
      <div className="verdict-audit-badge" data-testid="verdict-status">
        {v ? (
          <span className="audit-ok">
            {v.value === "agree" ? "Agreed" : "Disagreed"} by {v.by} at {v.at}
          </span>
        ) : (
          <span className="audit-pending">Awaiting radiologist verification.</span>
        )}
      </div>
    </div>
  );
}

function SegmentationRationale({ detail }) {
  const ev = detail.evidence || {};
  return (
    <figure className="rationale-image" data-testid="rationale-image">
      <figcaption className="note">
        Triage rationale: segmentation outline on axial index {ev.axial_index}, the slice with the
        largest tumour area. Yellow edema, orange tumour core, red enhancing tumour.
      </figcaption>
      <img src={detail.evidence_urls.overlay_png} alt="Segmentation overlay" />
    </figure>
  );
}

export function StudyPanel({ detail, onVerdict, busy, rationaleOn = false }) {
  const s = detail.study;
  const brain = s.modality === "MR";
  const [copied, setCopied] = useState(false);

  const handleCopyDraft = () => {
    if (detail.draft) {
      navigator.clipboard.writeText(detail.draft);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <aside className="study-analysis-sidebar" data-testid="study-panel">
      {/* Priority Lane Card */}
      <div className={`analysis-lane-card lane-${s.lane}`}>
        <div className="lane-header-row">
          <span className="lane-badge-text">{s.lane_label || s.lane}</span>
          {s.clock && (
            <span className="lane-sla-target mono">
              <ClockIcon size={13} /> SLA: {s.clock}
            </span>
          )}
        </div>
        <div className="lane-meta-row">
          <span className="meta-acuity">
            Acuity: <strong className="mono">{s.lane === "ABSTAIN" || s.lane === "FAILED" ? "--" : fmt(s.acuity, 1)}</strong>
          </span>
          <span className="meta-driver">
            Primary Finding: <strong>{s.driver_label || s.driver || "Unremarkable"}</strong>
          </span>
        </div>
      </div>

      {/* Patient & Exam Metadata Facts */}
      <div className="study-facts-card">
        <h4 className="card-section-title">Clinical Study Context</h4>
        <dl className="facts-grid">
          <dt>Patient ID</dt>
          <dd><Patient study={s} /></dd>

          <dt>Exam Modality</dt>
          <dd>{s.exam}</dd>

          <dt>Confidence</dt>
          <dd>
            {brain ? (
              <span className="confidence-volumetric">Volumetric MONAI SegResNet Output</span>
            ) : (
              <span className="mono">{fmt(s.confidence, 3)} (Calibrated)</span>
            )}
          </dd>

          <dt>Model ID</dt>
          <dd className="mono text-faint">{s.model_id || "monai-brats-v1"}</dd>

          <dt>Arrived</dt>
          <dd className="mono">{s.arrived ? `${timeUTC(s.arrived)} UTC` : "--"}</dd>
        </dl>
      </div>

      {rationaleOn && detail.evidence_urls?.overlay_png && <SegmentationRationale detail={detail} />}
      {s.lane === "FAILED" && <p className="error-banner">Processing error: {s.error}</p>}
      {s.abstain_reason && (
        <div className="abstain-notice-box" data-testid="abstain-reason">
          <strong>No lane assigned:</strong> {s.abstain_reason}. Radiologist review required.
        </div>
      )}

      {/* Structured AI Findings Table */}
      <div className="study-findings-card">
        <div className="findings-header">
          <h4 className="card-section-title">Deep AI Findings Signal</h4>
          <span className="findings-sub">Signal (0.0 to 1.0) against operating threshold</span>
        </div>

        {detail.findings.length === 0 ? (
          <p className="note" data-testid="no-findings">
            {s.lane === "FAILED" ? "None: processing did not reach the model output." : "None reported."}
          </p>
        ) : (
          <table className="findings-table-modern">
            <thead>
              <tr>
                <th>Finding Pathology</th>
                <th>Signal Meter</th>
                <th className="num">Signal</th>
                <th className="num">Urgency</th>
              </tr>
            </thead>
            <tbody>
              {detail.findings.map((f) => {
                const isDriver = f.name === s.driver;
                const sigVal = f.signal != null ? Number(f.signal) : 0;
                return (
                  <tr key={f.name} className={isDriver ? "driver-finding-row" : ""}>
                    <td className="finding-name-cell">
                      <span>{f.label}</span>
                      {isDriver && <span className="driver-pill">DRIVER</span>}
                    </td>
                    <td className="meter-cell">
                      <div className="signal-track">
                        <div
                          className={`signal-bar ${isDriver ? "bar-driver" : "bar-normal"}`}
                          style={{ width: `${Math.min(100, Math.max(0, sigVal * 100))}%` }}
                        />
                      </div>
                    </td>
                    <td className="mono num bold">{fmt(f.signal, 2)}</td>
                    <td className="mono num text-soft">{fmt(f.urgency, 2)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Radiologist Verdict Decision Section */}
      {s.lane === "FAILED" ? (
        <p className="note">No lane assigned. Study flagged for manual PACS review.</p>
      ) : (
        <Verdict study={s} onVerdict={onVerdict} busy={busy} />
      )}

      {/* AI Structured Draft Note */}
      {detail.draft && (
        <div className="study-draft-card">
          <div className="draft-header">
            <h4 className="card-section-title">Structured Draft Note</h4>
            <button
              type="button"
              className="btn-copy-draft"
              onClick={handleCopyDraft}
              title="Copy formatted note to clipboard"
            >
              {copied ? "✓ Copied" : "Copy Note"}
            </button>
          </div>
          <pre className="draft-note-body">{detail.draft}</pre>
        </div>
      )}

      {s.source && (
        <div className="study-source-footer mono">
          <span>Audit Source: {s.source}</span>
        </div>
      )}
    </aside>
  );
}

export default function Study({ load, loadSeries, sendVerdict }) {
  const { id } = useParams();
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const [seriesUid, setSeriesUid] = useState(null);
  const [instances, setInstances] = useState(null);
  const [rationale, setRationale] = useState(true);
  const [busy, setBusy] = useState(false);

  const [view3D, setView3D] = useState(true);

  useEffect(() => {
    load(id).then((d) => {
      setDetail(d);
      setSeriesUid(d.series[0]?.series_uid || null);
    }).catch(setError);
  }, [id, load]);

  useEffect(() => {
    if (!seriesUid) return;
    setInstances(null);
    loadSeries(id, seriesUid).then((d) => setInstances(d.instances)).catch(setError);
  }, [id, seriesUid, loadSeries]);

  async function onVerdict(value) {
    setBusy(true);
    try {
      const r = await sendVerdict(id, value);
      setDetail((d) => ({ ...d, study: r.study }));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  if (error) {
    return (
      <main className="study-page-layout">
        <p className="error" role="alert">{String(error.message || error)}</p>
      </main>
    );
  }

  if (!detail) {
    return (
      <main className="study-page-layout loading-state">
        <div className="clinical-spinner"></div>
        <p>Loading clinical study analysis...</p>
      </main>
    );
  }

  const isMR = detail.study.modality === "MR";
  const isCT = detail.study.modality === "CT";
  const ev = detail.evidence || {};
  const urls = detail.evidence_urls || {};
  const overlay = rationale && urls.gradcam_layer_png && ev.gradcam_box
    ? { url: urls.gradcam_layer_png, box: ev.gradcam_box } : null;
  const current = detail.series.find((s) => s.series_uid === seriesUid);

  return (
    <main className="study-page-layout" data-testid="study-page">
      <div className="study-main-viewport">
        {/* Navigation & Study Meta HUD Header */}
        <div className="study-header-hud">
          <div className="hud-left-section">
            <Link to="/" className="btn-back-worklist">
              ← Back to Worklist
            </Link>
            <div className="hud-study-tag">
              <span className="hud-patient mono">{detail.study.patient_id || detail.study.study}</span>
              <span className={`mod-badge mod-${detail.study.modality}`}>
                {detail.study.exam || detail.study.modality}
              </span>
              <span className={`lanetag lane-${detail.study.lane}`}>
                {detail.study.lane_label || detail.study.lane}
              </span>
            </div>
          </div>

          <div className="hud-right-section">
            {isMR && (
              <div className="view-mode-toggle" role="group" aria-label="Viewer Mode">
                <button
                  type="button"
                  className={`mode-btn ${view3D ? "active" : ""}`}
                  onClick={() => setView3D(true)}
                >
                  3D MPR (NiiVue)
                </button>
                <button
                  type="button"
                  className={`mode-btn ${!view3D ? "active" : ""}`}
                  onClick={() => setView3D(false)}
                >
                  2D Slice Stack
                </button>
              </div>
            )}
            {!isMR && detail.series.length > 1 && (
              <div className="series-switch" role="group" aria-label="Series">
                {detail.series.map((s) => (
                  <button
                    key={s.series_uid}
                    type="button"
                    aria-pressed={s.series_uid === seriesUid}
                    onClick={() => setSeriesUid(s.series_uid)}
                  >
                    {s.description}
                  </button>
                ))}
              </div>
            )}
            {!isMR && <Rationale detail={detail} on={rationale} onToggle={() => setRationale((v) => !v)} />}
          </div>
        </div>

        {/* Datastore note shown only when 2D slices are requested and datastore is non-connected */}
        {detail.datastore_note && (!isMR || !view3D) && !isCT && (
          <p className="note datastore-note" role="note" data-testid="datastore-note">
            {detail.datastore_note}
          </p>
        )}

        {/* Primary Medical Imaging Workstation View */}
        <div className="viewer-viewport-container">
          {isCT ? (
            hasCtGradcam(urls)
              ? <CtGradcamView evidence={ev} urls={urls} show={rationale} />
              : <p className="note viewer-empty" data-testid="ct-no-gradcam">No CT image is stored for this study.</p>
          ) : isMR && view3D ? (
            <Suspense fallback={<div className="viewer-loading-placeholder"><div className="clinical-spinner"></div><p>Initializing NiiVue 3D WebGL Engine...</p></div>}>
              <MriViewer3D
                studyId={id}
                isAlzheimer={Boolean(detail.study?.alzheimer || detail.alzheimer || id.toLowerCase().includes("alz"))}
              />
            </Suspense>
          ) : !current || current.instance_count === 0 ? (
            <div className="viewer-empty-placeholder">
              <p>No 2D DICOM instances available in this local test environment.</p>
              {isMR && (
                <button type="button" className="btn-action-primary" onClick={() => setView3D(true)}>
                  Switch to 3D MPR Workstation
                </button>
              )}
            </div>
          ) : !instances ? (
            <div className="viewer-loading-placeholder">
              <div className="clinical-spinner"></div>
              <p>Loading DICOM series instances...</p>
            </div>
          ) : (
            <Suspense fallback={<div className="viewer-loading-placeholder"><div className="clinical-spinner"></div><p>Rendering DICOM viewer...</p></div>}>
              <Viewer instances={instances} overlay={overlay} label={current.description} />
            </Suspense>
          )}
        </div>
      </div>

      {/* Persistent Right Clinical Findings & Verdict Panel */}
      <StudyPanel detail={detail} onVerdict={onVerdict} busy={busy} rationaleOn={rationale} />
    </main>
  );
}
