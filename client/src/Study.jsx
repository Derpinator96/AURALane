import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import AbstentionTray, { HumanLaneNote } from "./components/AbstentionTray.jsx";
import CtGradcamView, { hasCtGradcam } from "./components/CtGradcamView.jsx";
import { FindingSelector, gradcamLayer, selectedCaption } from "./components/GradcamFindings.jsx";
import AnnotationsPanel from "./components/AnnotationsPanel.jsx";
import SecondOpinionBar from "./components/SecondOpinionBar.jsx";
import NoteEditorModal from "./components/NoteEditorModal.jsx";
import { DraftPanel } from "./components/DraftPanel.jsx";
import { LazyView } from "./components/ErrorBoundary.jsx";
import { api, loadSession } from "./api.js";
import { laneName, timeUTC } from "./worklist.js";
import { CheckIcon, ChevronIcon, ClockIcon } from "./components/Icons.jsx";
import { Spinner } from "./components/ui.jsx";

// The viewer pulls in Cornerstone and its codecs; load it only on this page. A chunk that
// fails to load shows "failed to load, Retry" in its place instead of a blank app.
const loadViewer = () => import("./viewer/Viewer.jsx");
const loadMri = () => import("./viewer/MriViewer3D.jsx");
const loadingLine = <div className="loading-line"><Spinner label="Loading" /></div>;

export { DraftPanel };

const fmt = (v, d = 3) => (v == null ? "--" : Number(v).toFixed(d));

