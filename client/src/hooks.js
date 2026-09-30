import { useEffect, useState } from "react";

// jsdom (the unit tests) has no matchMedia; everything here then reports "no match".
export function useMediaQuery(query) {
  const supported = typeof window !== "undefined" && typeof window.matchMedia === "function";
  const [matches, setMatches] = useState(() => (supported ? window.matchMedia(query).matches : false));
  useEffect(() => {
    if (!supported) return undefined;
    const mq = window.matchMedia(query);
    const on = () => setMatches(mq.matches);
    on();
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [query, supported]);
  return matches;
}

const TYPING = /^(INPUT|TEXTAREA|SELECT)$/;
export const isTyping = (el) => TYPING.test(el?.tagName || "") || Boolean(el?.isContentEditable);

// Closes on Escape and on a press outside `ref`. While the reader is typing in a field,
// the first Escape only leaves the field.
export function useDismiss(ref, open, onClose) {
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      if (isTyping(e.target)) { e.target.blur?.(); return; }
      onClose();
    };
    const onDown = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose(); };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
    };
  }, [open, onClose, ref]);
}
