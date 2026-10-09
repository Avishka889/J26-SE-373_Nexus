import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.resetModules();
});

/** The project store as the running app loads it: every feature live. */
async function liveStore() {
  vi.resetModules();
  vi.stubEnv("MODE", "development");
  return import("./api");
}

function answerWith(projects: unknown[]) {
  return new Response(JSON.stringify(projects), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

/**
 * A failed first read is not an empty workspace.
 *
 * The read's error was swallowed ("the list is empty, which is what the empty
 * state is for"), so a restarting orchestrator showed "No projects yet" with a
 * button inviting a duplicate, and a deep link rendered an empty shell for good:
 * nothing marked the list loaded and nothing read it again.
 */
describe("the first read of the project list", () => {
  it("is remembered as failed, with the reason, not as no projects", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    const store = await liveStore();
    expect(store.getProjectsLoad().status).toBe("loading");

    await expect(store.hydrateProjects()).rejects.toBeTruthy();

    expect(store.getProjectsLoad()).toEqual({
      status: "failed",
      error: "Cannot reach the server. Check that it is running, then try again.",
    });
    expect(store.projectsAreLoaded()).toBe(false);
  });

  it("is loaded once a later read succeeds", async () => {
    let up = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => (up ? answerWith([]) : Promise.reject(new TypeError("Failed to fetch")))),
    );
    const store = await liveStore();
    await store.hydrateProjects().catch(() => undefined);

    up = true;
    await store.hydrateProjects();

    expect(store.getProjectsLoad()).toEqual({ status: "loaded", error: null });
    expect(store.projectsAreLoaded()).toBe(true);
  });
});

/**
 * The lists read the projects again when they open, so a status the server
 * moved is shown. A re-read that fails is not a reason to throw away a list
 * that was read: the page keeps what it had rather than turning into an error.
 */
describe("reading the list again", () => {
  it("keeps the list it had when the second read fails", async () => {
    let up = true;
    const project = { id: "p1", name: "Ledger", status: "design" };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => (up ? answerWith([project]) : Promise.reject(new TypeError("Failed to fetch")))),
    );
    const store = await liveStore();
    await store.hydrateProjects();

    up = false;
    await expect(store.hydrateProjects()).rejects.toBeTruthy();

    expect(store.getProjectsLoad()).toEqual({ status: "loaded", error: null });
    expect(store.getProjectsSnapshot().map((one) => one.id)).toEqual(["p1"]);
  });
});
