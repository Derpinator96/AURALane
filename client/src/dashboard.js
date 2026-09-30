// What the worklist dashboard shows, computed from the rows /api/worklist returned.
// Nothing here is estimated or invented: each figure is a count or a time taken
// from a row's own fields. The same counts the old Reports "Worklist summary" made.

import { isUnread } from "./worklist.js";

export const WAITING_LANES = ["CRITICAL", "URGENT", "ABSTAIN", "EXPEDITED", "ROUTINE"];

// A wait, in words: "12 min", "3 h 5 min", "2 d 4 h".
export function waitText(ms) {
  if (ms == null || Number.isNaN(ms)) return "--";
  const min = Math.floor(Math.max(0, ms) / 60000);
  if (min < 1) return "under 1 min";
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  if (h < 24) return min % 60 ? `${h} h ${min % 60} min` : `${h} h`;
  const d = Math.floor(h / 24);
  return h % 24 ? `${d} d ${h % 24} h` : `${d} d`;
}

export function summarize(studies, now = Date.now()) {
  const critical = studies.filter((s) => s.lane === "CRITICAL");
  const waitingCritical = critical.filter(isUnread);
  const arrivals = waitingCritical.map((s) => Date.parse(s.arrived)).filter((t) => !Number.isNaN(t));
  const oldestMs = arrivals.length ? now - Math.min(...arrivals) : null;

  const waiting = Object.fromEntries(WAITING_LANES.map((l) => [l, 0]));
  for (const s of studies) if (isUnread(s) && s.lane in waiting) waiting[s.lane] += 1;

  const agreed = studies.filter((s) => s.verdict?.value === "agree").length;
  const disagreed = studies.filter((s) => s.verdict?.value === "disagree").length;
  const verdicts = agreed + disagreed;
  const unread = studies.filter(isUnread).length;

  return {
    total: studies.length,
    critical: critical.length,
    waitingCritical: waitingCritical.length,
    oldestMs,
    waiting,
    triage: studies.filter((s) => s.lane === "ABSTAIN").length,
    agreed, disagreed, verdicts,
    agreementRate: verdicts > 0 ? (agreed / verdicts) * 100 : null,
    unread,
    read: studies.length - unread,
  };
}

// For each lane the dashboard tracks: how many studies nobody has read yet, and how long the
// longest of them has been waiting. Counted from the rows' own lane, verdict and arrival time.
export function waitingByLane(studies, now = Date.now()) {
  return WAITING_LANES.map((lane) => {
    const waiting = studies.filter((s) => s.lane === lane && isUnread(s));
    const times = waiting.map((s) => Date.parse(s.arrived)).filter((t) => !Number.isNaN(t));
    return { lane, count: waiting.length, oldestMs: times.length ? now - Math.min(...times) : null };
  });
}

// Each reader's unread studies, from the assigned_to on the rows.
export function readerLoad(readers, studies) {
  return readers.map((r) => ({
    ...r,
    unread: studies.filter((s) => s.assigned_to === r.id && isUnread(s)).length,
  }));
}

// The name the greeting uses: the reader's own name when the API lists one, else the
// part of the email before the @, in capitals: anurag.verma is Anurag Verma.
export function displayName(me, readers = []) {
  if (!me) return "";
  const named = readers.find((r) => r.id === me)?.name;
  if (named) return named;
  return String(me).replace(/@.*/, "").split(/[._-]+/).filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}
