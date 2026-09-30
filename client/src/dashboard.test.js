import { describe, expect, it } from "vitest";
import { displayName, readerLoad, summarize, waitText, waitingByLane } from "./dashboard.js";

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

describe("waitingByLane", () => {
  const now = Date.parse("2026-09-25T10:00:00+00:00");
  const w = waitingByLane([
    row({ lane: "CRITICAL", arrived: "2026-09-25T08:00:00+00:00" }),
    row({ lane: "CRITICAL", arrived: "2026-09-25T09:30:00+00:00" }),
    row({ lane: "CRITICAL", arrived: "2026-09-25T06:00:00+00:00", verdict: { value: "agree" } }),
    row({ lane: "ABSTAIN", arrived: "2026-09-25T09:50:00+00:00" }),
    row({ lane: "URGENT", verdict: { value: "disagree" } }),
  ], now);
  const by = Object.fromEntries(w.map((r) => [r.lane, r]));
  it("lists every tracked lane, in order, even when nothing waits", () => {
    expect(w.map((r) => r.lane)).toEqual(["CRITICAL", "URGENT", "ABSTAIN", "EXPEDITED", "ROUTINE"]);
    expect(by.ROUTINE).toEqual({ lane: "ROUTINE", count: 0, oldestMs: null });
  });
  it("counts only studies nobody has read, and times the oldest of them", () => {
    expect(by.CRITICAL.count).toBe(2);
    expect(by.CRITICAL.oldestMs).toBe(2 * 3_600_000);          // 08:00, not the already-read 06:00
    expect(by.URGENT.count).toBe(0);
    expect(by.ABSTAIN.oldestMs).toBe(10 * 60_000);
  });
  it("has no oldest wait when a waiting study carries no arrival time", () => {
    expect(waitingByLane([row({ lane: "ROUTINE", arrived: null })], now).find((r) => r.lane === "ROUTINE"))
      .toEqual({ lane: "ROUTINE", count: 1, oldestMs: null });
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
    expect(displayName("radiologist@dev.auralane.local", [])).toBe("Radiologist");
    expect(displayName("anurag.verma@x.io", [])).toBe("Anurag Verma");
    expect(displayName(null)).toBe("");
  });
});
