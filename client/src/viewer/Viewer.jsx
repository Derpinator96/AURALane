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

export default function Viewer({ instances, overlay, label }) {
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

  return (
    <div className="viewer">
      <div className="viewer-tools" role="toolbar" aria-label="Viewer tools">
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
      <div className="viewport-wrap">
        <div ref={element} className="viewport" data-testid="viewport"
             onContextMenu={(e) => e.preventDefault()} />
        {overlay && <img ref={overlayRef} className="overlay-layer" src={overlay.url}
                         alt="Triage rationale overlay" data-testid="overlay-layer" />}
        {error && <p className="error viewer-error" role="alert">Viewer could not load this series: {error}</p>}
      </div>
    </div>
  );
}
