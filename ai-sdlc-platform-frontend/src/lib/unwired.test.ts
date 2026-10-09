import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * Fixtures are unwired from the running app. Loaded as `npm run dev` and a
 * production build load it, every feature reads the backend, and the stores
 * start blank rather than on demo data: the account menu read "Alex Chen" and
 * GitHub and Vercel showed connected until the server answered.
 */
afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

async function asTheRunningApp(mode: string) {
  vi.resetModules();
  vi.stubEnv("MODE", mode);
  vi.stubEnv("VITE_LIVE_FEATURES", "");
  return {
    env: await import("@/lib/env"),
    settings: await import("@/entities/settings/api"),
    connections: await import("@/entities/settings/connections"),
    session: await import("@/store/session"),
  };
}

describe("the running app", () => {
  it.each(["development", "production"])(
    "reads only the backend in %s, even with no flag",
    async (mode) => {
      const { env, settings, connections, session } = await asTheRunningApp(mode);

      expect(env.env.allFixtures).toBe(false);
      for (const feature of env.LIVE_FEATURES)
        expect(env.isLive(feature)).toBe(true);
      expect(settings.getSettingsSnapshot()).toEqual(settings.blankSettings);
      expect(settings.getSettingsSnapshot().profile.name).toBe("");
      expect(connections.getConnectionsSnapshot()).toEqual([]);
      expect(session.useSessionStore.getState().activeProjectId).toBeNull();
    },
  );

  it("still runs on fixtures in the fixture mode, for the tests", async () => {
    const { env, settings, connections } = await asTheRunningApp("fixtures");

    expect(env.env.allFixtures).toBe(true);
    expect(settings.getSettingsSnapshot().profile.name).toBe("Alex Chen");
    expect(
      connections.getConnectionsSnapshot().map((one) => one.provider),
    ).toEqual(["github", "vercel"]);
  });
});