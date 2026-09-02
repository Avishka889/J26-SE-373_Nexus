/**
 * Provider connections: the credential seam beside the settings.
 *
 * A token is posted once and never comes back; everything after that is
 * metadata. In fixtures mode the map is authored demo data and says so in its
 * probe reason, because a fixture claiming a verdict from a call that never
 * happened would be a small lie in the one place honesty is the feature.
 */

import { isLive } from "@/lib/env";
import { http, messageOf } from "@/lib/http";
import { reflectConnections } from "./api";

export interface ConnectionProbe {
  verdict: "SUITABLE" | "WORKABLE" | "UNUSABLE";
  reason: string;
  login: string | null;
}

export interface Connection {
  provider: string;
  connected: boolean;
  createdAt: string;
  createdBy: string;
  tokenKind: "classic" | "fine-grained" | null;
  scopes: string[];
  probe: ConnectionProbe | null;
}

export interface ConnectionsApi {
  list(): Promise<Connection[]>;
  create(provider: string, token: string): Promise<Connection>;
  revoke(provider: string): Promise<void>;
  probe(provider: string): Promise<Connection>;
}

type Listener = () => void;
const listeners = new Set<Listener>();
/** What the fixtures answer for a provider, as authored demo data that says so. */
function demoConnection(provider: string): Connection {
  const github = provider === "github";
  return {
    provider,
    connected: true,
    createdAt: "2026-08-01 09:15",
    createdBy: "u_local_dev",
    tokenKind: github ? "classic" : null,
    scopes: github ? ["repo", "workflow"] : [],
    probe: {
      verdict: "SUITABLE",
      reason: "Authored demo data; no request was made.",
      login: "acme-labs",
    },
  };
}

// GitHub and Vercel, matching the demo settings, which show both connected.
const DEMO_CONNECTIONS: Connection[] = [
  demoConnection("github"),
  demoConnection("vercel"),
];
// Live, nothing until the server says what is connected: the demo pair showed
// GitHub and Vercel connected until the answer came.
let connectionsDb: Connection[] = isLive("settings") ? [] : DEMO_CONNECTIONS;

/**
 * Where the read of the connections stands. Until it answered, every provider
 * read "Not connected" and offered a token field, and a failed read was never
 * reported: both invited a new token over one that worked.
 */
export interface ConnectionsLoad {
  status: "loading" | "loaded" | "failed";
  /** Why the read failed, as a sentence; null unless it failed. */
  error: string | null;
}

const LOADED: ConnectionsLoad = { status: "loaded", error: null };
const LOADING: ConnectionsLoad = { status: "loading", error: null };
let load: ConnectionsLoad = isLive("settings") ? LOADING : LOADED;

export function getConnectionsLoad(): ConnectionsLoad {
  return load;
}

function emit() {
  listeners.forEach((listener) => listener());
}

export function subscribeConnections(listener: Listener): () => void {
  listeners.add(listener);
  if (isLive("settings")) void hydrateConnections();
  return () => listeners.delete(listener);
}

export function getConnectionsSnapshot(): Connection[] {
  return connectionsDb;
}

let hydrated = false;

/** Forget the connections, at sign-out, so the next account reads its own. */
export function forgetConnections(): void {
  connectionsDb = isLive("settings") ? [] : DEMO_CONNECTIONS;
  load = isLive("settings") ? LOADING : LOADED;
  hydrated = false;
  emit();
}

/** Read the connections again, after a read that failed. */
export function retryConnections(): void {
  hydrated = false;
  load = LOADING;
  emit();
  void hydrateConnections();
}

async function hydrateConnections(): Promise<void> {
  if (hydrated) return;
  hydrated = true;
  try {
    const payload = await http.get<{ connections: Connection[] }>(
      "/connections",
    );
    connectionsDb = payload.connections;
    load = LOADED;
    emit();
  } catch (error) {
    hydrated = false;
    load = {
      status: "failed",
      error: messageOf(error, "Your connections could not be read."),
    };
    emit();
  }
}

function apply(next: Connection[]): void {
  connectionsDb = next;
  emit();
  reflectConnections(next);
}

/** Tests only: the demo connections again. */
export function resetConnections(): void {
  apply(DEMO_CONNECTIONS);
}

function createFixtureConnectionsApi(): ConnectionsApi {
  return {
    async list() {
      return connectionsDb;
    },
    async create(provider, _token) {
      const connection = demoConnection(provider);
      apply([
        ...connectionsDb.filter((c) => c.provider !== provider),
        connection,
      ]);
      return connection;
    },
    async revoke(provider) {
      apply(connectionsDb.filter((c) => c.provider !== provider));
    },
    async probe(provider) {
      const found = connectionsDb.find((c) => c.provider === provider);
      if (!found) throw new Error(`no ${provider} connection`);
      return found;
    },
  };
}

function createHttpConnectionsApi(): ConnectionsApi {
  const refresh = async () => {
    const payload = await http.get<{ connections: Connection[] }>(
      "/connections",
    );
    apply(payload.connections);
  };
  return {
    async list() {
      await refresh();
      return connectionsDb;
    },
    async create(provider, token) {
      const created = await http.post<Connection>("/connections", {
        provider,
        token,
      });
      await refresh();
      return created;
    },
    async revoke(provider) {
      await http.delete(`/connections/${provider}`);
      await refresh();
    },
    async probe(provider) {
      const probed = await http.post<Connection>(
        `/connections/${provider}/probe`,
        {},
      );
      await refresh();
      return probed;
    },
  };
}

export const connectionsApi: ConnectionsApi = isLive("settings")
  ? createHttpConnectionsApi()
  : createFixtureConnectionsApi();
