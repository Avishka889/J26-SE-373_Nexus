import { useSyncExternalStore } from "react";
import { useQuery } from "@tanstack/react-query";
import { settingsKeys } from "@/lib/query";
import type { SettingsState } from "@/types/settings";
import {
  type SettingsLoad,
  getSettingsLoad,
  getSettingsSnapshot,
  reloadSettings,
  settingsApi,
  subscribeSettings,
} from "./api";
import {
  type Connection,
  type ConnectionsLoad,
  connectionsApi,
  getConnectionsLoad,
  getConnectionsSnapshot,
  subscribeConnections,
} from "./connections";
import {
  type PhaseKey,
  type PhaseModel,
  type RunSetup,
  type RunsOn,
  phaseModels,
  runsOn,
} from "./models";

export function useSettings(): SettingsState {
  return useSyncExternalStore(
    subscribeSettings,
    getSettingsSnapshot,
    getSettingsSnapshot,
  );
}

/** Whether the server's settings have arrived, so a page shows them and not the defaults. */
export function useSettingsLoad(): SettingsLoad {
  return useSyncExternalStore(
    subscribeSettings,
    getSettingsLoad,
    getSettingsLoad,
  );
}

export function useSettingsActions() {
  return {
    reloadSettings: () => reloadSettings(),
    updateSettings: (patch: Partial<SettingsState>) =>
      settingsApi.update(patch),
    updateGitSettings: (patch: Partial<SettingsState["git"]>) =>
      settingsApi.updateGit(patch),
    updateVercelSettings: (patch: Partial<SettingsState["vercel"]>) =>
      settingsApi.updateVercel(patch),
    updateRenderSettings: (patch: Partial<SettingsState["render"]>) =>
      settingsApi.updateRender(patch),
    updateDatabaseSettings: (patch: Partial<SettingsState["database"]>) =>
      settingsApi.updateDatabase(patch),
    updateProfile: (patch: Partial<SettingsState["profile"]>) =>
      settingsApi.updateProfile(patch),
  };
}

export function useConnections(): Connection[] {
  return useSyncExternalStore(
    subscribeConnections,
    getConnectionsSnapshot,
    getConnectionsSnapshot,
  );
}

/** Where the read of the connections stands: on its way, read, or failed with a reason. */
export function useConnectionsLoad(): ConnectionsLoad {
  return useSyncExternalStore(subscribeConnections, getConnectionsLoad, getConnectionsLoad);
}

export function useConnectionsActions() {
  return {
    connect: (provider: string, token: string) =>
      connectionsApi.create(provider, token),
    revoke: (provider: string) => connectionsApi.revoke(provider),
    probe: (provider: string) => connectionsApi.probe(provider),
  };
}

/** Each phase's model and thinking, as the server reports them. */
export function usePhaseModels() {
  return useQuery({ queryKey: settingsKeys.models, queryFn: phaseModels });
}

/** One phase's, once read: undefined while reading, after a read that failed, and in the demo. */
export function usePhaseModel(key: PhaseKey): PhaseModel | undefined {
  return usePhaseModels().data?.find((phase) => phase.key === key);
}

/**
 * The line under a phase's chat box: what a send runs on (`runsOn`). `waiting`
 * is the run a send would regenerate, which is the phase's run while a review
 * waits and nothing otherwise.
 */
export function useRunsOn(key: PhaseKey, waiting: RunSetup | null | undefined): RunsOn | undefined {
  return runsOn(usePhaseModel(key), waiting ?? null) ?? undefined;
}
