// Chest Grad-CAM for each of the top findings (evidence.gradcam_findings, written
// where the chest model runs, core/cxr_gradcam.py). The driver, the finding that
// set the lane, is selected by default.

export function findingsOf(ev) {
  return Array.isArray(ev?.gradcam_findings) ? ev.gradcam_findings : [];
}

// The finding whose map is showing: the reader's choice, else the driver.
export function activeFinding(ev, selected) {
  const list = findingsOf(ev);
  return list.find((g) => g.name === selected) || list.find((g) => g.driver) || null;
}

// The transparent layer to pin over the frame, and the caption that says what it is.
export function gradcamLayer(ev, urls, selected) {
  const active = activeFinding(ev, selected);
  const url = active?.layer_url || urls?.gradcam_layer_png;
  const drawable = Boolean(url && ev?.gradcam_box && (active ? true : ev.gradcam_coverage !== 0));
  return { active, url, drawable };
}

export function FindingSelector({ ev, selected, onSelect }) {
  const list = findingsOf(ev);
  if (list.length < 2) return null;
  const current = activeFinding(ev, selected);
  return (
    <div className="finding-selector" role="group" aria-label="Grad-CAM finding" data-testid="finding-selector">
      <span className="finding-selector-label">Finding</span>
      {list.map((g) => (
        <button key={g.slug} type="button" className="finding-chip" aria-pressed={current?.name === g.name}
                onClick={() => onSelect(g.name)} data-testid={`finding-${g.slug}`}
                title={`Signal ${Number(g.signal).toFixed(2)}, weighted ${Number(g.weighted).toFixed(2)}`}>
          {g.name}
          <span className="mono finding-chip-signal">{Number(g.signal).toFixed(2)}</span>
          {g.driver && <span className="finding-chip-tag">driver</span>}
        </button>
      ))}
    </div>
  );
}

export function selectedCaption(ev, selected) {
  const active = activeFinding(ev, selected);
  if (!active || active.driver) return null;
  return `Grad-CAM for ${active.name} (signal ${Number(active.signal).toFixed(2)}). It did not set the lane: ${ev.gradcam_finding} did.`;
}
