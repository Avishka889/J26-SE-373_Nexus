import { defineConfig, devices } from "@playwright/test";

/**
 * Critical journeys only (login → project → gate).
 * Install: npm i -D @playwright/test && npx playwright install
 */
/**
 * The port the fixtures server runs on.
 *
 * Overridable because a development server in live mode occupies 5173 while
 * somebody is using the app, and `reuseExistingServer` then hands this whole
 * suite that server: every check runs against live data, the four demo
 * projects are not there, and forty tests fail for a reason that has nothing
 * to do with the code. `E2E_PORT=5174 npx playwright test` runs beside it.
 */
const PORT = Number(process.env.E2E_PORT ?? 5173);
const BASE_URL = `http://localhost:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  // The live walk through has its own config and its own server.
  testIgnore: /live-.*\.spec\.ts/,
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: "list",
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    // Fixtures, explicitly, whatever .env.development says: these checks assert
    // things about four authored demo projects. A mode file rather than an env
    // var, because Vite does not treat an empty VITE_ value in the environment as
    // set, so passing VITE_LIVE_FEATURES= here lost to .env.development and the
    // suite quietly ran against an empty database.
    command: `npm run dev -- --port ${PORT} --mode fixtures`,
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
  },
});
