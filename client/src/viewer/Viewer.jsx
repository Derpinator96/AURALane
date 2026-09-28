import { useEffect, useRef, useState } from "react";
import { core, initCornerstone, registerFrame, tools } from "./cornerstone.js";

// Stack viewport for one series. Left drag runs the selected tool (window and
// level, zoom, pan); the mouse wheel scrolls slices. The pixels come from the
// datastore through the frame URLs the API returned.
//
// overlay: { url, box: [x, y, size] } pins an image (the Grad-CAM heat layer)
// to that box in frame pixels. It is repositioned on every render, so it
// follows pan and zoom. Nothing is drawn unless the caller passes it.

const MODES = [
  ["wl", "Window/level", tools.WindowLevelTool],
  ["zoom", "Zoom", tools.ZoomTool],
  ["pan", "Pan", tools.PanTool],
];
let counter = 0;

export default function Viewer({
  instances,
  overlay,
  label,
  annotations = [],
  selectedAnnotation = null,
  onSelectAnnotation = null,
  onRequestNewNote = null,
  isAddNoteMode = false,
  onToggleAddNoteMode = null,
}) {
  const element = useRef(null);
  const overlayRef = useRef(null);
  const handles = useRef(null);
  const [mode, setMode] = useState("wl");
  const [invert, setInvert] = useState(false);
  const [slice, setSlice] = useState({ index: 0, count: 0 });
  const [error, setError] = useState(null);

  // Build the viewport for this series.
  useEffect(() => {
    let cancelled = false;
    const id = ++counter;
    const engineId = `engine-${id}`, viewportId = `vp-${id}`, groupId = `tg-${id}`;
    (async () => {
      try {
        await initCornerstone();
        if (cancelled) return;
        const engine = new core.RenderingEngine(engineId);
        engine.enableElement({ viewportId, type: core.Enums.ViewportType.STACK,
                               element: element.current,
                               defaultOptions: { background: [0, 0, 0] } });
        const viewport = engine.getViewport(viewportId);
        const group = tools.ToolGroupManager.createToolGroup(groupId);
        for (const [, , T] of MODES) group.addTool(T.toolName);
        group.addTool(tools.StackScrollTool.toolName);
        group.addViewport(viewportId, engineId);
        group.setToolActive(tools.WindowLevelTool.toolName, {
          bindings: [{ mouseButton: tools.Enums.MouseBindings.Primary }] });
        group.setToolActive(tools.StackScrollTool.toolName, {
          bindings: [{ mouseButton: tools.Enums.MouseBindings.Wheel }] });
        const imageIds = instances.map((i) => registerFrame(i.frame_url, i.metadata));
        const start = Math.floor(imageIds.length / 2);
        await viewport.setStack(imageIds, start);
        viewport.render();
        handles.current = { engine, viewport, group, imageIds };
        setSlice({ index: start, count: imageIds.length });
        setError(null);
      } catch (e) {
        if (!cancelled) setError(String(e?.message || e));
      }
    })();
    const onNewImage = () => {
      const h = handles.current;
      if (h) setSlice({ index: h.viewport.getCurrentImageIdIndex(), count: h.imageIds.length });
    };
    element.current.addEventListener(core.Enums.Events.STACK_NEW_IMAGE, onNewImage);
    const el = element.current;
    return () => {
      cancelled = true;
      el.removeEventListener(core.Enums.Events.STACK_NEW_IMAGE, onNewImage);
      tools.ToolGroupManager.destroyToolGroup(groupId);
      handles.current?.engine.destroy();
      handles.current = null;
    };
  }, [instances]);

  // Switch the left-button tool.
  useEffect(() => {
    const h = handles.current;
    if (!h) return;
    for (const [key, , T] of MODES) {
      if (key === mode) {
        h.group.setToolActive(T.toolName, { bindings: [{ mouseButton: tools.Enums.MouseBindings.Primary }] });
      } else {
        h.group.setToolPassive(T.toolName);
      }
    }
  }, [mode, slice.count]);

  // Keep the overlay pinned to its box in frame pixels.
  useEffect(() => {
    const el = element.current, img = overlayRef.current;
    if (!overlay || !img) return undefined;
    const place = () => {
      const h = handles.current;
      if (!h) return;
      const imageId = h.imageIds[h.viewport.getCurrentImageIdIndex()];
      const [x, y, size] = overlay.box;
      const toCanvas = (col, row) =>
        h.viewport.worldToCanvas(core.utilities.imageToWorldCoords(imageId, [col, row]));
      const [x0, y0] = toCanvas(x, y);
      const [x1, y1] = toCanvas(x + size, y + size);
      Object.assign(img.style, { left: `${Math.min(x0, x1)}px`, top: `${Math.min(y0, y1)}px`,
                                 width: `${Math.abs(x1 - x0)}px`, height: `${Math.abs(y1 - y0)}px` });
    };
    place();
    el.addEventListener(core.Enums.Events.IMAGE_RENDERED, place);
    return () => el.removeEventListener(core.Enums.Events.IMAGE_RENDERED, place);
  }, [overlay, slice.count]);

  const act = (fn) => () => { const h = handles.current; if (h) { fn(h.viewport); h.viewport.render(); } };

  // Handle clicking viewport to add note
  const handleViewportClick = (e) => {
    if (!isAddNoteMode && e.type !== "contextmenu") return;
    if (e.type === "contextmenu") e.preventDefault();

    if (!element.current) return;
    const rect = element.current.getBoundingClientRect();
    const normX = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const normY = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));

    onRequestNewNote?.({
      modality: "CR",
      coordinate_space: "IMAGE_NORMALIZED",
      coordinate_x: normX,
      coordinate_y: normY,
      slice_index: slice.index,
      segmentation_region: "Chest Radiograph",
      viewer_context: {
        slice: slice.index + 1,
        total_slices: slice.count,
      },
    });
  };

  return (
    <div className={`viewer ${isAddNoteMode ? "pinpoint-active-mode" : ""}`}>
      <div className="viewer-tools" role="toolbar" aria-label="Viewer tools">
        {onToggleAddNoteMode && (
          <button
            type="button"
            className={`btn-pin-mode ${isAddNoteMode ? "active" : ""}`}
            onClick={onToggleAddNoteMode}
            title="Click anywhere on the X-Ray to drop a note marker"
          >
            📍 {isAddNoteMode ? "Pin Active" : "Add Note"}
          </button>
        )}
        {MODES.map(([key, name]) => (
          <button key={key} type="button" aria-pressed={mode === key} onClick={() => setMode(key)}>{name}</button>
        ))}
        <button type="button" aria-pressed={invert}
                onClick={() => { const v = !invert; setInvert(v); act((vp) => vp.setProperties({ invert: v }))(); }}>
          Invert
        </button>
        <button type="button" onClick={() => { setInvert(false); act((vp) => { vp.resetProperties(); vp.resetCamera(); })(); }}>
          Reset
        </button>
        {slice.count > 1 && (
          <span className="mono slice" data-testid="slice">slice {slice.index + 1} / {slice.count}</span>
        )}
        {label && <span className="viewer-label">{label}</span>}
      </div>

      {isAddNoteMode && (
        <div className="cxr-pin-instruction-hud">
          <span className="pulse-dot"></span>
          <span><strong>Pinpoint Active:</strong> Click any location on the radiograph to attach a clinical note.</span>
        </div>
      )}

      <div
        className="viewport-wrap"
        onClick={handleViewportClick}
        onContextMenu={handleViewportClick}
      >
        <div ref={element} className="viewport" data-testid="viewport" />
        {overlay && <img ref={overlayRef} className="overlay-layer" src={overlay.url}
                         alt="Triage rationale overlay" data-testid="overlay-layer" />}
        {annotations.map((ann) => {
          if (ann.coordinate_x == null || ann.coordinate_y == null) return null;
          const isSel = ann.id === selectedAnnotation?.id;
          return (
            <div
              key={ann.id || ann.annotation_id}
              className={`pin-marker-point ${isSel ? "selected" : ""}`}
              style={{
                left: `${ann.coordinate_x * 100}%`,
                top: `${ann.coordinate_y * 100}%`,
              }}
              onClick={(e) => {
                e.stopPropagation();
                onSelectAnnotation?.(ann);
              }}
              title={`${ann.note_text} (${ann.created_by || "radiologist"})`}
            >
              <span className="pin-dot"></span>
              <span className="pin-pulse"></span>
              {isSel && <div className="pin-tooltip-popover">{ann.note_text}</div>}
            </div>
          );
        })}
        {error && <p className="error viewer-error" role="alert">Viewer could not load this series: {error}</p>}
      </div>
    </div>
  );
}

