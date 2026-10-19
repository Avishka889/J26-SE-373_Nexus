/**
 * The deployment display contract, re-exported from the generated package.
 *
 * `@sdlc/contracts-ts` is generated from the committed JSON Schemas, which are
 * generated from the Pydantic models, so the snapshot this phase renders is the
 * one the orchestrator returns by construction. The previous deployment page
 * had a vocabulary of its own (five stages the server never had, a risk score
 * no rule produced), which is why it could only ever be a demo.
 *
 * Two kinds of declaration are written here and only two: `DeployStages`,
 * because the generator emits an index signature where the server guarantees
 * all ten keys, and the API seam types, which are this client's own vocabulary
 * for the routes under `/projects/{id}/deployment`.
 */

import type {
  DeploySnapshot as WireDeploySnapshot,
  DeployStageState,
  DeploymentView,
} from "@sdlc/contracts-ts";
import type { DeployStageId } from "@/types/project";

export type {
  Blocker,
  BuildStepReport,
  ChangelogAnalysis,
  ChangelogClaim,
  ChangelogReport,
  DependencyUpdate,
  DependencyUpdates,
  DeployPlan,
  DeployStageState,
  DeployThreadMessage,
  DeploymentStepView,
  DeploymentView,
  EvidenceRef,
  FeedbackDecisionView,
  FeedbackItem,
  FeedbackReport,
  GateDecision,
  GateState,
  ImpactReport,
  MonitoringReport,
  PipelineConfig,
  PipelineFile,
  ReleaseCandidate,
  RiskReport,
  RollbackPlan,
  SignalVote,
  UpdateAssessment,
  UpdateDecisionView,
  VerifiedRelease,
} from "@sdlc/contracts-ts";

/**
 * All ten stages, always.
 *
 * The generated type is an index signature, because JSON Schema says
 * `additionalProperties`, but the server's snapshot validator refuses to return
 * one without every key. Narrowing it here is what lets a stage panel index
 * `stages[id]` with no null guard.
 */
export type DeployStages = Record<DeployStageId, DeployStageState>;

export type DeploySnapshot = Omit<WireDeploySnapshot, "stages"> & { stages: DeployStages };

export type RiskLevel = "low" | "medium" | "high";

export type ReleaseTarget = "local" | "cloud";

/** Where a release can go, and whether it can go there from this orchestrator. */
export type ReleaseTargetOption = {
  id: ReleaseTarget;
  label: string;
  usable: boolean;
  /** Why it cannot be used, when it cannot. */
  reason: string;
};

type Actor = { by: string };

export type DeployDecisionInput = Actor & {
  kind: "approved" | "changes";
  note?: string;
  /** A cloud release spends provider minutes, so an approval says so explicitly. */
  goAhead?: boolean;
};

export type UpdateDecisionInput = Actor & {
  decision: "approved" | "rejected" | "deferred";
  note?: string;
};

export type RollbackDecisionInput = Actor & {
  decision: "approved" | "rejected";
  note?: string;
};

export type FeedbackDecisionInput = Actor & {
  decision: "sent" | "dismissed";
  note?: string;
};

export type PolicyInput = Actor & {
  autoDeployLow: boolean;
  cloudAutoDeploy?: boolean;
};

export type MonitoringWindowInput = {
  rounds?: number;
  /** Seconds between probe rounds. */
  interval?: number;
};

/**
 * Every call this phase makes, each answering with the whole snapshot.
 *
 * The same shape on both sides of the seam, so a component cannot tell whether
 * the fixtures or the orchestrator answered.
 */
/** One generated deployment file's body, fetched when a reader opens it. */
export type DeployFile = { path: string; version: number; stage: string; content: string };

export type DeploymentApi = {
  getDeployment(projectId: string): Promise<DeploySnapshot>;
  /** A generated file's body at a deploy version: the snapshot carries none. */
  getFile(projectId: string, path: string, version: number): Promise<DeployFile>;
  listTargets(projectId: string): Promise<ReleaseTargetOption[]>;
  chooseTarget(projectId: string, target: ReleaseTarget, by: string): Promise<DeploySnapshot>;
  /** The packages the next run analyses; empty for every dependency. */
  chooseScope(projectId: string, packages: string[], by: string): Promise<DeploySnapshot>;
  /** The ledger beyond the newest ten a snapshot carries. */
  listLedger(projectId: string, limit: number): Promise<DeploymentView[]>;
  choosePolicy(projectId: string, policy: PolicyInput): Promise<DeploySnapshot>;
  run(projectId: string): Promise<DeploySnapshot>;
  retryStage(projectId: string, stageId: DeployStageId): Promise<DeploySnapshot>;
  /** Go on with the phase's stopped run from where it stopped. */
  continueRun(projectId: string, runId: string): Promise<DeploySnapshot>;
  decideUpdate(
    projectId: string,
    updateId: string,
    decision: UpdateDecisionInput,
  ): Promise<DeploySnapshot>;
  submitDecision(projectId: string, decision: DeployDecisionInput): Promise<DeploySnapshot>;
  decideRollback(
    projectId: string,
    deploymentId: string,
    decision: RollbackDecisionInput,
  ): Promise<DeploySnapshot>;
  /** Release the same approved version again, after a release undone before traffic moved. */
  releaseAgain(projectId: string, deploymentId: string): Promise<DeploySnapshot>;
  openMonitoringWindow(
    projectId: string,
    window?: MonitoringWindowInput,
  ): Promise<DeploySnapshot>;
  decideFeedback(
    projectId: string,
    itemId: string,
    decision: FeedbackDecisionInput,
  ): Promise<DeploySnapshot>;
  /** Send suggestions to requirements as one design change: one version, one run. */
  sendFeedback(projectId: string, itemIds: string[], actor: Actor): Promise<DeploySnapshot>;
};
