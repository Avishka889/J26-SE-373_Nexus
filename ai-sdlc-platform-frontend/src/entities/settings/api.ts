import { avatarDefault as defaultAvatar } from "@/assets/img";
import type { SettingsState } from "@/types/settings";
import { isLive } from "@/lib/env";
import { http } from "@/lib/http";
import type { PhaseKey, ThinkingLevel } from "./models";

/**
 * Authored demo data for fixtures mode. Secret free like the wire shape: the
 * old defaults carried token and password fields "kept in memory", which is
 * exactly the pattern the credential store replaced.
 */
export const defaultSettings: SettingsState = {
  git: {
    provider: "github",
    defaultOrg: "acme-labs",
    connected: true,
    scopes: ["repo", "workflow"],
  },
  vercel: {
    team: "acme-labs",
    projectId: "",
    orgId: "",
    origin: "",
    connected: true,
  },
  render: { serviceId: "", region: "oregon", origin: "", connected: false },
  database: {
    provider: "mongodb_atlas",
    projectId: "",
    cluster: "",
    clientId: "",
    connected: false,
  },
  ai: {
    provider: "openai",
    model: "gpt-4o",
    temperature: 0.2,
    // No choice made: every phase thinks as the platform is configured.
    thinking: { design: null, code: null, testing: null, deployment: null },
  },
  profile: {
    name: "Alex Chen",
    email: "alex@acme.dev",
    workspace: "Alex's Workspace",
    avatarUrl: defaultAvatar,
  },
};

export interface SettingsApi {
  get(): Promise<SettingsState>;
  update(patch: Partial<SettingsState>): Promise<SettingsState>;
  updateGit(patch: Partial<SettingsState["git"]>): Promise<SettingsState>;
  updateVercel(patch: Partial<SettingsState["vercel"]>): Promise<SettingsState>;
  updateRender(patch: Partial<SettingsState["render"]>): Promise<SettingsState>;
  updateDatabase(
    patch: Partial<SettingsState["database"]>,
  ): Promise<SettingsState>;
  updateAi(patch: Partial<SettingsState["ai"]>): Promise<SettingsState>;
  /**
   * Choose how hard one phase thinks, keeping the others' choices. The `ai`
   * section saves whole, so the request carries all four phases.
   */
  chooseThinking(phase: PhaseKey, level: ThinkingLevel): Promise<SettingsState>;
  updateProfile(
    patch: Partial<SettingsState["profile"]>,
  ): Promise<SettingsState>;
}

/**
 * What the live store holds before the server's settings arrive: nothing that
 * looks like anybody's. It held the demo settings, so the account menu read
 * "Alex Chen" and every reader showed a demo team until the server answered.
 */
export const blankSettings: SettingsState = {
  git: { provider: "github", defaultOrg: "", connected: false, scopes: [] },
  vercel: { team: "", projectId: "", orgId: "", origin: "", connected: false },
  render: { serviceId: "", region: "oregon", origin: "", connected: false },
  database: {
    provider: "mongodb_atlas",
    projectId: "",
    cluster: "",
    clientId: "",
    connected: false,
  },
  ai: {
    provider: "",
    model: "",
    temperature: 0.2,
    thinking: { design: null, code: null, testing: null, deployment: null },
  },
  profile: { name: "", email: "", workspace: "", avatarUrl: null },
};

type Listener = () => void;

let settingsDb: SettingsState = structuredClone(
  isLive("settings") ? blankSettings : defaultSettings,
);
const listeners = new Set<Listener>();

function emit() {
  listeners.forEach((l) => l());
}

export function subscribeSettings(listener: Listener): () => void {
  listeners.add(listener);
  // Live mode loads the server's state once, on first interest. The store
  // renders defaults until it lands, and every later mutation applies the
  // server's answer, so the module store is a cache of the server rather than
  // a second source of truth.
  if (isLive("settings")) void hydrateSettings();
  return () => listeners.delete(listener);
}

export function getSettingsSnapshot(): SettingsState {
  return settingsDb;
}

/** Whether the server's settings are in the store yet, or why they are not. */
export interface SettingsLoad {
  loaded: boolean;
  error: string | null;
}

// Fixtures answer at once; live settings are the defaults until the server's
// arrive, and a page that showed them meanwhile showed empty fields that
// filled themselves a second later, which read as fields clearing on their own.
let load: SettingsLoad = { loaded: !isLive("settings"), error: null };

export function getSettingsLoad(): SettingsLoad {
  return load;
}

let hydrated = false;

/** Read the server's settings into the store, once; `fetch` is the server, replaceable in tests. */
export async function hydrateSettings(
  fetch: () => Promise<SettingsState> = () =>
    http.get<SettingsState>("/settings"),
): Promise<void> {
  if (hydrated) return;
  hydrated = true;
  try {
    settingsDb = await fetch();
    load = { loaded: true, error: null };
  } catch (error) {
    hydrated = false;
    load = {
      loaded: load.loaded,
      error: error instanceof Error ? error.message : String(error),
    };
  }
  emit();
}

