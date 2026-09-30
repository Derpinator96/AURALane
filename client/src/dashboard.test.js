import { describe, expect, it } from "vitest";
import { arrivalsByHour, displayName, readerLoad, summarize, waitText } from "./dashboard.js";

const row = (o) => ({ study: "s", lane: "ROUTINE", pool: "Chest", verdict: null, arrived: "2026-09-25T08:10:00+00:00", ...o });

describe("waitText", () => {
  it("writes a wait in the largest sensible units", () => {
    expect(waitText(30_000)).toBe("under 1 min");
    expect(waitText(12 * 60_000)).toBe("12 min");
    expect(waitText((3 * 60 + 5) * 60_000)).toBe("3 h 5 min");
    expect(waitText(3 * 3_600_000)).toBe("3 h");
    expect(waitText((2 * 24 + 4) * 3_600_000)).toBe("2 d 4 h");
    expect(waitText(null)).toBe("--");
  });
});

describe("summarize", () => {
  const now = Date.parse("2026-09-25T10:00:00+00:00");
  const studies = [
    row({ study: "a", lane: "CRITICAL", arrived: "2026-09-25T08:00:00+00:00" }),
    row({ study: "b", lane: "CRITICAL", arrived: "2026-09-25T09:30:00+00:00" }),
    row({ study: "c", lane: "CRITICAL", arrived: "2026-09-25T07:00:00+00:00", verdict: { value: "agree" } }),
    row({ study: "d", lane: "ABSTAIN" }),
    row({ study: "e", lane: "URGENT", verdict: { value: "disagree" } }),
  ];
  const s = summarize(studies, now);

  it("counts critical studies and the longest wait among the ones nobody has read", () => {
    expect(s.critical).toBe(3);
    expect(s.waitingCritical).toBe(2);
    expect(s.oldestMs).toBe(2 * 3_600_000);                 // "a", not the already-read "c"
  });
  it("counts what is waiting per lane and what needs a human", () => {
    expect(s.waiting.CRITICAL).toBe(2);
    expect(s.waiting.URGENT).toBe(0);
    expect(s.waiting.ABSTAIN).toBe(1);
    expect(s.triage).toBe(1);
  });
  it("agreement is agreed over all verdicts, and absent when there are none", () => {
    expect(s.verdicts).toBe(2);
    expect(s.agreementRate).toBe(50);
    expect(summarize([row({})], now).agreementRate).toBeNull();
  });
  it("splits read from unread", () => {
    expect(s.unread).toBe(3);
    expect(s.read).toBe(2);
  });
  it("has no oldest wait when no critical study is waiting", () => {
    expect(summarize([row({ lane: "CRITICAL", verdict: { value: "agree" } })], now).oldestMs).toBeNull();
  });
});

describe("arrivalsByHour", () => {
  it("uses the latest day with arrivals and splits each hour by pool", () => {
    const a = arrivalsByHour([
      row({ arrived: "2026-09-24T22:00:00+00:00" }),
      row({ arrived: "2026-09-25T08:10:00+00:00", pool: "Chest" }),
      row({ arrived: "2026-09-25T08:50:00+00:00", pool: "Neuro" }),
      row({ arrived: "2026-09-25T09:05:00+00:00", pool: "Chest" }),
    ], ["Chest", "Neuro"]);
    expect(a.day).toBe("2026-09-25");
    expect(a.total).toBe(3);
    expect(a.hours[8].counts).toEqual({ Chest: 1, Neuro: 1 });
    expect(a.hours[9].total).toBe(1);
    expect(a.max).toBe(2);
  });
  it("is null when nothing has arrived", () => {
    expect(arrivalsByHour([], ["Chest"])).toBeNull();
    expect(arrivalsByHour([row({ arrived: null })], ["Chest"])).toBeNull();
  });
});

describe("readers", () => {
  it("counts each reader's unread assigned studies", () => {
    const load = readerLoad([{ id: "r1", name: "Reader 1", pools: ["Chest"] }, { id: "r2", name: "Reader 2", pools: [] }], [
      row({ assigned_to: "r1" }), row({ assigned_to: "r1", verdict: { value: "agree" } }), row({ assigned_to: "r1" }),
    ]);
    expect(load.map((r) => r.unread)).toEqual([2, 0]);
  });
  it("greets by the reader's name, else the email's local part", () => {
    expect(displayName("a@x.io", [{ id: "a@x.io", name: "Reader 1" }])).toBe("Reader 1");
    expect(displayName("radiologist@dev.auralane.local", [])).toBe("radiologist");
    expect(displayName(null)).toBe("");
  });
});
