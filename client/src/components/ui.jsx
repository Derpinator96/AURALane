import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { isTyping, useDismiss } from "../hooks.js";
import { CheckIcon, ChevronDownIcon } from "./Icons.jsx";

// The fixed background layer: three large soft blooms and faint curved line art.
// It sits behind everything and is never blurred by the panels' own filters.
export function Backdrop() {
  const arcs = Array.from({ length: 26 }, (_, i) => 150 + i * 26);
  return (
    <div className="bg" aria-hidden="true">
      <div className="bg-blooms"><span className="b1" /><span className="b2" /><span className="b3" /></div>
      <svg className="bg-art" viewBox="0 0 900 900" fill="none" stroke="currentColor" strokeWidth="1">
        {arcs.map((r, i) => <circle key={r} cx="900" cy="900" r={r} opacity={0.35 + (i % 5) * 0.13} />)}
      </svg>
    </div>
  );
}

// A raised white pill button with an optional leading icon.
export function Pill({ icon, children, primary = false, quiet = false, small = false, className = "", ...rest }) {
  const cls = ["pill", primary && "pill-primary", quiet && "pill-quiet", small && "pill-sm", className].filter(Boolean).join(" ");
  return <button type="button" className={cls} {...rest}>{icon}{children}</button>;
}

export function Circle({ icon, label, small = false, className = "", ...rest }) {
  return (
    <button type="button" className={`circle ${small ? "circle-sm" : ""} ${className}`} aria-label={label} title={label} {...rest}>
      {icon}
    </button>
  );
}

// Tabs in a frosted pill. `items` is [{ id, label, count?, testid? }]; `value` is the chosen id.
export function Segmented({ items, value, onChange, label, small = false, className = "" }) {
  return (
    <div className={`seg ${small ? "seg-sm" : ""} ${className}`} role="group" aria-label={label}>
      {items.map((it) => (
        <button key={it.id} type="button" aria-pressed={value === it.id} onClick={() => onChange(it.id)}
                data-testid={it.testid}>
          {it.label}
          {it.count != null && <span className="count mono">{it.count}</span>}
        </button>
      ))}
    </div>
  );
}

// A button that opens a panel of controls. The panel stays mounted while closed
// (hidden), so the controls inside keep their state and remain reachable by label.
export function PopoverButton({ label, icon, children, align = "right", pillProps = {}, menu = false, badge = null, chevron = false }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const close = useCallback(() => setOpen(false), []);
  useDismiss(ref, open, close);
  return (
    <div className="pop-wrap" ref={ref}>
      <button type="button" aria-haspopup={menu ? "menu" : "true"} aria-expanded={open}
              onClick={() => setOpen((v) => !v)} {...pillProps} className={pillProps.className || "pill"}>
        {icon}{label}{badge != null && <span className="count mono">{badge}</span>}
        {chevron && <ChevronDownIcon size={14} />}
      </button>
      <div className={`pop pop-${align} ${menu ? "pop-menu" : ""}`} hidden={!open} role={menu ? "menu" : "group"}
           aria-label={typeof label === "string" ? label : undefined}>
        {typeof children === "function" ? children(close) : children}
      </div>
    </div>
  );
}

// A blurred scrim over the whole app, with its content on top. Escape or a press on
// the scrim closes it. Rendered into <body>: the frame has its own backdrop filter,
// and a filtered ancestor would trap a fixed overlay.
export function Overlay({ onClose, children, side = "center", label }) {
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      if (isTyping(e.target)) { e.target.blur?.(); return; }
      onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return createPortal(
    <div className={`overlay ${side === "right" ? "overlay-right" : ""}`} data-testid="overlay"
         onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      {children}
    </div>,
    document.body,
  );
}

// A short confirmation at the bottom of the screen. show("Saved to Reports") for a few seconds.
export function useToast(ms = 3600) {
  const [msg, setMsg] = useState(null);
  const timer = useRef(null);
  const show = useCallback((m) => {
    setMsg(m);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setMsg(null), ms);
  }, [ms]);
  useEffect(() => () => clearTimeout(timer.current), []);
  const node = msg ? createPortal(
    <div className="toast" role="status" data-testid="toast"><CheckIcon size={16} />{msg}</div>, document.body) : null;
  return { show, node };
}

export const initials = (name = "") => {
  const parts = String(name).replace(/@.*/, "").split(/[\s._-]+/).filter(Boolean);
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : (parts[0] || "?").slice(0, 2)).toUpperCase();
};

export function Monogram({ name }) {
  return <span className="monogram" aria-hidden="true">{initials(name)}</span>;
}

export function Spinner({ label }) {
  return <span className="spinner" role="status" aria-label={label || "Loading"} />;
}
