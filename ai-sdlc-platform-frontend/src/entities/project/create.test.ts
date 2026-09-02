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

const answer = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/**
 * A create was a POST and then a PATCH carrying the requirement text, so a PATCH
 * that failed left a project with no requirements, which a retry duplicated;
 * and the new project joined the end of a list the server orders newest first,
 * so it fell out of Home's three, the sidebar's five and the palette.
 */
describe("creating a project", () => {
  it("is one request carrying the text and the files", async () => {
    const calls: { method: string; url: string; body: unknown }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push({
          method: init?.method ?? "GET",
          url: String(url),
          body: init?.body ? JSON.parse(String(init.body)) : undefined,
        });
        return url.endsWith("/projects") && init?.method === "POST"
          ? answer({ id: "p_new", name: "Ledger", status: "draft" }, 201)
          : answer([]);
      }),
    );
    const store = await liveStore();

    await store.projectsApi.create("Ledger", "Books", "Track the books.", ["brief.md"]);

    const writes = calls.filter((call) => call.method !== "GET");
    expect(writes).toHaveLength(1);
    expect(writes[0]).toMatchObject({
      method: "POST",
      body: { name: "Ledger", description: "Books", requirementText: "Track the books.", files: ["brief.md"] },
    });
  });

  it("puts the new project first, as the server lists them", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init?: RequestInit) =>
        init?.method === "POST"
          ? answer({ id: "p_new", name: "Ledger", status: "draft" }, 201)
          : answer([
              { id: "p2", name: "Older", status: "design" },
              { id: "p1", name: "Oldest", status: "code" },
            ]),
      ),
    );
    const store = await liveStore();
    await store.hydrateProjects();

    await store.projectsApi.create("Ledger");

    expect(store.getProjectsSnapshot().map((one) => one.id)).toEqual(["p_new", "p2", "p1"]);
  });
});
