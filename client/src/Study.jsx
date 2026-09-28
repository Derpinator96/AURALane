import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import CtGradcamView, { hasCtGradcam } from "./components/CtGradcamView.jsx";
import AnnotationsPanel from "./components/AnnotationsPanel.jsx";
import NoteEditorModal from "./components/NoteEditorModal.jsx";
import { api, loadSession } from "./api.js";
import { timeUTC } from "./worklist.js";
import { CheckIcon, ClockIcon } from "./components/Icons.jsx";

// The viewer pulls in Cornerstone and its codecs; load it only on this page.
const Viewer = lazy(() => import("./viewer/Viewer.jsx"));
const MriViewer3D = lazy(() => import("./viewer/MriViewer3D.jsx"));

const fmt = (v, d = 3) => (v == null ? "--" : Number(v).toFixed(d));

function Patient({ study }) {
  return <span className="mono bold">{study.patient_id || study.study}</span>;
}

// What the rationale is for this study, in words. Grad-CAM for chest, the
// segmentation outline for brain, and for head CT the model's own slice result
// (no Grad-CAM is wired for CT yet). Said plainly when there is nothing to draw.
export function rationaleText(detail) {
  const ev = detail.evidence || {};
  const urls = detail.evidence_urls || {};
  if (urls.gradcam_layer_png) {
    if (ev.gradcam_coverage === 0) {
      return `Grad-CAM found no region at or above the display threshold for ${ev.gradcam_finding} on this image, so nothing is drawn.`;
    }
    return `Grad-CAM for ${ev.gradcam_finding}, the finding that set the lane, drawn on ${(ev.gradcam_coverage * 100).toFixed(1)}% of the model's view.`;
  }
  if (urls.overlay_png) {
    return `Segmentation outline on axial slice ${ev.axial_index}, the slice with the largest tumour area.`;
  }
  if (ev.ct) {
    return `No Grad-CAM for head CT yet. The model's strongest slice is index ${ev.ct.top_slice_index} of ${ev.ct.n_slices}, dominant subtype ${ev.ct.dominant_subtype}.`;
  }
  return "No rationale image for this study.";
}

export function Rationale({ detail, on, onToggle, opacity, onOpacity }) {
  const ev = detail.evidence || {};
  const urls = detail.evidence_urls || {};
  const drawable = Boolean(urls.gradcam_layer_png && ev.gradcam_coverage !== 0);
  return (
    <div className="rationale" data-testid="rationale">
      <button type="button" aria-pressed={on} disabled={!drawable && !urls.overlay_png}
              onClick={onToggle} data-testid="rationale-toggle" className="btn-rationale-toggle">
        Triage rationale: {on ? "ON" : "OFF"}
      </button>
      {on && drawable && (
        <label className="slider-label">
          <span>Opacity {Math.round(opacity * 100)}%</span>
          <input type="range" min="0.1" max="1" step="0.05" value={opacity}
                 onChange={(e) => onOpacity(parseFloat(e.target.value))}
                 aria-label="Grad-CAM opacity" data-testid="rationale-opacity" />
        </label>
      )}
      <p className="note" data-testid="rationale-caption">
        {rationaleText(detail)}{" "}
        {(drawable || urls.overlay_png) && "A sanity check on why the study was placed where it was, not a localisation."}
        {ev.gradcam_note ? ` ${ev.gradcam_note}` : ""}
      </p>
    </div>
  );
}

