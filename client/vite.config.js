import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// The API runs on 8100 (python -m core.run serve). Port 8000 is the round-2
// demo's and is never used here. /api is proxied so the browser talks to one
// origin; frame URLs the API returns are fetched directly, never through /api.
// /dicom-web goes to Orthanc (local runtime): the browser fetches frames from
// the datastore, never through the API, and Orthanc sends no CORS headers.
// AURALANE_API_PROXY points /api at another port when 8100 is taken.
const api = {
  "/api": process.env.AURALANE_API_PROXY || "http://127.0.0.1:8100",
  "/dicom-web": "http://127.0.0.1:8042",
};

export default defineConfig({
  plugins: [react()],
  // The DICOM image loader ships web workers and WASM codecs; Vite must not
  // pre-bundle it, and workers are ES modules. The codecs it imports are UMD files, and
  // a worker's imports are not scanned, so they are listed here to be converted; without
  // this the dev server fails with "does not provide an export named 'default'" and the
  // viewer never loads.
  optimizeDeps: {
    exclude: ["@cornerstonejs/dicom-image-loader"],
    include: [
      "dicom-parser",
      "@cornerstonejs/codec-charls/decodewasmjs",
      "@cornerstonejs/codec-libjxl/decodewasmjs",
      "@cornerstonejs/codec-libjpeg-turbo-8bit/decodewasmjs",
      "@cornerstonejs/codec-openjpeg/decodewasmjs",
      "@cornerstonejs/codec-openjph/wasmjs",
    ],
  },
  worker: { format: "es" },
  server: { port: 5173, strictPort: true, proxy: api },
  preview: { port: 4173, strictPort: true, proxy: api },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.js"],
    include: ["src/**/*.test.{js,jsx}"],
    // Typing a long password key by key can pass 5 s when the suite runs in parallel.
    testTimeout: 20000,
  },
});
