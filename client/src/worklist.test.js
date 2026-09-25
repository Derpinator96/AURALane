import { describe, expect, it } from "vitest";
import fixture from "./test/worklist.api.json";
import { arrange, arrangePools } from "./worklist.js";

const { studies, lanes, pools } = fixture;
const lanesOf = (sections) => sections.map((s) => s.lane);
const ids = (sections) => sections.flatMap((s) => s.rows.map((r) => r.study));

describe("arrange", () => {
  it("groups by lane in the API's lane order and keeps the API's row order", () => {
    const sections = arrange(studies, lanes);
    expect(lanesOf(sections)).toEqual(["CRITICAL", "URGENT", "ABSTAIN", "EXPEDITED", "ROUTINE"]);
    const apiOrder = studies.map((r) => r.study);
    expect(ids(sections)).toEqual(apiOrder);
  });

  it("keeps the abstention section when a lane filter would exclude it", () => {
    const sections = arrange(studies, lanes, { lane: "CRITICAL" });
    expect(lanesOf(sections)).toEqual(["CRITICAL", "ABSTAIN"]);
    expect(sections[1].rows.length).toBe(studies.filter((r) => r.lane === "ABSTAIN").length);
  });

  it("keeps the abstention section under the read filter, even when empty", () => {
    const allRead = studies.map((r) => ({ ...r, verdict: { value: "agree" } }));
    const sections = arrange(allRead, lanes, { read: "unread" });
    expect(lanesOf(sections)).toEqual(["ABSTAIN"]);
    const noAbstain = studies.filter((r) => r.lane !== "ABSTAIN");
    expect(lanesOf(arrange(noAbstain, lanes))).toContain("ABSTAIN");
  });

  it("re-sorts by arrival, oldest or newest first, with abstention pinned first", () => {
    const oldest = arrange(studies, lanes, { sort: "arrival-oldest" });
    expect(oldest[0].lane).toBe("ABSTAIN");
    const times = oldest[1].rows.map((r) => r.arrived);
    expect(times).toEqual([...times].sort());
    expect(ids(oldest)).not.toEqual(ids(arrange(studies, lanes)));
    const newest = arrange(studies, lanes, { sort: "arrival-newest" });
    expect(newest[1].rows.map((r) => r.arrived)).toEqual([...times].reverse());
  });

  it("filters unread and read", () => {
    const one = studies.find((r) => r.lane === "ROUTINE");
    const rows = studies.map((r) => (r === one ? { ...r, verdict: { value: "agree" } } : r));
    expect(ids(arrange(rows, lanes, { read: "read" }))).toEqual(
      [one.study, ...rows.filter((r) => r.lane === "ABSTAIN").map((r) => r.study)].sort((a, b) =>
        ids(arrange(rows, lanes)).indexOf(a) - ids(arrange(rows, lanes)).indexOf(b)));
    expect(ids(arrange(rows, lanes, { read: "unread" }))).not.toContain(one.study);
  });
});

describe("arrangePools", () => {
  it("never ranks across pools and gives every pool its own pinned sections", () => {
    const out = arrangePools(studies, pools, lanes);
    expect(out.map((p) => p.pool)).toEqual(pools.map((p) => p.pool));
    for (const p of out) {
      expect(ids(p.sections).every((id) => studies.find((r) => r.study === id).pool === p.pool)).toBe(true);
      expect(lanesOf(p.sections)).toContain("ABSTAIN");
    }
    expect(out.flatMap((p) => ids(p.sections)).sort()).toEqual(studies.map((r) => r.study).sort());
  });

  it("a failed study stays pinned in its own pool, whatever the filter", () => {
    const failed = { ...studies.find((r) => r.pool === "Neuro"), study: "f1", lane: "FAILED" };
    const out = arrangePools([...studies, failed], pools, lanes, { lane: "ROUTINE" });
    const neuro = out.find((p) => p.pool === "Neuro");
    expect(lanesOf(neuro.sections)).toEqual(["ABSTAIN", "FAILED"]);
    expect(lanesOf(out.find((p) => p.pool === "Chest").sections)).not.toContain("FAILED");
  });
});