function Verdict({ study, onVerdict, busy }) {
  const v = study.verdict;
  return (
    <div className="study-verdict-section">
      <div className="verdict-header">
        <h4 className="verdict-heading">Your call on the lane</h4>
        <span className="verdict-sub">Audited</span>
      </div>
      <div className="verdict-action-buttons">
        <button type="button" disabled={busy} aria-pressed={v?.value === "agree"}
                onClick={() => onVerdict("agree")}
                className={`btn-verdict btn-agree ${v?.value === "agree" ? "selected" : ""}`}>
          {v?.value === "agree" && <CheckIcon size={14} />} Agree with the lane
        </button>
        <button type="button" disabled={busy} aria-pressed={v?.value === "disagree"}
                onClick={() => onVerdict("disagree")}
                className={`btn-verdict btn-disagree ${v?.value === "disagree" ? "selected" : ""}`}>
          {v?.value === "disagree" && <CheckIcon size={14} />} Disagree
        </button>
      </div>
      <div className="verdict-audit-badge" data-testid="verdict-status">
        {v ? (
          <span className="audit-ok">{v.value === "agree" ? "Agreed" : "Disagreed"} by {v.by} at {v.at}</span>
        ) : (
          <span className="audit-pending">No verdict yet.</span>
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

// The draft the template wrote (no language model), editable by the reader.
// Saved and "Mark as reviewed" go to the API and are audited; the text is not
// in the audit.
export function DraftPanel({ detail, saveDraft }) {
  const s = detail.study;
  const saved = detail.draft_review;
  const [text, setText] = useState(saved?.text ?? detail.draft ?? "");
  const [review, setReview] = useState(saved || null);
  const [state, setState] = useState(null);

  useEffect(() => {
    setText(detail.draft_review?.text ?? detail.draft ?? "");
    setReview(detail.draft_review || null);
    setState(null);
  }, [detail.study.study]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!detail.draft) return null;

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setState("Copied.");
    } catch {
      setState("The browser did not allow copying; select the text instead.");
    }
  }

  async function save(reviewed) {
    setState("Saving.");
    try {
      const r = await saveDraft(s.study, text, reviewed);
      setReview(r.draft_review);
      setState(null);
    } catch (e) {
      setState(`Not saved: ${e.message}`);
    }
  }

  return (
    <section className="draft-panel" data-testid="draft-panel" aria-label="Draft report">
      <h4 className="card-section-title">Draft, template generated, radiologist to review</h4>
      <p className="draft-meta">
        Driving finding: <strong>{s.driver_label || "none"}</strong>. Lane: <strong>{s.lane_label || s.lane}</strong>.
      </p>
      <textarea className="draft-text mono" value={text} rows={11} data-testid="draft-text"
                aria-label="Draft text" onChange={(e) => { setText(e.target.value); setState(null); }} />
      <div className="draft-actions">
        <button type="button" onClick={copy}>Copy</button>
        {saveDraft && <button type="button" onClick={() => save(false)}>Save edits</button>}
        {saveDraft && (
          <button type="button" className="btn-primary" onClick={() => save(true)}
                  data-testid="draft-reviewed">Mark as reviewed</button>
        )}
      </div>
      <p className="note" data-testid="draft-status">
        {state || (review?.reviewed ? `Reviewed by ${review.by} at ${review.at}.`
                   : review ? `Edited by ${review.by} at ${review.at}, not yet marked reviewed.`
                   : "Not reviewed.")}
      </p>
    </section>
  );
}

// Chest only: the site's regional prior (core/regional.py), shown for the
// finding that set the lane. The factor is exactly what multiplied its signal.
export function RegionalContext({ regional, driver, driverLabel }) {
  if (!regional) return null;
  let text;
  if (!regional.applied) {
    text = `Regional context: ${regional.reason === "no site state set" ? "no site state set" : "off"}`;
  } else {
    const f = regional.factors?.[driver];
    text = f
      ? `Regional context: ${regional.state}, x${f.factor.toFixed(2)}`
      : `Regional context: ${regional.state}, x1.00 (no regional prior for ${driverLabel || "this finding"})`;
  }
  return (
    <p className="note" data-testid="regional-context">
      {text}
      {regional.applied && (
        <span className="regional-basis"> GBD 2023 prevalence in the state against India's, square-rooted
          and held between x0.80 and x1.25, applied to the signal after the z-score.</span>
      )}
    </p>
  );
}

export function StudyPanel({ detail, onVerdict, busy, rationaleOn = true, saveDraft,
                             annotations = [], activeAnnotationId = null, onSelectAnnotation = null,
                             onEditAnnotation = null, onDeleteAnnotation = null,
                             isAddNoteMode = false, onToggleAddNoteMode = null }) {
  const s = detail.study;
  const brain = s.modality === "MR";

  return (
    <aside className="study-analysis-sidebar" data-testid="study-panel">
      <div className={`analysis-lane-card lane-${s.lane}`}>
        <div className="lane-header-row">
          <span className="lane-badge-text">{s.lane_label || s.lane}</span>
          {s.clock && <span className="lane-sla-target mono"><ClockIcon size={13} /> {s.clock}</span>}
        </div>
        <div className="lane-meta-row">
          <span className="meta-acuity">
            Acuity: <strong className="mono">{s.lane === "ABSTAIN" || s.lane === "FAILED" ? "--" : fmt(s.acuity, 1)}</strong>
          </span>
          <span className="meta-driver">Driving finding: <strong>{s.driver_label || "--"}</strong></span>
        </div>
        {s.assigned_name && <p className="lane-assigned">Assigned to {s.assigned_name}</p>}
      </div>

      <DraftPanel detail={detail} saveDraft={saveDraft} />

      <div className="study-facts-card">
        <h4 className="card-section-title">Study</h4>
        <dl className="facts-grid">
          <dt>Patient (pseudonym)</dt><dd><Patient study={s} /></dd>
          <dt>Exam</dt><dd>{s.exam}</dd>
          <dt>Driving finding</dt><dd>{s.driver_label || "--"}</dd>
          <dt>Acuity</dt>
          <dd className="mono">{s.lane === "ABSTAIN" || s.lane === "FAILED" ? "--" : fmt(s.acuity, 1)}</dd>
          <dt>Confidence</dt>
          <dd>
            {brain ? "None: the brain model reports volumes, not a probability"
                   : <><span className="mono">{fmt(s.confidence)}</span> <span className="note">temperature-scaled model output for the driving finding</span></>}
          </dd>
          <dt>Model</dt><dd className="mono">{s.model_id || "--"}</dd>
          <dt>Arrived</dt><dd className="mono">{s.arrived ? `${timeUTC(s.arrived)} UTC` : "--"}</dd>
        </dl>
      </div>
      <RegionalContext regional={detail.evidence?.regional} driver={s.driver}
                       driverLabel={s.driver_label} />

      {/* Persistent Clinician Pinpoint Annotations Card */}
      <AnnotationsPanel
        annotations={annotations}
        activeAnnotationId={activeAnnotationId}
        onSelectAnnotation={onSelectAnnotation}
        onEditAnnotation={onEditAnnotation}
        onDeleteAnnotation={onDeleteAnnotation}
        isAddNoteMode={isAddNoteMode}
        onToggleAddNoteMode={onToggleAddNoteMode}
      />

      {rationaleOn && detail.evidence_urls?.overlay_png && <SegmentationRationale detail={detail} />}
      {s.lane === "FAILED" && <p className="error-banner">Processing failed: {s.error}</p>}
      {s.abstain_reason && (
        <div className="abstain-notice-box" data-testid="abstain-reason">
          <strong>No lane assigned:</strong> {s.abstain_reason}. A radiologist picks the lane.
        </div>
      )}

      <div className="study-findings-card">
        <div className="findings-header">
          <h4 className="card-section-title">Findings</h4>
          <span className="findings-sub">Signal 0 to 1 against each finding's own operating point</span>
        </div>
        {detail.findings.length === 0 ? (
          <p className="note" data-testid="no-findings">
            {s.lane === "FAILED" ? "None: processing did not reach the model output." : "None reported."}
          </p>
        ) : (
          <table className="findings-table-modern">
            <thead>
              <tr><th>Finding</th><th aria-label="Signal bar" /><th className="num">Signal</th><th className="num">Urgency</th></tr>
            </thead>
            <tbody>
              {detail.findings.map((f) => {
                const isDriver = f.name === s.driver;
                const sig = f.signal != null ? Number(f.signal) : 0;
                return (
                  <tr key={f.name} className={isDriver ? "driver-finding-row" : ""}>
                    <td className="finding-name-cell">
                      <span>{f.label}</span>
                      {isDriver && <span className="driver-pill">DRIVER</span>}
                    </td>
                    <td className="meter-cell">
                      <div className="signal-track">
                        <div className={`signal-bar ${isDriver ? "bar-driver" : "bar-normal"}`}
                             style={{ width: `${Math.min(100, Math.max(0, sig * 100))}%` }} />
                      </div>
                    </td>
                    <td className="mono num bold">{fmt(f.signal)}</td>
                    <td className="mono num text-soft">{fmt(f.urgency, 2)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {s.lane === "FAILED" ? (
        <p className="note">No lane assigned. The study is still in PACS; read it there.</p>
      ) : (
        <Verdict study={s} onVerdict={onVerdict} busy={busy} />
      )}

      {s.source && <div className="study-source-footer mono"><span>Source: {s.source}</span></div>}
    </aside>
  );
}

export default function Study({ load, loadSeries, sendVerdict, saveDraft, token }) {
  const { id } = useParams();
  const activeToken = token || loadSession()?.token;
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const [seriesUid, setSeriesUid] = useState(null);
  const [instances, setInstances] = useState(null);
  const [rationale, setRationale] = useState(true);
  const [opacity, setOpacity] = useState(0.6);
  const [busy, setBusy] = useState(false);
  const [view3D, setView3D] = useState(true);

  // Clinician Pinpoint Annotations State
  const [annotations, setAnnotations] = useState([]);
  const [selectedAnnotation, setSelectedAnnotation] = useState(null);
  const [isAddNoteMode, setIsAddNoteMode] = useState(false);
  const [noteModalOpen, setNoteModalOpen] = useState(false);
  const [editingAnnotationData, setEditingAnnotationData] = useState(null);
  const [savingNote, setSavingNote] = useState(false);

  useEffect(() => {
    load(id).then((d) => {
      setDetail(d);
      setSeriesUid(d.series[0]?.series_uid || null);
      setView3D(Boolean(d.evidence?.volumes));
    }).catch(setError);
  }, [id, load]);

  // Load persistent study annotations from backend
  const refreshAnnotations = useCallback(() => {
    if (!id) return;
    api.getAnnotations(activeToken, id)
      .then((res) => { if (res && res.annotations) setAnnotations(res.annotations); })
      .catch((err) => { console.warn("Notice: could not load study annotations:", err); });
  }, [id, activeToken]);

  useEffect(() => { refreshAnnotations(); }, [refreshAnnotations]);

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

  // Pinpoint Annotation Handlers
  const handleRequestNewNote = (draftData) => {
    setEditingAnnotationData(draftData);
    setNoteModalOpen(true);
  };

  const handleEditAnnotation = (ann) => {
    setEditingAnnotationData(ann);
    setNoteModalOpen(true);
  };

  const handleSaveNote = async (data) => {
    setSavingNote(true);
    try {
      if (data.id) {
        const res = await api.updateAnnotation(activeToken, data.id, {
          note_text: data.note_text,
          segmentation_region: data.segmentation_region,
          metadata: data.metadata,
        });
        if (res && res.annotation) {
          setAnnotations((prev) => prev.map((a) => (a.id === data.id ? res.annotation : a)));
        }
      } else {
        const res = await api.createAnnotation(activeToken, id, data);
        if (res && res.annotation) {
          setAnnotations((prev) => [...prev, res.annotation]);
          setSelectedAnnotation(res.annotation);
        }
      }
      setNoteModalOpen(false);
      setEditingAnnotationData(null);
      setIsAddNoteMode(false);
    } catch (err) {
      alert("Error saving note: " + (err.message || err));
    } finally {
      setSavingNote(false);
    }
  };

  const handleDeleteAnnotation = async (annId) => {
    try {
      await api.deleteAnnotation(activeToken, annId);
      setAnnotations((prev) => prev.filter((a) => a.id !== annId && a.annotation_id !== annId));
      if (selectedAnnotation?.id === annId || selectedAnnotation?.annotation_id === annId) {
        setSelectedAnnotation(null);
      }
    } catch (err) {
      alert("Error deleting note: " + (err.message || err));
    }
  };

  const handleSelectAnnotation = (ann) => setSelectedAnnotation(ann);
  const noteProps = {
    annotations, selectedAnnotation, onSelectAnnotation: handleSelectAnnotation,
    onRequestNewNote: handleRequestNewNote, isAddNoteMode,
    onToggleAddNoteMode: () => setIsAddNoteMode((v) => !v),
  };

  if (error) {
    return <main className="study-page-layout"><p className="error" role="alert">{String(error.message || error)}</p></main>;
  }
  if (!detail) {
    return <main className="study-page-layout loading-state"><p>Loading the study.</p></main>;
  }

  const isMR = detail.study.modality === "MR";
  const isCT = detail.study.modality === "CT";
  const has3D = Boolean(detail.evidence?.volumes);
  const show3D = isMR && has3D && view3D;
  const ev = detail.evidence || {};
  const urls = detail.evidence_urls || {};
  const overlay = rationale && urls.gradcam_layer_png && ev.gradcam_box && ev.gradcam_coverage !== 0
    ? { url: urls.gradcam_layer_png, box: ev.gradcam_box, opacity } : null;
  const current = detail.series.find((s) => s.series_uid === seriesUid);

  return (
    <main className="study-page-layout" data-testid="study-page">
      <div className="study-main-viewport">
        <div className="study-header-hud">
          <div className="hud-left-section">
            <Link to="/" className="btn-back-worklist">Back to worklist</Link>
            <div className="hud-study-tag">
              <span className="hud-patient mono">{detail.study.patient_id || detail.study.study}</span>
              <span className={`mod-badge mod-${detail.study.modality}`}>{detail.study.exam || detail.study.modality}</span>
              <span className={`lanetag lane-${detail.study.lane}`}>{detail.study.lane_label || detail.study.lane}</span>
            </div>
          </div>
          <div className="hud-right-section">
            {isMR && has3D && (
              <div className="view-mode-toggle" role="group" aria-label="Viewer mode">
                <button type="button" className={`mode-btn ${view3D ? "active" : ""}`} onClick={() => setView3D(true)}>
                  3D (NiiVue)
                </button>
                <button type="button" className={`mode-btn ${!view3D ? "active" : ""}`} onClick={() => setView3D(false)}>
                  2D slices
                </button>
              </div>
            )}
            {detail.series.length > 1 && !show3D && (
              <div className="series-switch" role="group" aria-label="Series">
                {detail.series.map((s) => (
                  <button key={s.series_uid} type="button" aria-pressed={s.series_uid === seriesUid}
                          onClick={() => setSeriesUid(s.series_uid)}>{s.description}</button>
                ))}
              </div>
            )}
          </div>
        </div>

        <Rationale detail={detail} on={rationale} onToggle={() => setRationale((v) => !v)}
                   opacity={opacity} onOpacity={setOpacity} />

        {detail.datastore_note && !show3D && (
          <p className="note datastore-note" role="note" data-testid="datastore-note">{detail.datastore_note}</p>
        )}

        <div className="viewer-viewport-container">
          {isCT && hasCtGradcam(urls) ? (
            <CtGradcamView evidence={ev} urls={urls} show={rationale} {...noteProps} />
          ) : show3D ? (
            <Suspense fallback={<p className="note">Loading the 3D viewer.</p>}>
              <MriViewer3D studyId={id} token={token} onUnavailable={() => setView3D(false)}
                           onEditAnnotation={handleEditAnnotation}
                           onDeleteAnnotation={handleDeleteAnnotation} {...noteProps} />
            </Suspense>
          ) : !current || current.instance_count === 0 ? (
            <div className="viewer-empty-placeholder"><p>No images for this study in this runtime.</p></div>
          ) : !instances ? (
            <p className="note">Loading the series.</p>
          ) : (
            <Suspense fallback={<p className="note">Loading the viewer.</p>}>
              <Viewer instances={instances} overlay={overlay} label={current.description} {...noteProps} />
            </Suspense>
          )}
        </div>
      </div>

      <StudyPanel detail={detail} onVerdict={onVerdict} busy={busy} rationaleOn={rationale}
                  saveDraft={saveDraft} annotations={annotations}
                  activeAnnotationId={selectedAnnotation?.id || selectedAnnotation?.annotation_id}
                  onSelectAnnotation={handleSelectAnnotation} onEditAnnotation={handleEditAnnotation}
                  onDeleteAnnotation={handleDeleteAnnotation} isAddNoteMode={isAddNoteMode}
                  onToggleAddNoteMode={() => setIsAddNoteMode((v) => !v)} />

      {/* Persistent Spatially-Anchored Note Editor Modal */}
      <NoteEditorModal
        isOpen={noteModalOpen}
        initialData={editingAnnotationData}
        onSave={handleSaveNote}
        onCancel={() => { setNoteModalOpen(false); setEditingAnnotationData(null); }}
        busy={savingNote}
      />
    </main>
  );
}
