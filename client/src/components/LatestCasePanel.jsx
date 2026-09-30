import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api.js";
import { rationaleText } from "../Study.jsx";
import CtGradcamView, { hasCtGradcam } from "./CtGradcamView.jsx";
import AbstentionTray, { HumanLaneNote } from "./AbstentionTray.jsx";
import { DraftPanel } from "./DraftPanel.jsx";
import SecondOpinionBar from "./SecondOpinionBar.jsx";
import { LazyView } from "./ErrorBoundary.jsx";
import { FindingSelector, gradcamLayer, selectedCaption } from "./GradcamFindings.jsx";
import { ArrowUpRightIcon } from "./Icons.jsx";
import { Spinner } from "./ui.jsx";
import { PatientLabel } from "../names.jsx";
import { laneName, seriesName } from "../worklist.js";

// Cornerstone (2D) and NiiVue (3D) load only when a study needs them. A chunk that fails
// to load shows "failed to load, Retry" in its own place; the sheet stays.
const loadViewer = () => import("../viewer/Viewer.jsx");
const loadMri = () => import("../viewer/MriViewer3D.jsx");

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
  if (!instances) return <div className="loading-line"><Spinner label="Loading the images" /></div>;
  return (
    <LazyView load={loadViewer} what="Viewer" fallback={<div className="loading-line"><Spinner label="Loading the viewer" /></div>}
              instances={instances} overlay={overlay} label={seriesName(series)} />
  );
}

