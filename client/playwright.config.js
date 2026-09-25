import { randomBytes } from "node:crypto";
import { defineConfig } from "@playwright/test";

// End to end against real processes: the API in fixture mode on 8100 and the
// production build served by vite preview on 4173 (which proxies /api).
// Chromium comes from the environment (PLAYWRIGHT_CHROMIUM or the preinstalled
// /opt/pw-browsers build), so no browser download is attempted.
const chromium = process.env.PLAYWRIGHT_CHROMIUM ||
  "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";

// A fresh sign-in password per run, handed to the API and to the specs through
// the environment. No password is written in the repository.
process.env.AURALANE_DEV_PASSWORD ||= randomBytes(8).toString("hex");

export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  use: { baseURL: "http://127.0.0.1:4173", launchOptions: { executablePath: chromium } },
  webServer: [
    {
      command: "cd .. && AURALANE_RUNTIME=fixture python -m core.run serve --port 8100",
      url: "http://127.0.0.1:8100/api/health",
      reuseExistingServer: false,
    },
    {
      command: "npm run build && npm run preview",
      url: "http://127.0.0.1:4173",
      reuseExistingServer: false,
    },
  ],
});
