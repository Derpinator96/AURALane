import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import { api } from "../api.js";

// The API client remembers recent study payloads; a test must start without them.
afterEach(() => {
  cleanup();
  api.clearCache();
});
