import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup, configure } from "@testing-library/react";
import { api } from "../api.js";

// findBy and waitFor give up after 1 s by default, which a busy machine (the suites run in parallel, and a
// browser may be capturing) can exceed without anything being wrong. A real failure still fails, later.
configure({ asyncUtilTimeout: 5000 });

// The API client remembers recent study payloads; a test must start without them.
afterEach(() => {
  cleanup();
  api.clearCache();
});
