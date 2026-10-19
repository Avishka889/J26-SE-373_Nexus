import { getProjectsSnapshot } from "@/entities/project";
import type { DeploySnapshot } from "../api/types";
import { buildDeploySnapshot, withDerived } from "./buildDeploySnapshot";
import type { UpdateDecisionRecord } from "./rules";

/**
 * The deployment phase, held in memory for the session the way the
 * orchestrator holds it for good.
 *
 * Beside each snapshot sit the records the read model derives from: the
 * decisions people took about updates, keyed by update, so a decision follows
 * the update across versions exactly as the overlay does on the server. Every
 * mutation reads, changes, recomputes what the read model derives, and writes.
 */

type Entry = {
  snapshot: DeploySnapshot;
  decisions: Record<string, UpdateDecisionRecord>;
};

let deployDb: Record<string, Entry> = {};

function seed(projectId: string): Entry {
  const status = getProjectsSnapshot().find((one) => one.id === projectId)?.status ?? "draft";
  return { snapshot: buildDeploySnapshot(projectId, status), decisions: {} };
}

function entry(projectId: string): Entry {
  deployDb[projectId] ??= seed(projectId);
  return deployDb[projectId];
}

export function readDeployment(projectId: string): DeploySnapshot {
  return structuredClone(entry(projectId).snapshot);
}

export function readDecisionRecords(projectId: string): Record<string, UpdateDecisionRecord> {
  return structuredClone(entry(projectId).decisions);
}

/** Read, change, recompute, write. The drafts are clones, so they are safe to mutate. */
export function mutateDeployment(
  projectId: string,
  change: (draft: DeploySnapshot, decisions: Record<string, UpdateDecisionRecord>) => void,
): DeploySnapshot {
  const current = entry(projectId);
  const draft = structuredClone(current.snapshot);
  const decisions = structuredClone(current.decisions);
  change(draft, decisions);
  deployDb[projectId] = { snapshot: withDerived(draft), decisions };
  return structuredClone(deployDb[projectId].snapshot);
}

/** Tests only. */
export function resetDeployDb() {
  deployDb = {};
}
