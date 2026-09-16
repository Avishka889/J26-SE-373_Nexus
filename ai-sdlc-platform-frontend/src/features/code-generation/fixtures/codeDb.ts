import { getProjectsSnapshot } from "@/entities/project";
import { BLANK_SEED, DESIGN_SEEDS } from "@/entities/design-seed";
import type { ProjectStatus } from "@/types/project";
import type { CodeSnapshot } from "../api/types";
import { buildCodeSnapshot, type CodePosture } from "./buildCodeSnapshot";

/**
 * The code artefact, held in memory for the session the way the orchestrator
 * holds it for good. Every mutation reads, changes and writes the whole
 * snapshot, so the fixture behaves exactly like the service and the swap needs
 * no change in the UI.
 */

/**
 * How far through the code phase a project's own status says it is.
 *
 * Derived rather than written down beside each project, for the reason the
 * design fixtures derive theirs: a project cannot be in Testing without having
 * passed the code gate, and it cannot be in Design with code already
 * generated. Deriving it is what stops a badge and a phase contradicting each
 * other.
 *
 * This is why the four demo projects sit where they do, which is not where the
 * plan guessed: MediTrack is the one in `code`, so MediTrack is the project
 * waiting on a code review and the one the end to end spec drives. NexusPay is
 * in `testing`, so its code was approved and reads as decided.
 */
export function codePostureFor(status: ProjectStatus): CodePosture {
  switch (status) {
    case "draft":
    case "analyzing":
    case "design":
      // The design gate has not been passed, so there is nothing settled to
      // generate from and the phase honestly has nothing in it.
      return "not-started";
    case "code":
      return "awaiting";
    default:
      // testing, deploy, complete. Each is downstream of the code gate.
      return "approved";
  }
}

export function seedCodeSnapshot(projectId: string): CodeSnapshot {
  const seed = DESIGN_SEEDS[projectId] ?? BLANK_SEED;
  const project = getProjectsSnapshot().find((p) => p.id === projectId);
  const posture = project
    ? codePostureFor(project.status)
    : DESIGN_SEEDS[projectId]
      ? "awaiting"
      : "not-started";
  return buildCodeSnapshot(projectId, seed, posture, 1);
}

let codeDb: Record<string, CodeSnapshot> = {};

const DESIGN_NOT_APPROVED =
  "this project's design has not been approved, so there is nothing settled to generate code from";

/**
 * The server's `designBlocker`, as the demo can know it: from the project's
 * status, which is the fact the page read before the server said it.
 */
function withDesignBlocker(projectId: string, snapshot: CodeSnapshot): CodeSnapshot {
  const status = getProjectsSnapshot().find((p) => p.id === projectId)?.status;
  const approved =
    status === "code" || status === "testing" || status === "deploy" || status === "complete";
  return { ...snapshot, designBlocker: approved ? null : DESIGN_NOT_APPROVED };
}

export function readCode(projectId: string): CodeSnapshot {
  codeDb[projectId] ??= seedCodeSnapshot(projectId);
  return withDesignBlocker(projectId, structuredClone(codeDb[projectId]));
}

export function writeCode(projectId: string, next: CodeSnapshot): CodeSnapshot {
  codeDb[projectId] = next;
  return withDesignBlocker(projectId, structuredClone(next));
}

/** Read, change, write. The draft is already a clone, so it is safe to mutate. */
export function mutateCode(
  projectId: string,
  change: (draft: CodeSnapshot) => void,
): CodeSnapshot {
  const draft = readCode(projectId);
  change(draft);
  return writeCode(projectId, draft);
}

/** Tests only. */
export function resetCodeDb() {
  codeDb = {};
}
