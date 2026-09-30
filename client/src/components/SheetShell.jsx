import { useEffect, useRef, useState } from "react";
import { CloseIcon, CollapseIcon, ExpandIcon } from "./Icons.jsx";

// The study sheet's frame: a glass panel at the right edge that the reader can widen. The width
// is dragged from the grip on its left edge, stepped with the arrow keys, or set to the whole
// screen with the expand button. It is remembered for the next study. Below 720 px the sheet
// is already the whole screen and the controls are hidden.

const KEY = "auralane.sheetWidth";
const MIN = 400;
const MARGIN = 32;             // the overlay's padding on both sides
const SNAP = 24;               // dragging this close to the edge means "the whole screen"

function load() {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "full") return "full";
    return Number(v) >= MIN ? Number(v) : null;
  } catch {
    return null;
  }
}

export default function SheetShell({ onClose, children }) {
  const [width, setWidth] = useState(load);            // null (the default), a width in px, or "full"
  const shell = useRef(null);
  const before = useRef(null);                          // the width to return to from full screen
  const full = width === "full";

  useEffect(() => {
    try {
      if (width == null) localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, String(width));
    } catch {
      // Storage unavailable: the width lasts until reload.
    }
  }, [width]);

  const max = () => window.innerWidth - MARGIN;
  const current = () => shell.current?.getBoundingClientRect().width ?? MIN;
  const set = (px) => setWidth(px >= max() - SNAP ? "full" : Math.max(MIN, Math.round(px)));

  const toggle = () => {
    if (full) { setWidth(before.current); return; }
    before.current = width;
    setWidth("full");
  };

  const drag = (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    const grip = e.currentTarget, el = shell.current;
    const x0 = e.clientX, w0 = current(), limit = max();
    let w = w0;
    grip.setPointerCapture(e.pointerId);
    el.classList.add("dragging");
    const move = (ev) => {
      w = Math.min(limit, Math.max(MIN, w0 + (x0 - ev.clientX)));
      el.style.setProperty("--sheet-w", `${w}px`);
    };
    const up = () => {
      grip.removeEventListener("pointermove", move);
      grip.removeEventListener("pointerup", up);
      grip.removeEventListener("pointercancel", up);
      el.classList.remove("dragging");
      set(w);
    };
    grip.addEventListener("pointermove", move);
    grip.addEventListener("pointerup", up);
    grip.addEventListener("pointercancel", up);
  };

  const key = (e) => {
    const step = { ArrowLeft: 48, ArrowRight: -48 }[e.key];
    if (step) { e.preventDefault(); set(current() + step); }
    else if (e.key === "Home") { e.preventDefault(); setWidth(null); }
    else if (e.key === "End") { e.preventDefault(); setWidth("full"); }
  };

  return (
    <div ref={shell} className={`sheet-shell ${full ? "is-full" : ""}`}
         style={width == null ? undefined : { "--sheet-w": full ? "100%" : `${width}px` }}>
      <div className="sheet-resize" role="separator" aria-orientation="vertical" tabIndex={0}
           aria-label="Resize study panel" aria-valuemin={MIN} aria-valuemax={Math.max(MIN, max())}
           aria-valuenow={Math.round(full ? max() : width ?? current())}
           title="Drag to resize, double-click to expand" data-testid="resize-panel"
           onPointerDown={drag} onKeyDown={key} onDoubleClick={toggle} />
      <aside className="sheet" data-testid="workstation-details-panel" role="dialog" aria-modal="true" aria-label="Study details">
        <div className="sheet-tools">
          <button type="button" className="circle" onClick={toggle} aria-pressed={full} data-testid="expand-panel"
                  aria-label={full ? "Restore study panel size" : "Expand study panel"}
                  title={full ? "Restore size" : "Expand"}>
            {full ? <CollapseIcon size={18} /> : <ExpandIcon size={18} />}
          </button>
          <button type="button" className="circle" onClick={onClose} aria-label="Close study panel"
                  title="Close (Esc)" data-testid="close-panel">
            <CloseIcon size={18} />
          </button>
        </div>
        {children}
      </aside>
    </div>
  );
}
