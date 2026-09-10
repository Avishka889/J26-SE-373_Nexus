import { getProjectsSnapshot } from "@/entities/project";
import type { DesignSnapshot, DesignThreadMessage } from "../api/types";
import { buildSnapshot, demoStamp, recomputeCoverage, stageSummary } from "./buildSnapshot";
import { BLANK_SEED, DESIGN_SEEDS, postureFor } from "@/entities/design-seed";

/**
 * The design artifact, held in memory for the session the way the orchestrator
 * will hold it for good. Every mutation reads, changes and writes the whole
 * snapshot, so the fixture behaves exactly like the future service and the swap
 * needs no change in the UI.
 *
 * Keyed by project id in both directions: which content a project gets, and how
 * far through the phase it is. Both come from the project itself, so a project's
 * badge and its design can never contradict each other.
 */

export function seedDesignSnapshot(projectId: string): DesignSnapshot {
  const seed = DESIGN_SEEDS[projectId] ?? BLANK_SEED;
  const project = getProjectsSnapshot().find((p) => p.id === projectId);

  // No project means a test asked for a snapshot directly. An authored seed is
  // shown as awaiting a decision, which is the state most tests care about; a
  // project with no content of its own starts empty, as a new one does.
  const posture = project
    ? postureFor(project.status)
    : DESIGN_SEEDS[projectId]
      ? "awaiting"
      : "empty";

  return buildSnapshot(projectId, seed, posture, project?.requirementText ?? "");
}

let designDb: Record<string, DesignSnapshot> = {};

export function readDesign(projectId: string): DesignSnapshot {
  designDb[projectId] ??= seedDesignSnapshot(projectId);
  return structuredClone(designDb[projectId]);
}

export function writeDesign(projectId: string, next: DesignSnapshot): DesignSnapshot {
  designDb[projectId] = next;
  return structuredClone(next);
}

/** Read, change, write. The draft is already a clone, so it is safe to mutate. */
export function mutateDesign(
  projectId: string,
  change: (draft: DesignSnapshot) => void,
): DesignSnapshot {
  const draft = readDesign(projectId);
  change(draft);
  return writeDesign(projectId, draft);
}

/** Tests only. */
export function resetDesignDb() {
  designDb = {};
}

/* ------------------------------------------------------------- helpers */

let threadSeq = 0;
export function appendThread(
  draft: DesignSnapshot,
  message: Omit<DesignThreadMessage, "id" | "at" | "producedVersion" | "question"> &
    Partial<Pick<DesignThreadMessage, "producedVersion" | "question">>,
  at: string,
) {
  threadSeq += 1;
  draft.thread = [
    ...draft.thread,
    { producedVersion: null, question: null, ...message, id: `t-live-${threadSeq}`, at },
  ];
}

export { buildSnapshot, demoStamp, recomputeCoverage, stageSummary };
