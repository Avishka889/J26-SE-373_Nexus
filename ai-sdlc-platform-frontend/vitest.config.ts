import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

/**
 * Unit tests: colocate as `*.test.ts` next to `model/` (and other pure modules).
 * Install: npm i -D vitest @vitest/coverage-v8 jsdom
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  test: {
    environment: "jsdom",
    // One zone on every machine, and not UTC: times are shown in the reader's
    // zone, and a test run in UTC could not tell that apart from no conversion.
    env: { TZ: "Asia/Colombo" },
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    exclude: ["e2e/**", "node_modules/**", "dist/**"],
  },
});
