import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "./api.js";

// The 3D viewer asks for a presigned link every time it mounts. Reusing the answer briefly
// keeps the URL identical, so the browser's cache can serve the volume the second time.
describe("volume links", () => {
  let n;
  beforeEach(() => {
    n = 0;
    vi.useFakeTimers();
    api.clearCache();
    vi.stubGlobal("fetch", vi.fn(async (url) => {
      n += 1;
      return { ok: true, status: 200, json: async () => ({ url: `https://blob.example/${encodeURIComponent(url)}?sig=${n}`, name: "v.nii.gz" }) };
    }));
  });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

  it("gives the same link back on a second mount, then a fresh one after a minute", async () => {
    const a = await api.volume("t", "S1", "t1c");
    const b = await api.volume("t", "S1", "t1c");
    expect(b.url).toBe(a.url);
    expect(fetch).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(61_000);
    const c = await api.volume("t", "S1", "t1c");
    expect(c.url).not.toBe(a.url);
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("keeps studies, sequences and people apart", async () => {
    await api.volume("t", "S1", "t1c");
    await api.volume("t", "S1", "flair");
    await api.volume("t", "S2", "t1c");
    await api.volume("other", "S1", "t1c");
    expect(fetch).toHaveBeenCalledTimes(4);
  });

  it("forgets a study's links when this client writes to it", async () => {
    await api.volume("t", "S1", "t1c");
    await api.segmentation("t", "S1");
    await api.verdict("t", "S1", "agree");
    await api.volume("t", "S1", "t1c");
    await api.segmentation("t", "S1");
    expect(fetch).toHaveBeenCalledTimes(5);       // 2 links, the verdict, 2 links again
  });
});
