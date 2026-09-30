import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, errorMessage } from "./api.js";

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

// A request the API refuses as malformed answers with a list of objects. It used to be shown as
// "[object Object]".
describe("error messages", () => {
  const reply = (status, body, statusText = "") => ({ ok: false, status, statusText, json: async () => body });
  afterEach(() => vi.unstubAllGlobals());

  it("writes a refused sign-up as sentences, not [object Object]", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply(422, { detail: [
      { type: "string_pattern_mismatch", loc: ["body", "username"], msg: "String should match pattern '^[A-Za-z0-9._-]{3,64}$'",
        input: "Jane Doe", ctx: { pattern: "^[A-Za-z0-9._-]{3,64}$" } },
      { type: "string_too_short", loc: ["body", "password"], msg: "String should have at least 8 characters",
        input: "SECRET-VALUE", ctx: { min_length: 8 } },
    ] }, "Unprocessable Entity")));
    const err = await api.requestAccess({}).catch((e) => e);
    expect(err.status).toBe(422);
    expect(err.message).toBe("Username can use letters, numbers, dots, underscores and hyphens only, with no spaces. "
                             + "Password needs at least 8 characters.");
    // What was typed is never repeated back, whatever the field.
    expect(err.message).not.toContain("SECRET-VALUE");
    expect(err.message).not.toContain("Jane Doe");
  });

  it("keeps a plain message as it was and never returns an object", () => {
    expect(errorMessage(409, "Conflict", { detail: "a request for this username already exists" }))
      .toBe("a request for this username already exists");
    expect(errorMessage(400, "", { detail: { message: "nope" } })).toBe("nope");
    expect(errorMessage(400, "", { detail: { odd: true } })).toBe("The request failed (400).");
    expect(errorMessage(422, "", { detail: [{ type: "missing", loc: ["body", "email"] }] })).toBe("Email is required.");
  });

  it("says something when the server sent no reason at all", () => {
    expect(errorMessage(502, "", {})).toBe("The request failed (502).");
    expect(errorMessage(500, "Internal Server Error", {})).toBe("Internal Server Error");
  });
});
