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

// Studies per UTC hour on the most recent day any study arrived, split by reading
// pool. Returns null when nothing has arrived.
export function arrivalsByHour(studies, poolNames) {
  const stamped = studies
    .map((s) => ({ s, t: Date.parse(s.arrived) }))
    .filter((x) => !Number.isNaN(x.t));
  if (!stamped.length) return null;
  const day = new Date(Math.max(...stamped.map((x) => x.t))).toISOString().slice(0, 10);
  const hours = Array.from({ length: 24 }, (_, hour) => ({
    hour, counts: Object.fromEntries(poolNames.map((p) => [p, 0])), total: 0,
  }));
  for (const { s, t } of stamped) {
    const d = new Date(t).toISOString();
    if (d.slice(0, 10) !== day) continue;
    const h = hours[Number(d.slice(11, 13))];
    if (s.pool in h.counts) h.counts[s.pool] += 1;
    h.total += 1;
  }
  return { day, hours, total: hours.reduce((a, h) => a + h.total, 0), max: Math.max(...hours.map((h) => h.total)) };
}

// Each reader's unread studies, from the assigned_to on the rows.
export function readerLoad(readers, studies) {
  return readers.map((r) => ({
    ...r,
    unread: studies.filter((s) => s.assigned_to === r.id && isUnread(s)).length,
  }));
}

// The name the greeting uses: the reader's own name when the API lists one, else the
// part of the email before the @.
export function displayName(me, readers = []) {
  if (!me) return "";
  return readers.find((r) => r.id === me)?.name || String(me).replace(/@.*/, "");
}