/**
 * Forget the settings, at sign-out, so the next account reads its own: the
 * store loads once per page, and held the last account's until reloaded.
 */
export function forgetSettings(): void {
  settingsDb = isLive("settings") ? structuredClone(blankSettings) : structuredClone(defaultSettings);
  hydrated = false;
  load = { loaded: !isLive("settings"), error: null };
  emit();
}

/** Ask the server again, after a read that failed. */
export function reloadSettings(
  fetch?: () => Promise<SettingsState>,
): Promise<void> {
  hydrated = false;
  load = { loaded: load.loaded, error: null };
  emit();
  return hydrateSettings(fetch);
}

function apply(next: SettingsState): SettingsState {
  settingsDb = next;
  emit();
  return structuredClone(settingsDb);
}

function createFixtureSettingsApi(): SettingsApi {
  return {
    async get() {
      return structuredClone(settingsDb);
    },
    async update(patch) {
      return apply({ ...settingsDb, ...patch });
    },
    async updateGit(patch) {
      return apply({ ...settingsDb, git: { ...settingsDb.git, ...patch } });
    },
    async updateVercel(patch) {
      return apply({
        ...settingsDb,
        vercel: { ...settingsDb.vercel, ...patch },
      });
    },
    async updateRender(patch) {
      return apply({
        ...settingsDb,
        render: { ...settingsDb.render, ...patch },
      });
    },
    async updateDatabase(patch) {
      return apply({
        ...settingsDb,
        database: { ...settingsDb.database, ...patch },
      });
    },
    async updateAi(patch) {
      return apply({ ...settingsDb, ai: { ...settingsDb.ai, ...patch } });
    },
    async chooseThinking(phase, level) {
      return apply({
        ...settingsDb,
        ai: { ...settingsDb.ai, thinking: { ...settingsDb.ai.thinking, [phase]: level } },
      });
    },
    async updateProfile(patch) {
      return apply({
        ...settingsDb,
        profile: { ...settingsDb.profile, ...patch },
      });
    },
  };
}

type SettingsHttp = Pick<typeof http, "get" | "patch">;

/**
 * The live settings API: one request at a time, in the order they were made.
 *
 * Each field saves itself when the typing stops, so three fields pasted in
 * quick succession sent three requests at once, and their answers could land
 * in any order. An older answer applied after a newer one put back what the
 * newer one had changed, and a field showed empty that the server held. In a
 * queue each request goes once the one before has answered, so the answers
 * land in order and each carries every save before it.
 */
export function createHttpSettingsApi(
  client: SettingsHttp = http,
): SettingsApi {
  let queue: Promise<unknown> = Promise.resolve();
  const applied = (
    send: () => Promise<SettingsState>,
  ): Promise<SettingsState> => {
    const answer = queue.then(send).then(apply);
    queue = answer.catch(() => undefined);
    return answer;
  };
  const patch = (path: string) => (body: object) =>
    applied(() => client.patch<SettingsState>(path, body));
  return {
    get: () => applied(() => client.get<SettingsState>("/settings")),
    update: patch("/settings"),
    updateGit: patch("/settings/git"),
    updateVercel: patch("/settings/vercel"),
    updateRender: patch("/settings/render"),
    updateDatabase: patch("/settings/database"),
    updateAi: patch("/settings/ai"),
    // The other phases are read when the request goes, after every save before
    // it has answered: read when it was asked for, a second choice made before
    // the first had answered sent the first phase's old level and undid it.
    chooseThinking: (phase, level) =>
      applied(() =>
        client.patch<SettingsState>("/settings/ai", {
          thinking: { ...settingsDb.ai.thinking, [phase]: level },
        }),
      ),
    updateProfile: patch("/settings/profile"),
  };
}

export const settingsApi: SettingsApi = isLive("settings")
  ? createHttpSettingsApi()
  : createFixtureSettingsApi();

/** Fixture-and-connection coherence: the settings view derives `connected`
 * from the connections store on the server, for Git, Vercel and Render alike;
 * the connections seam calls this so the two stores tell one story. */
export function reflectConnections(
  connections: readonly { provider: string; scopes: string[] }[],
): void {
  const git = connections.find((c) => c.provider === "github");
  const has = (provider: string) =>
    connections.some((c) => c.provider === provider);
  settingsDb = {
    ...settingsDb,
    git: {
      ...settingsDb.git,
      connected: git !== undefined,
      scopes: git?.scopes ?? [],
    },
    vercel: { ...settingsDb.vercel, connected: has("vercel") },
    render: { ...settingsDb.render, connected: has("render") },
  };
  emit();
}
