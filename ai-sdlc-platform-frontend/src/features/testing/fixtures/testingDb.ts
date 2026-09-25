import { getProjectsSnapshot } from "@/entities/project";
import type { ProjectStatus } from "@/types/project";
import type { TestSnapshot } from "../api/types";
import { buildTestSnapshot, type TestPosture } from "./buildTestSnapshot";

/**
 * The testing artefacts, held in memory for the session the way the
 * orchestrator holds them for good. Every mutation reads, changes and writes
 * the whole snapshot, so the fixture behaves exactly like the service and the
 * swap needs no change in the UI.
 */

/**
 * How far through the testing phase a project's own status says it is.
 *
 * Derived rather than written beside each project, for the reason the code
 * fixtures derive theirs: a project cannot be in Deploy without having passed
 * the test gate, and it cannot be in Code with tests already run. Deriving it
 * is what stops a badge and a phase contradicting each other.
 */
export function testPostureFor(status: ProjectStatus): TestPosture {
  switch (status) {
    case "draft":
    case "analyzing":
    case "design":
    case "code":
      // The code gate has not been passed, so there is nothing approved to
      // test and the phase honestly has nothing in it.
      return "not-started";
    case "testing":
      return "awaiting";
    default:
      // deploy, complete. Each is downstream of the test gate.
      return "approved";
  }
}

export function seedTestSnapshot(projectId: string): TestSnapshot {
  const project = getProjectsSnapshot().find((one) => one.id === projectId);
  const posture = project ? testPostureFor(project.status) : "not-started";
  // The code version a demo project is at. One, because the fixtures generate
  // once; a project that regenerated would carry the newer number and the
  // snapshot's `codeMovedOn` would then be true, which is a state worth
  // demonstrating but not the default one.
  return buildTestSnapshot(projectId, posture, posture === "not-started" ? 0 : 1);
}

let testingDb: Record<string, TestSnapshot> = {};

export function readTesting(projectId: string): TestSnapshot {
  testingDb[projectId] ??= seedTestSnapshot(projectId);
  return structuredClone(testingDb[projectId]);
}

export function writeTesting(projectId: string, next: TestSnapshot): TestSnapshot {
  testingDb[projectId] = next;
  return structuredClone(next);
}

/** Read, change, write. The draft is already a clone, so it is safe to mutate. */
export function mutateTesting(
  projectId: string,
  change: (draft: TestSnapshot) => void,
): TestSnapshot {
  const draft = readTesting(projectId);
  change(draft);
  return writeTesting(projectId, draft);
}

/** Tests only. */
export function resetTestingDb() {
  testingDb = {};
}
