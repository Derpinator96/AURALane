import { lazy, Suspense, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

// The viewer pulls in Cornerstone and its codecs; load it only on this page.
const Viewer = lazy(() => import("./viewer/Viewer.jsx"));

const fmt = (v, d = 3) => (v == null ? "--" : Number(v).toFixed(d));

// Patient identity: the API returns the pseudonymous ID only. Resolving it to a
// name is the local identity map's job (sim/edge/identity.py, resolve_study),
// which runs inside the hospital and is not exposed by this API yet. When it
// is, it plugs in here; until then the pseudonym is shown and nothing is
// invented.
function Patient({ study }) {
  return <span className="mono">{study.patient_id || study.study}</span>;
}

function Rationale({ detail, on, onToggle }) {
  const ev = detail.evidence || {};
  const urls = detail.evidence_urls || {};
  const available = Boolean(urls.gradcam_layer_png || urls.overlay_png);
  return (
    <div className="rationale">
      <button type="button" aria-pressed={on} disabled={!available} onClick={onToggle}
              data-testid="rationale-toggle">
        Triage rationale: {on ? "on" : "off"}
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
    <div className="verdict">
      <h3>Lane assignment</h3>
      <div className="verdict-buttons">
        <button type="button" disabled={busy} aria-pressed={v?.value === "agree"}
                onClick={() => onVerdict("agree")}>Agree</button>
        <button type="button" disabled={busy} aria-pressed={v?.value === "disagree"}
                onClick={() => onVerdict("disagree")}>Disagree</button>
      </div>
      <p className="note" data-testid="verdict-status">
        {v ? `${v.value === "agree" ? "Agreed" : "Disagreed"} by ${v.by} at ${v.at}` : "No verdict yet."}
      </p>
    </div>
  );
}

// The brain rationale is a rendered slice, not a layer on the viewer, so it
// sits in the panel and leaves the viewer its full size.
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
  return (
    <aside className="panel">
      <div className={`panel-lane lane-${s.lane}`}>
        <span className="lanename">{s.lane_label}</span>
        <span className="clock">{s.clock}</span>
      </div>
      <dl className="facts">
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
      </dl>
      {rationaleOn && detail.evidence_urls?.overlay_png && <SegmentationRationale detail={detail} />}
      {s.lane === "FAILED" && <p className="error">Processing failed: {s.error}</p>}
      <h3>Findings</h3>
      {detail.findings.length === 0 ? (
        <p className="note" data-testid="no-findings">
          {s.lane === "FAILED" ? "None: processing did not reach the model output." : "None reported."}
        </p>
      ) : (<>
      <p className="note">Signal 0 to 1 against the model's own operating point, not a probability of disease.</p>
      <table className="findings">
        <thead><tr><th>Finding</th><th className="num">Signal</th><th className="num">Urgency</th></tr></thead>
        <tbody>
          {detail.findings.map((f) => (
            <tr key={f.name} className={f.name === s.driver ? "driver-row" : ""}>
              <td>{f.label}</td><td className="mono num">{fmt(f.signal)}</td>
              <td className="mono num">{fmt(f.urgency, 2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </>)}
      {s.lane === "FAILED" ? (
        <p className="note">No lane was assigned, so there is nothing to agree or disagree with. Read the study in PACS.</p>
      ) : (
        <Verdict study={s} onVerdict={onVerdict} busy={busy} />
      )}
      {s.source && <p className="source-note"><span className="source">{s.source.split(".")[0]}</span> {s.source}</p>}
      <details className="draft">
        <summary>Draft note (template, no language model)</summary>
        <pre>{detail.draft}</pre>
      </details>
    </aside>
  );
}

export default function Study({ load, loadSeries, sendVerdict }) {
  const { id } = useParams();
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const [seriesUid, setSeriesUid] = useState(null);
  const [instances, setInstances] = useState(null);
  const [rationale, setRationale] = useState(false);
  const [busy, setBusy] = useState(false);

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

  if (error) return <main className="study"><p className="error" role="alert">{String(error.message || error)}</p></main>;
  if (!detail) return <main className="study"><p>Loading study.</p></main>;

  const ev = detail.evidence || {};
  const urls = detail.evidence_urls || {};
  const overlay = rationale && urls.gradcam_layer_png && ev.gradcam_box
    ? { url: urls.gradcam_layer_png, box: ev.gradcam_box } : null;
  const current = detail.series.find((s) => s.series_uid === seriesUid);

  return (
    <main className="study">
      <div className="study-main">
        <div className="study-bar">
          <Link to="/" className="back">Back to worklist</Link>
          {detail.series.length > 1 && (
            <div className="series-switch" role="group" aria-label="Series">
              {detail.series.map((s) => (
                <button key={s.series_uid} type="button" aria-pressed={s.series_uid === seriesUid}
                        onClick={() => setSeriesUid(s.series_uid)}>{s.description}</button>
              ))}
            </div>
          )}
          <Rationale detail={detail} on={rationale} onToggle={() => setRationale((v) => !v)} />
        </div>
        {!current || current.instance_count === 0 ? (
          <p className="note viewer-empty">No images are available for this series from this datastore.</p>
        ) : !instances ? (
          <p className="note viewer-empty">Loading series.</p>
        ) : (
          <Suspense fallback={<p className="note viewer-empty">Loading viewer.</p>}>
            <Viewer instances={instances} overlay={overlay} label={current.description} />
          </Suspense>
        )}
      </div>
      <StudyPanel detail={detail} onVerdict={onVerdict} busy={busy} rationaleOn={rationale} />
    </main>
  );
}
