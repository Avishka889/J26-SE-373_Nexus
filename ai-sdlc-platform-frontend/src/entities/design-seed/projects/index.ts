import type { ProjectStatus } from "@/types/project";
import type { DesignPosture, ProjectDesignSeed } from "../projectSeed";
import { nexuspaySeed } from "./nexuspay";
import { shopflowSeed } from "./shopflow";
import { meditrackSeed } from "./meditrack";
import { notifyhubSeed } from "./notifyhub";

/**
 * Which design content belongs to which project.
 *
 * Keyed by project id, because serving one snapshot to everything is what made a
 * commerce platform show a KYC threshold and a project in Testing show an
 * undecided design gate.
 */
export const DESIGN_SEEDS: Record<string, ProjectDesignSeed> = {
  p1: nexuspaySeed,
  p2: meditrackSeed,
  p3: shopflowSeed,
  p4: notifyhubSeed,
};

/**
 * A project the demo has no authored content for.
 *
 * Used for anything created during the session. It is empty rather than a copy
 * of one of the four, because a new project genuinely has nothing yet, and the
 * generation timer is what fills it in.
 */
export const BLANK_SEED: ProjectDesignSeed = {
  appName: "App",
  requirements: [],
  assumptions: [],
  questions: [],
  nodes: [],
  edges: [],
  // Null, as the server sends it before the recommendation stage has run. An
  // empty recommendation would violate the contract's floor of two candidates.
  architecture: null,
  useCases: [],
  diagrams: [],
  flows: [],
  sprint: {
    sprintName: "Sprint 1",
    goal: "",
    velocityAssumption: { points: 0, basis: "" },
    estimatedPoints: 0,
    proposed: [],
    backlog: [],
  },
};

/**
 * The design posture a project's own progress implies.
 *
 * This is derived rather than written down beside each seed, so a project's badge
 * and its gate can never disagree: a project cannot be in Testing without having
 * passed the design gate, and it cannot be in Design with the gate already
 * decided.
 */
export function postureFor(status: ProjectStatus): DesignPosture {
  switch (status) {
    case "draft":
    case "analyzing":
      return "empty";
    case "design":
      return "awaiting";
    default:
      // code, testing, deploy, complete. Each is downstream of the design gate,
      // so the design must already have been approved to have reached it.
      return "approved";
  }
}
