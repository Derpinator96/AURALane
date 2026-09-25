import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// The API runs on 8100 (python -m core.run serve). Port 8000 is the round-2
// demo's and is never used here. /api is proxied so the browser talks to one
// origin; frame URLs the API returns are fetched directly, never through /api.
const api = { "/api": "http://127.0.0.1:8100" };

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
