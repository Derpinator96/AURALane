import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// The API runs on 8100 (python -m core.run serve). Port 8000 is the round-2
// demo's and is never used here. /api is proxied so the browser talks to one
// origin; frame URLs the API returns are fetched directly, never through /api.
// /dicom-web goes to Orthanc (local runtime): the browser fetches frames from
// the datastore, never through the API, and Orthanc sends no CORS headers.
const api = {
  "/api": "http://127.0.0.1:8100",
  "/dicom-web": "http://127.0.0.1:8042",
};

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true, proxy: api },
  preview: { port: 4173, strictPort: true, proxy: api },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.js"],
    include: ["src/**/*.test.{js,jsx}"],
  },
});
