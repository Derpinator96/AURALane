import { describe, expect, it } from "vitest";
import { seriesName } from "./worklist.js";

describe("seriesName", () => {
  it("keeps a real description, such as an MR sequence", () => {
    expect(seriesName({ description: "FLAIR", number: 4, instance_count: 155 })).toBe("FLAIR");
    expect(seriesName({ description: "  PA ", number: 1 })).toBe("PA");
  });

  it("does not show the de-identification placeholder as a name", () => {
    expect(seriesName({ description: "TRIAGE SERIES", number: 2, instance_count: 18 })).toBe("Series 2, 18 images");
    expect(seriesName({ description: "triage series", instance_count: 1 }, 0)).toBe("Series 1, 1 image");
    expect(seriesName({ description: "", number: 3 })).toBe("Series 3");
    expect(seriesName({ description: "TRIAGE SERIES" }, 4)).toBe("Series 5");
  });

  it("tells several placeholder series apart", () => {
    const series = [{ description: "TRIAGE SERIES", number: 1, instance_count: 3 }, { description: "TRIAGE SERIES", number: 2, instance_count: 40 }];
    expect(new Set(series.map((s, i) => seriesName(s, i))).size).toBe(2);
  });
});