export default function LatestCasePanel({ studyId, token, me = null, onVerdictChange, onChanged }) {
  const navigate = useNavigate();
  const [detail, setDetail] = useState(null);
  const [selectedFinding, setSelectedFinding] = useState(null);
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
    setSelectedFinding(null);
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

  if (!studyId) return null;
  if (loading) {
    return (
      <div className="case-details-loading">
        <Spinner label="Loading the study" />
        <p>Loading <span className="mono-id">{studyId}</span></p>
      </div>
    );
  }
  if (error || !detail) {
    return <div className="case-details-error"><p className="error-text" role="alert">Could not load study {studyId}: {error}</p></div>;
  }

  const s = detail.study;
  const isMR = s.modality === "MR";
  const isCT = s.modality === "CT";
  const isCR = s.modality === "CR" || s.modality === "DX";
  const ev = detail.evidence || {};
  const urls = detail.evidence_urls || {};
  const v = s.verdict;
  const has3D = Boolean(ev.volumes) && !no3D;
  const layer = gradcamLayer(ev, urls, selectedFinding);
  const heat = layer.drawable;
  const overlay = showGradcam && heat ? { url: layer.url, box: ev.gradcam_box, opacity } : null;
  const finding = s.lane === "FAILED" ? s.error : s.driver_label || s.abstain_reason || "No finding";
  const scored = s.lane !== "ABSTAIN" && s.lane !== "FAILED" && s.acuity != null;
  // A radiologist asked for a second opinion reads and reports; the lane, the verdict and the tray are
  // the study's own reader's.
  const owner = detail.can_request_opinion !== false;

  // A study a reader placed or set aside is refetched: its draft and lane text change.
  const changed = async (row) => {
    setDetail((prev) => ({ ...prev, study: row }));
    if (onVerdictChange) onVerdictChange(studyId, row);
    if (onChanged) onChanged();
    try {
      setDetail(await api.study(token, studyId));
    } catch {
      // The row above is already what the reader sees.
    }
  };

  // Saving a report on a study with second opinions moves that radiologist along in everyone's list.
  const saveReport = async (id, text, reviewed) => {
    const saved = await api.saveDraft(token, id, text, reviewed);
    if (detail.opinions?.length || detail.my_opinion) api.study(token, id).then(setDetail).catch(() => {});
    return saved;
  };

  const analyse = (
    <button type="button" className="pill pill-sm" data-testid="btn-analyse-header"
            onClick={() => navigate(`/studies/${encodeURIComponent(studyId)}`)}>
      Full analysis<ArrowUpRightIcon size={14} />
    </button>
  );

  return (
    <div className="latest-case-panel" data-testid="latest-case-panel">
      <header className="sheet-head">
        <span className={`lanetag lane-${s.lane}`}>{laneName(s.lane, s.lane_label)}</span>
        <h2 className="sheet-title">{finding}</h2>
        <div className="sheet-ids">
          <PatientLabel id={s.patient_id} fallback={s.study} inline detail />
          <span className="chip chip-quiet">{s.pool} pool</span>
          {scored && <span className="chip chip-quiet">Acuity <span className="mono-id">{fmt(s.acuity, 1)}</span></span>}
        </div>
      </header>

      <HumanLaneNote study={s} />
      <SecondOpinionBar detail={detail} token={token} me={me} onChanged={changed} />
      {owner && <AbstentionTray detail={detail} token={token} onChanged={changed} />}

      {s.lane !== "FAILED" && owner && (
        <div className="verdict-block" data-testid="verdict-section">
          <div className="verdict-actions">
            <button type="button" disabled={busy} onClick={() => handleVerdict("agree")} aria-pressed={v?.value === "agree"}
                    className="pill btn-verdict btn-agree">Agree · {laneName(s.lane, s.lane_label)}</button>
            <button type="button" disabled={busy} onClick={() => handleVerdict("disagree")} aria-pressed={v?.value === "disagree"}
                    title="Disagree with the lane and escalate" className="pill btn-verdict btn-disagree">Escalate</button>
          </div>
          {v && (
            <p className="chip chip-quiet" data-testid="sheet-verdict-status">
              <span className="dot" style={{ "--dot": v.value === "agree" ? "var(--ok)" : "var(--alert-ink)" }} />
              {v.value === "agree" ? "Agreed" : "Disagreed"} by {v.by}
            </p>
          )}
        </div>
      )}

      <section className="sheet-viewer">
        {isMR && (
          <div className="viewer-container mri-tumor-view" data-testid="mr-view">
            <div className="viewer-bar"><h3 className="sec-title">Brain MRI</h3>{analyse}</div>
            {has3D ? (
              <LazyView load={loadMri} what="Viewer" fallback={<div className="loading-line"><Spinner label="Loading the 3D viewer" /></div>}
                        studyId={studyId} token={token} onUnavailable={() => setNo3D(true)} />
            ) : (
              <>
                {urls.overlay_png && <img src={urls.overlay_png} alt="Segmentation overlay" className="cxr-base-img" />}
                <p className="note" data-testid="no-3d">
                  No 3D volume is stored for this study. {urls.overlay_png ? "Showing the model's segmentation outline." : ""}
                </p>
              </>
            )}
            <p className="evidence-caption">{rationaleText(detail)}</p>
          </div>
        )}

        {isCR && (
          <div className="viewer-container cxr-view" data-testid="cxr-view">
            <div className="viewer-bar"><h3 className="sec-title">Chest X-ray</h3>{analyse}</div>
            {heat && (
              <div className="glass-toolbar">
                <button type="button" className="pill pill-sm btn-gradcam-toggle" aria-pressed={showGradcam}
                        onClick={() => setShowGradcam(!showGradcam)} data-testid="gradcam-toggle"
                        title="A sanity check on why the study was placed where it was, not a localisation.">
                  Grad-CAM {showGradcam ? "on" : "off"}
                </button>
                {showGradcam && (
                  <label className="slider-label">
                    <span>Opacity {Math.round(opacity * 100)}%</span>
                    <input type="range" min="0.1" max="1" step="0.05" value={opacity}
                           onChange={(e) => setOpacity(parseFloat(e.target.value))} aria-label="Grad-CAM opacity" />
                  </label>
                )}
              </div>
            )}
            <FindingSelector ev={ev} selected={selectedFinding} onSelect={setSelectedFinding} />
            <SeriesView token={token} detail={detail} overlay={overlay} />
            <p className="evidence-caption">{selectedCaption(ev, selectedFinding) || rationaleText(detail)}</p>
          </div>
        )}

        {isCT && (
          <div className="viewer-container ct-view" data-testid="ct-view">
            <div className="viewer-bar"><h3 className="sec-title">Head CT</h3>{analyse}</div>
            {hasCtGradcam(urls) ? (
              <>
                <div className="glass-toolbar">
                  <button type="button" className="pill pill-sm btn-gradcam-toggle" aria-pressed={showGradcam}
                          onClick={() => setShowGradcam(!showGradcam)} data-testid="ct-gradcam-toggle"
                          title="A sanity check on why the study was placed where it was, not a localisation.">
                    Grad-CAM {showGradcam ? "on" : "off"}
                  </button>
                </div>
                <CtGradcamView evidence={ev} urls={urls} show={showGradcam} initialMode="single" />
                {detail.decision_reason && <p className="evidence-caption">{detail.decision_reason}</p>}
              </>
            ) : (
              <>
                <SeriesView token={token} detail={detail} overlay={null} />
                <p className="note viewer-empty" data-testid="ct-no-gradcam">
                  {s.lane === "FAILED"
                    ? "Processing failed, so there is no Grad-CAM for this study."
                    : "No Grad-CAM image is stored for this study."}
                </p>
                <p className="evidence-caption">{rationaleText(detail)}</p>
              </>
            )}
          </div>
        )}
      </section>

      <section className="sheet-findings">
        <h3 className="sec-title">Findings</h3>
        {detail.findings && detail.findings.length > 0 ? (
          <table className="findings-table">
            <thead><tr><th>Finding</th><th className="num">Signal</th><th className="num">Urgency</th></tr></thead>
            <tbody>
              {detail.findings.map((f) => (
                <tr key={f.name} className={f.name === s.driver ? "driver-row" : ""}>
                  <td className="finding-name">
                    {f.label || f.name}
                    {f.name === s.driver && <span className="chip chip-quiet driver-tag">Driver</span>}
                  </td>
                  <td className="mono-id num">{fmt(f.signal)}</td>
                  <td className="mono-id num">{fmt(f.urgency, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="note">{s.abstain_reason || "No abnormal findings flagged by the model."}</p>
        )}
        {isMR && ev.volumes_cm3 && (
          <div className="ct-chips">
            <span className="chip chip-quiet">Whole tumour {ev.volumes_cm3.whole_tumour} cm3</span>
            <span className="chip chip-quiet">Core {ev.volumes_cm3.tumour_core} cm3</span>
            <span className="chip chip-quiet">Enhancing {ev.volumes_cm3.enhancing} cm3</span>
          </div>
        )}
      </section>

      <DraftPanel detail={detail} saveDraft={saveReport} />
    </div>
  );
}
