import { defineConfig, devices } from "@playwright/test";

/**
 * The live walk through, against an orchestrator somebody started.
 *
 * No webServer: this one deliberately does not start its own, because it has to
 * run against a dev server built with .env.development (so features are live) and
 * an orchestrator with a database and a provider key. Starting those from a test
 * config would hide what the run actually depends on.
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /live-.*\.spec\.ts/,
  fullyParallel: false,
  retries: 0,
  reporter: "list",
  use: {
    // 5173, because the orchestrator's CORS_ORIGINS allows that origin and
    // nothing else. A dev server on another port gets a 400 on the preflight,
    // and the UI shows nothing at all when that happens.
    baseURL: process.env.LIVE_BASE_URL ?? "http://localhost:5173",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
