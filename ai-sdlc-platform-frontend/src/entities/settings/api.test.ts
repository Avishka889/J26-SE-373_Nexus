import { describe, expect, it } from "vitest";
import type { SettingsState } from "@/types/settings";
import {
  createHttpSettingsApi,
  defaultSettings,
  forgetSettings,
  getSettingsLoad,
  getSettingsSnapshot,
  hydrateSettings,
  reloadSettings,
} from "./api";

/**
 * Saves go one at a time, in the order they were made.
 *
 * Three Atlas fields pasted in quick succession sent three requests at once, and
 * their answers landed in any order: an older answer applied after a newer one
 * put back what the newer one had changed, and a field showed empty that the
 * server held.
 */
function withDatabase(
  fields: Partial<SettingsState["database"]>,
): SettingsState {
  return {
    ...defaultSettings,
    database: { ...defaultSettings.database, ...fields },
  };
}

describe("the live settings API", () => {
  it("sends a save only once the one before it has answered, and keeps the newest answer", async () => {
    const sent: string[] = [];
    const answers: Array<(state: SettingsState) => void> = [];
    const client = {
      get: async <T>() => defaultSettings as T,
      patch: <T>(_path: string, body: unknown) => {
        sent.push(JSON.stringify(body));
        return new Promise<T>((resolve) =>
          answers.push((state) => resolve(state as T)),
        );
      },
    } as unknown as Parameters<typeof createHttpSettingsApi>[0];
    const api = createHttpSettingsApi(client);

    const first = api.updateDatabase({ projectId: "66f0c0ffee0123456789abcd" });
    const second = api.updateDatabase({ cluster: "Cluster0" });
    await Promise.resolve();

    expect(sent).toEqual(['{"projectId":"66f0c0ffee0123456789abcd"}']);
    answers[0](withDatabase({ projectId: "66f0c0ffee0123456789abcd" }));
    await first;
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(sent).toHaveLength(2);
    answers[1](
      withDatabase({
        projectId: "66f0c0ffee0123456789abcd",
        cluster: "Cluster0",
      }),
    );
    await second;

    expect(getSettingsSnapshot().database).toMatchObject({
      projectId: "66f0c0ffee0123456789abcd",
      cluster: "Cluster0",
    });
  });

  it("goes on after a refused save", async () => {
    let calls = 0;
    const client = {
      get: async <T>() => defaultSettings as T,
      patch: async <T>() => {
        calls += 1;
        if (calls === 1) throw new Error("refused");
        return withDatabase({ cluster: "Cluster0" }) as T;
      },
    } as unknown as Parameters<typeof createHttpSettingsApi>[0];
    const api = createHttpSettingsApi(client);

    await expect(api.updateDatabase({ cluster: "" })).rejects.toThrow(
      "refused",
    );
    await expect(
      api.updateDatabase({ cluster: "Cluster0" }),
    ).resolves.toMatchObject({
      database: { cluster: "Cluster0" },
    });
  });
});

/**
 * A phase's thinking saves with the other phases' choices: the `ai` section
 * saves whole, so a request that carried only its own phase would clear the
 * others.
 */
describe("choosing how hard a phase thinks", () => {
  function withThinking(
    thinking: Partial<SettingsState["ai"]["thinking"]>,
  ): SettingsState {
    return {
      ...defaultSettings,
      ai: {
        ...defaultSettings.ai,
        thinking: { ...defaultSettings.ai.thinking, ...thinking },
      },
    };
  }

  // Read when it was asked for, a second choice made before the first had
  // answered sent the first phase's old level, and undid the first choice.
  it("reads the other phases when the request goes, so two choices made at once both stay", async () => {
    forgetSettings();
    const sent: Array<{ path: string; body: unknown }> = [];
    const answers: Array<(state: SettingsState) => void> = [];
    const client = {
      get: async <T>() => defaultSettings as T,
      patch: <T>(path: string, body: unknown) => {
        sent.push({ path, body });
        return new Promise<T>((resolve) =>
          answers.push((state) => resolve(state as T)),
        );
      },
    } as unknown as Parameters<typeof createHttpSettingsApi>[0];
    const api = createHttpSettingsApi(client);

    const first = api.chooseThinking("design", "high");
    const second = api.chooseThinking("code", "low");
    await Promise.resolve();
    answers[0](withThinking({ design: "high" }));
    await first;
    await new Promise((resolve) => setTimeout(resolve, 0));
    answers[1](withThinking({ design: "high", code: "low" }));
    await second;

    expect(sent).toEqual([
      {
        path: "/settings/ai",
        body: {
          thinking: { design: "high", code: null, testing: null, deployment: null },
        },
      },
      {
        path: "/settings/ai",
        body: {
          thinking: { design: "high", code: "low", testing: null, deployment: null },
        },
      },
    ]);
    expect(getSettingsSnapshot().ai.thinking).toEqual({
      design: "high",
      code: "low",
      testing: null,
      deployment: null,
    });
  });
});

describe("reading the server's settings", () => {
  it("records why a read failed, and a second read brings them in", async () => {
    await hydrateSettings(() => Promise.reject(new Error("502 Bad Gateway")));
    expect(getSettingsLoad().error).toBe("502 Bad Gateway");

    const stored = withDatabase({
      projectId: "66f0c0ffee0123456789abcd",
      cluster: "Cluster0",
    });
    await reloadSettings(() => Promise.resolve(stored));

    expect(getSettingsLoad()).toEqual({ loaded: true, error: null });
    expect(getSettingsSnapshot().database.cluster).toBe("Cluster0");
  });
});
