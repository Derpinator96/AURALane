import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { CopyIcon, RefreshIcon } from "./Icons.jsx";
import { useToast } from "./ui.jsx";

// The draft the template wrote (no language model), editable by the reader.
// Saved and "Mark as reviewed" go to the API and are audited; the text is not in the audit.

// A section heading is a line of capitals on its own: EXAMINATION, FINDINGS, IMPRESSION.
const HEADING = /^[A-Z][A-Z0-9 &/,-]{2,}$/;

// The layer behind the textarea. Its text is transparent; only the tint under a heading shows,
// so the letters the reader sees and edits are the textarea's own and can never drift.
function Marks({ text }) {
  const lines = text.split("\n");
  return lines.map((line, i) => (
    <span key={i}>{HEADING.test(line) ? <mark>{line}</mark> : line}{"\n"}</span>
  ));
}

export function DraftPanel({ detail, saveDraft }) {
  const s = detail.study;
  // What the panel opens with: the latest saved report, else the reader's saved edit
  // (rows from before reports existed), else the draft generated from the findings.
  const opening = detail.report?.text ?? detail.draft_review?.text ?? detail.draft ?? "";
  const [text, setText] = useState(opening);
  const [base, setBase] = useState(opening);            // what the box held when last loaded or saved
  const [review, setReview] = useState(detail.report || detail.draft_review || null);
  const [state, setState] = useState(null);
  const [confirmRegen, setConfirmRegen] = useState(false);
  const box = useRef(null);
  const toast = useToast();

  useEffect(() => {
    const next = detail.report?.text ?? detail.draft_review?.text ?? detail.draft ?? "";
    setText(next);
    setBase(next);
    setReview(detail.report || detail.draft_review || null);
    setState(null);
    setConfirmRegen(false);
  }, [detail.study.study]); // eslint-disable-line react-hooks/exhaustive-deps

  // The box grows with its text, so the sheet scrolls, not the box.
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [text]);

  if (!detail.draft) return null;

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setState("Copied");
    } catch {
      setState("The browser did not allow copying; select the text instead");
    }
  }

  async function save(reviewed) {
    setState("Saving");
    try {
      const r = await saveDraft(s.study, text, reviewed);
      const saved = r.report || r.draft_review;
      setReview(saved);
      setBase(text);
      if (r.report_error) setState(`Not added to Reports: ${r.report_error}`);
      else {
        setState(null);
        if (reviewed && r.report) toast.show("Saved to Reports");
      }
    } catch (e) {
      setState(`Not saved: ${e.message}`);
    }
  }

  // A fresh draft from the stored findings; asks first when the box holds edits.
  function regenerate(force = false) {
    if (!force && text !== base && text !== detail.draft) {
      setConfirmRegen(true);
      return;
    }
    setText(detail.draft);
    setConfirmRegen(false);
    setState("Regenerated. Save it to keep it");
  }

  const reviewedNow = Boolean(review && (review.reviewed || review.status === "reviewed"));
  const who = review && (review.by || review.author_name || review.author);
  const chipText = state
    || (reviewedNow ? `Reviewed by ${who} at ${review.at}`
        : review ? `Draft saved by ${who} at ${review.at}` : "Not reviewed");
  const chipDot = state ? "idle" : reviewedNow ? "ok" : review ? "draft" : "idle";

  return (
    <section className="draft-panel" data-testid="draft-panel" aria-label="Draft report">
      <h3 className="sec-title">Draft report</h3>
      <div className="editor">
        <div className="editor-marks" aria-hidden="true"><Marks text={text} />{"\n"}</div>
        <textarea ref={box} className="editor-input" value={text} rows={6} data-testid="draft-text"
                  aria-label="Draft text" spellCheck="false"
                  onChange={(e) => { setText(e.target.value); setState(null); }} />
      </div>
      {confirmRegen && (
        <div className="regen-confirm" role="alert">
          <span>Replace your edits with a fresh draft?</span>
          <button type="button" className="pill pill-sm" onClick={() => regenerate(true)}>Replace</button>
          <button type="button" className="pill pill-sm pill-quiet" onClick={() => setConfirmRegen(false)}>Keep my edits</button>
        </div>
      )}
      <div className="draft-actions">
        <button type="button" className="pill pill-quiet" onClick={copy}><CopyIcon size={15} />Copy</button>
        <button type="button" className="pill pill-quiet" onClick={() => regenerate(false)}
                data-testid="draft-regenerate"><RefreshIcon size={15} />Regenerate draft</button>
        {saveDraft && <button type="button" className="pill pill-quiet" onClick={() => save(false)}>Save draft</button>}
        {saveDraft && (
          <button type="button" className="pill pill-primary" onClick={() => save(true)}
                  data-testid="draft-reviewed">Mark as reviewed</button>
        )}
      </div>
      <p className={`chip chip-quiet draft-chip status-${chipDot}`} data-testid="draft-status" role="status">
        <span className="dot" aria-hidden="true" />{chipText}
      </p>
      {toast.node}
    </section>
  );
}
