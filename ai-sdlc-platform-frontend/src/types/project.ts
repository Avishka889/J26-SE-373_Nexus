/** Shared project domain types, owned by contracts eventually; UI imports from here. */

export type ProjectStatus =
  | "draft"
  | "analyzing"
  | "design"
  | "code"
  | "testing"
  | "deploy"
  | "complete";

/**
 * The Requirements and Design stages, in order, keyed to the artifact each one
 * produces. These are the contract keys the C1 service will use, so the backend
 * swap maps one to one. Visible labels live in the feature (model/stages.ts):
 * this file owns identity and order only.
 *
 * `types/contracts.ts` reads this too, and a type file may not import a
 * feature, so the tuple has to live here.
 */
export const DESIGN_STAGE_IDS = [
  "requirements",
  "domain-model",
  "architecture-graph",
  "architecture-recommendation",
  "uml-diagrams",
  "wireframes",
  "sprint-plan",
  "design-review",
] as const;

export type DesignStageId = (typeof DESIGN_STAGE_IDS)[number];

/**
 * The Code Generation stages, in order, keyed to what each one produces.
 *
 * Kept apart from the design tuple on purpose, exactly as the contracts keep
 * them apart: `DesignStageId` types the design snapshot and everything C1, so
 * adding to it would silently change that phase's progress arithmetic and its
 * stage validators. Two phases, two vocabularies, one shared chrome.
 *
 * The repository push happens inside `build`, so it is not a stage of its own;
 * its result lives on the artefact that stage writes.
 */
export const CODE_STAGE_IDS = [
  "sprint-scope",
  "tech-stack",
  "api-contract",
  "frontend-code",
  "backend-code",
  "contract-agreement",
  "build",
  "code-review",
] as const;

export type CodeStageId = (typeof CODE_STAGE_IDS)[number];

/**
 * The Testing and Security stages, in order, keyed to what each one produces.
 *
 * A third vocabulary for the third axis, kept apart from the other two for the
 * reason the contracts keep them apart: `TestStageId` types the testing
 * snapshot, so adding to the code tuple would silently change this phase's
 * progress arithmetic and its stage validators.
 *
 * Six produce an artefact and `test-review` is the gate, which produces none.
 * A gate is a decision rather than a document, and the stepper still shows it
 * because that is where the reader is going.
 */
export const TEST_STAGE_IDS = [
  "test-generation",
  "test-run",
  "test-quality",
  "self-healing",
  "security-scan",
  "remediation",
  "test-review",
] as const;

export type TestStageId = (typeof TEST_STAGE_IDS)[number];

/**
 * The Deployment stages, in order, keyed to what each one produces.
 *
 * A fourth vocabulary for the fourth axis, kept apart for the same reason as
 * the other three. Seven are produced by the deployment service,
 * `deployment-review` is the gate, and the last two are carried out by the
 * orchestrator after the gate: a release and a monitoring window outlive the
 * run that proposed them, so their state comes from the deployment ledger
 * rather than from the run.
 */
export const DEPLOY_STAGE_IDS = [
  "dependency-updates",
  "changelog-analysis",
  "impact-analysis",
  "risk-assessment",
  "pipeline-generation",
  "staging-verification",
  "rollback-planning",
  "deployment-review",
  "release",
  "monitoring",
] as const;

export type DeployStageId = (typeof DEPLOY_STAGE_IDS)[number];

/** `input` is the pre-stage: nothing has been generated yet. */
export type ReqPhase = "input" | DesignStageId;

export type RequirementChatRole = "user" | "assistant";
export type RequirementChatType = "source_requirement" | "chat";

export interface RequirementChatMessage {
  id: string;
  role: RequirementChatRole;
  type: RequirementChatType;
  content: string;
  createdAt: string;
}

export interface Project {
  id: string;
  name: string;
  description: string;
  status: ProjectStatus;
  createdAt: string;
  updatedAt: string;
  requirementText: string;
  requirementChat: RequirementChatMessage[];
  files: string[];
  reqPhase: ReqPhase;
  /** The whole project: the mean of `phaseProgress`, rounded half up. */
  progress: number;
  /**
   * Each phase's own progress, as the server derives it. A phase's stages carry
   * 80 of its 100 and its approval the last 20 (for Deployment, a verified
   * release), so a phase waiting on its review reads 80.
   */
  phaseProgress?: PhaseProgress;
  /**
   * The newest run of the phase the project is in stopped before finishing,
   * and nothing is running there now. Its page says why and how to go on.
   */
  runStopped?: boolean;
  techStack: string[];
  color: string;
}

export interface PhaseProgress {
  design: number;
  code: number;
  testing: number;
  deployment: number;
}
