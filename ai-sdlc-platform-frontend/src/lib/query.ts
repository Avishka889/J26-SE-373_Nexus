import { MutationCache, QueryClient } from "@tanstack/react-query";

declare module "@tanstack/react-query" {
  interface Register {
    mutationMeta: {
      /** The mutation shows its own failure, so the cache does not report it twice. */
      reportsOwnErrors?: boolean;
    };
  }
}

export const runKeys = {
  all: ["runs"] as const,
  detail: (runId: string) => ["runs", runId] as const,
  validation: (runId: string) => ["runs", runId, "validation"] as const,
};

export const projectKeys = {
  all: ["projects"] as const,
  detail: (projectId: string) => ["projects", projectId] as const,
};

export const settingsKeys = {
  all: ["settings"] as const,
  /** Each phase's model and thinking, as the AI Model tab and the chat boxes read them. */
  models: ["settings", "models"] as const,
};

/** What waits on the signed-in person, as the bell reads it. */
export const attentionKeys = {
  all: ["attention"] as const,
};

export const testingKeys = {
  all: ["testing"] as const,
  snapshot: (projectId: string) => ["testing", projectId, "snapshot"] as const,
  run: (projectId: string) => ["testing", projectId, "run"] as const,
  failures: (projectId: string) => ["testing", projectId, "failures"] as const,
  findings: (projectId: string) => ["testing", projectId, "findings"] as const,
  quality: (projectId: string) => ["testing", projectId, "quality"] as const,
  audit: (projectId: string) => ["testing", projectId, "audit"] as const,
  testFiles: (projectId: string) => ["testing", projectId, "test-files"] as const,
  file: (projectId: string, path: string, version: number) =>
    ["testing", projectId, "file", version, path] as const,
};

export const deploymentKeys = {
  all: ["deployment"] as const,
  snapshot: (projectId: string) => ["deployment", projectId, "snapshot"] as const,
  targets: (projectId: string) => ["deployment", projectId, "targets"] as const,
  file: (projectId: string, path: string, version: number) =>
    ["deployment", projectId, "file", version, path] as const,
};

export const activityKeys = {
  all: ["activity"] as const,
  list: (projectId: string) => ["activity", projectId] as const,
};

export const requirementsKeys = {
  all: ["requirements"] as const,
  design: (projectId: string) => ["requirements", projectId, "design"] as const,
};

export const codeKeys = {
  all: ["code"] as const,
  snapshot: (projectId: string) => ["code", projectId, "snapshot"] as const,
  file: (projectId: string, path: string, version: number) =>
    ["code", projectId, "file", version, path] as const,
  preview: (projectId: string) => ["code", projectId, "preview"] as const,
};

export function createQueryClientOptions() {
  return {
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: 1,
        // A tab left open offered a decision made elsewhere since: it never
        // read again on coming back. Only what is older than `staleTime` is
        // read, and a file at a version (stale never) is not.
        refetchOnWindowFocus: true,
      },
    },
  } as const;
}

export interface QueryClientHooks {
  /** Told of every failed mutation that does not report its own failure. */
  onMutationError?: (error: unknown) => void;
}

/**
 * The one query client, with every mutation failure reported once.
 *
 * Most mutations only said what to do on success and nothing handled the rest,
 * so Approve, Send, Answer, Save and Try again stopped spinning and nothing
 * happened. The cache's own callback runs for every mutation, whatever it
 * declares locally, which is what makes "no silent failure" a property of the
 * app rather than of each call site remembering.
 */
export function createQueryClient(hooks: QueryClientHooks = {}) {
  return new QueryClient({
    ...createQueryClientOptions(),
    mutationCache: new MutationCache({
      onError: (error, _variables, _result, mutation) => {
        if (mutation.meta?.reportsOwnErrors) return;
        hooks.onMutationError?.(error);
      },
    }),
  });
}