function Patient({ study }) {
  return <span className="mono-id bold">{study.patient_id || study.study}</span>;
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

// The rationale toggle and opacity slider (part "controls") and its caption (part "caption").
// The page puts the controls above the image and the caption under it.
export function Rationale({ detail, on, onToggle, opacity, onOpacity, selected = null, part = "all" }) {
  const ev = detail.evidence || {};
  const urls = detail.evidence_urls || {};
  const drawable = gradcamLayer(ev, urls, selected).drawable;
  const caption = (
    <p className="note" data-testid="rationale-caption">
      {selectedCaption(ev, selected) || rationaleText(detail)}
      {ev.gradcam_note ? ` ${ev.gradcam_note}` : ""}
    </p>
  );
  if (part === "caption") return caption;
  return (
    <div className="rationale" data-testid="rationale">
      <button type="button" aria-pressed={on} disabled={!drawable && !urls.overlay_png}
              onClick={onToggle} data-testid="rationale-toggle" className="pill pill-sm btn-rationale-toggle"
              title="A sanity check on why the study was placed where it was, not a localisation.">
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
      {part === "all" && caption}
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
                             token = null, me = null, onStudyChanged = () => {}, onLeft = () => {},
                             annotations = [], activeAnnotationId = null, onSelectAnnotation = null,
                             onEditAnnotation = null, onDeleteAnnotation = null,
                             isAddNoteMode = false, onToggleAddNoteMode = null }) {
  const s = detail.study;
  const brain = s.modality === "MR";
  const scored = s.lane !== "ABSTAIN" && s.lane !== "FAILED";
  // A radiologist asked for a second opinion reads and reports; the verdict and the tray are the reader's.
  const owner = detail.can_request_opinion !== false;

  // A bento of tiles. The decision (lane, finding, acuity and the verdict) leads the tall column beside
  // the images so it is on screen when the study opens; the draft and the study's details sit below.
  return (
    <aside className="study-analysis-sidebar" data-testid="study-panel">
      <div className="study-hero-side">
        <div className="study-hero-scroll">
          <section className={`bento-tile analysis-decision lane-${s.lane}`} aria-label="Decision">
            <div className="decision-top">
              <span className={`lanetag lane-${s.lane}`}>{laneName(s.lane, s.lane_label)}</span>
              {s.clock && <span className="chip chip-quiet lane-sla-target"><ClockIcon size={13} /> {s.clock}</span>}
            </div>
            <div className="decision-main">
              <div className="decision-finding">
                <span className="decision-kicker">Driving finding</span>
                <h2 className="decision-title">{s.driver_label || "--"}</h2>
              </div>
              <div className="decision-acuity">
                <span className="decision-kicker">Acuity</span>
                <strong className="decision-number">{scored ? fmt(s.acuity, 1) : "--"}</strong>
              </div>
            </div>
            {s.assigned_name && <p className="lane-assigned">Assigned to {s.assigned_name}</p>}
            {s.lane === "FAILED" && <p className="error-banner">Processing failed: {s.error}</p>}
            <SecondOpinionBar detail={detail} token={token} me={me} onChanged={onStudyChanged} />
            {s.lane === "FAILED" ? (
              <p className="note">No lane assigned. The study is still in PACS; read it there.</p>
            ) : owner && (
              <Verdict study={s} onVerdict={onVerdict} busy={busy} />
            )}
          </section>

          <HumanLaneNote study={s} />
          {owner && <AbstentionTray detail={detail} token={token} me={me} onChanged={onStudyChanged} onLeft={onLeft} />}

          <section className="bento-tile study-findings-card" aria-label="Findings">
            <h4 className="card-section-title">Findings</h4>
            {detail.findings.length === 0 ? (
              <p className="note" data-testid="no-findings">
                {s.lane === "FAILED" ? "None: processing did not reach the model output." : "None reported."}
              </p>
            ) : (
              <div className="findings-scroll">
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
                          <td className="mono-id num bold">{fmt(f.signal)}</td>
                          <td className="mono-id num text-soft">{fmt(f.urgency, 2)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      </div>

      <div className="bento-tile study-draft"><DraftPanel detail={detail} saveDraft={saveDraft} /></div>

      <div className="study-lower-side">
        <div className="bento-tile study-facts-card">
          <h4 className="card-section-title">Study</h4>
          <dl className="facts-grid">
            <dt>Patient (pseudonym)</dt><dd><Patient study={s} /></dd>
            <dt>Exam</dt><dd>{s.exam}</dd>
            <dt>Confidence</dt>
            <dd>
              {brain ? "Not reported: the brain model reports volumes, not a probability"
                     : <span className="mono-id">{fmt(s.confidence)}</span>}
            </dd>
            <dt>Model</dt><dd className="mono-id">{s.model_id || "--"}</dd>
            <dt>Arrived</dt><dd className="mono">{s.arrived ? `${timeUTC(s.arrived)} UTC` : "--"}</dd>
          </dl>
          <RegionalContext regional={detail.evidence?.regional} driver={s.driver}
                           driverLabel={s.driver_label} />
        </div>

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
        {s.source && <div className="study-source-footer"><span>Source: <span className="mono-id">{s.source}</span></span></div>}
      </div>
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
  const [ctView, setCtView] = useState("gradcam");   // head CT: "gradcam" | "3d"
  const [selectedFinding, setSelectedFinding] = useState(null);   // chest Grad-CAM finding; null is the driver
  const navigate = useNavigate();

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

  // A reader placed the study, set it aside or sent it for a second read: reload it.
  async function onStudyChanged(row) {
    setDetail((d) => ({ ...d, study: row }));
    try {
      setDetail(await load(id));
    } catch {
      // The row above is already what the reader sees.
    }
  }

  // Saving a report on a study with second opinions moves that radiologist along in everyone's list.
  async function saveAndRefresh(...args) {
    const saved = await saveDraft(...args);
    if (detail?.opinions?.length || detail?.my_opinion) load(id).then(setDetail).catch(() => {});
    return saved;
  }

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
    return <main className="study-page-layout loading-state"><Spinner label="Loading the study" /><p>Loading the study</p></main>;
  }

  const isMR = detail.study.modality === "MR";
  const isCT = detail.study.modality === "CT";
  const has3D = Boolean(detail.evidence?.volumes);
  const hasCtVolume = isCT && Boolean(detail.evidence?.volumes?.CT);
  const show3D = (isMR && has3D && view3D) || (hasCtVolume && (ctView === "3d" || !hasCtGradcam(detail.evidence_urls || {})));
  const ev = detail.evidence || {};
  const urls = detail.evidence_urls || {};
  const layer = gradcamLayer(ev, urls, selectedFinding);
  const overlay = rationale && layer.drawable ? { url: layer.url, box: ev.gradcam_box, opacity } : null;
  const current = detail.series.find((s) => s.series_uid === seriesUid);

  return (
    <main className="study-page-layout" data-testid="study-page">
      <div className="study-main-viewport">
        <div className="study-header-hud">
          <div className="hud-left-section">
            <Link to="/" className="pill pill-sm btn-back-worklist"><ChevronIcon size={14} className="flip" />Back to worklist</Link>
            <div className="hud-study-tag">
              <span className="hud-patient mono-id">{detail.study.patient_id || detail.study.study}</span>
              <span className={`mod-badge mod-${detail.study.modality}`}>{detail.study.exam || detail.study.modality}</span>
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
            {hasCtVolume && hasCtGradcam(detail.evidence_urls || {}) && (
              <div className="view-mode-toggle" role="group" aria-label="Viewer mode">
                <button type="button" className={`mode-btn ${ctView === "gradcam" ? "active" : ""}`}
                        onClick={() => setCtView("gradcam")}>Grad-CAM</button>
                <button type="button" className={`mode-btn ${ctView === "3d" ? "active" : ""}`}
                        onClick={() => setCtView("3d")}>3D volume</button>
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

        <div className="study-controls">
          <Rationale detail={detail} on={rationale} onToggle={() => setRationale((v) => !v)}
                     opacity={opacity} onOpacity={setOpacity} selected={selectedFinding} part="controls" />
          <FindingSelector ev={ev} selected={selectedFinding} onSelect={setSelectedFinding} />
        </div>

        <div className="viewer-viewport-container">
          {isCT && hasCtGradcam(urls) && !show3D ? (
            <CtGradcamView evidence={ev} urls={urls} show={rationale} {...noteProps} />
          ) : show3D ? (
            <LazyView load={loadMri} what="Viewer" fallback={loadingLine}
                      studyId={id} token={token} modality={isCT ? "CT" : "MR"}
                      onUnavailable={() => { setView3D(false); setCtView("gradcam"); }}
                      onEditAnnotation={handleEditAnnotation}
                      onDeleteAnnotation={handleDeleteAnnotation} {...noteProps} />
          ) : !current || current.instance_count === 0 ? (
            <div className="viewer-empty-placeholder"><p>No images for this study in this runtime.</p></div>
          ) : !instances ? (
            loadingLine
          ) : (
            <LazyView load={loadViewer} what="Viewer" fallback={loadingLine}
                      instances={instances} overlay={overlay} label={current.description} {...noteProps} />
          )}
        </div>

        <div className="study-captions">
          <Rationale detail={detail} selected={selectedFinding} part="caption" />
          {detail.datastore_note && !show3D && (
            <p className="note datastore-note" role="note" data-testid="datastore-note">{detail.datastore_note}</p>
          )}
        </div>
      </div>

      <StudyPanel detail={detail} onVerdict={onVerdict} busy={busy} rationaleOn={rationale}
                  saveDraft={saveDraft && saveAndRefresh} token={activeToken} me={loadSession()?.user?.email}
                  onStudyChanged={onStudyChanged} onLeft={() => navigate("/")} annotations={annotations}
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
