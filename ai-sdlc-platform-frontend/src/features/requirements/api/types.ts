/**
 * The C1 display contract, re-exported from the generated package.
 *
 * `@sdlc/contracts-ts` is generated from the committed JSON Schemas, which are
 * generated from the Pydantic models: one author, two derived artefacts. This
 * file used to hand maintain a copy of every interface, protected by a CI test
 * that compared field names; re-exporting makes drift impossible by
 * construction instead, in nullability too, which the name comparison could
 * never see.
 *
 * Only two kinds of declaration remain hand written here: the union aliases,
 * which are derived from the generated interfaces by indexed access so they
 * cannot drift either, and the API seam types, which are this client's own
 * vocabulary rather than anything the wire carries.
 */

import type {
  DesignSnapshot as WireDesignSnapshot,
  DesignThreadMessage,
  GraphEdge,
  GraphNode,
  ParsedRequirement,
  ScreenBlock,
  StageState,
  UmlDiagram,
} from "@sdlc/contracts-ts";
import type { DesignStageId } from "@/types/project";

export type {
  AcceptanceCriterion,
  ArchitectureGraph,
  ArchitectureRecommendation,
  ArchitectureStyleNote,
  Assumption,
  ClarifyingQuestion,
  ConsistencyFinding,
  DesignThreadMessage,
  EntityAttribute,
  FlowLink,
  FlowScreen,
  GateDecision,
  GateState,
  GraphEdge,
  GraphNode,
  ParsedRequirement,
  ScreenBlock,
  SequenceStep,
  SprintPlan,
  StageState,
  TopologyCandidate,
  UmlArtefact,
  UmlDiagram,
  UseCase,
  UserStory,
  ValidationFinding,
  WireframeCoverageRow,
  WireframeFlow,
  WireframesArtefact,
} from "@sdlc/contracts-ts";

/* ------------------------------------------------------- derived aliases */
/* Indexed access into the generated interfaces, so renaming or widening a
   union on the wire changes these in the same regeneration. */

export type StageStatus = StageState["status"];
export type RequirementType = ParsedRequirement["type"];
export type RequirementPriority = ParsedRequirement["priority"];
export type QualityAttribute = NonNullable<ParsedRequirement["qualityAttribute"]>;
export type GraphNodeKind = GraphNode["kind"];
export type ActorKind = NonNullable<GraphNode["actorKind"]>;
export type GraphEdgeKind = GraphEdge["kind"];
export type UmlDiagramKind = UmlDiagram["kind"];
export type ScreenBlockKind = ScreenBlock["kind"];
export type ThreadMessageKind = DesignThreadMessage["kind"];

/* -------------------------------------------------------------- snapshot */

/**
 * The generated snapshot types `stages` as a string index, because JSON Schema
 * cannot say "exactly these eight keys". The server validates that every stage
 * id is present before a snapshot leaves it, so the client may read
 * `stages[id]` without a guard; this narrows the key set to say so. A checked
 * refinement of the generated shape, not a fork: every other field is the
 * generated one, and TypeScript verifies the override is assignable.
 */
export interface DesignSnapshot extends Omit<WireDesignSnapshot, "stages"> {
  stages: Record<DesignStageId, StageState>;
}

/* ------------------------------------------------------------------ api */

export interface GateDecisionInput {
  kind: "approved" | "changes";
  by: string;
  note?: string;
}

/**
 * Every mutation answers with the whole snapshot. The client then never
 * re-derives partial state, and the backend swap needs no invalidation
 * choreography.
 */
export interface RequirementsApi {
  getDesign(projectId: string): Promise<DesignSnapshot>;
  /**
   * Start generating the design from a requirement input.
   *
   * The requirement text arriving is the whole start signal: there is no
   * separate "run the pipeline" call, and the client owns no timer. Stages move
   * to complete one at a time on the server side, and the client learns about it
   * by reading the snapshot again, which is why every status indicator can be
   * derived from one place.
   */
  startDesignRun(projectId: string, text: string, files?: string[]): Promise<DesignSnapshot>;
  /** Run every design stage again at the current version, after a run that stopped. */
  startOver(projectId: string): Promise<DesignSnapshot>;
  editRequirement(projectId: string, requirementId: string, text: string): Promise<DesignSnapshot>;
  editAssumption(projectId: string, assumptionId: string, text: string): Promise<DesignSnapshot>;
  dismissAssumption(projectId: string, assumptionId: string, dismissed: boolean): Promise<DesignSnapshot>;
  answerQuestion(projectId: string, questionId: string, answer: string): Promise<DesignSnapshot>;
  /**
   * Regenerate the design with the answers given: the reader's own act, since it
   * runs the model again. At a pending review it is the review's request for changes.
   */
  applyAnswers(projectId: string): Promise<DesignSnapshot>;
  /**
   * Go on from the design's questions while its run is paused on them: with the
   * answers, which analyses the requirements again with them, or with the
   * assumptions, which builds the rest on what the analysis assumed.
   */
  continueFromQuestions(
    projectId: string,
    kind: "answers" | "assumptions",
  ): Promise<DesignSnapshot>;
  selectArchitecture(projectId: string, candidateId: string, by: string): Promise<DesignSnapshot>;
  renameGraphNode(projectId: string, nodeId: string, label: string): Promise<DesignSnapshot>;
  requestWireframeRefinement(projectId: string, flowId: string, note: string): Promise<DesignSnapshot>;
  /** Adds a change or clarification, which bumps the requirements version. */
  submitChange(projectId: string, note: string, by: string): Promise<DesignSnapshot>;
  retryStage(projectId: string, stageId: DesignStageId): Promise<DesignSnapshot>;
  /** Go on with the phase's stopped run from where it stopped. */
  continueRun(projectId: string, runId: string): Promise<DesignSnapshot>;
  submitGateDecision(projectId: string, decision: GateDecisionInput): Promise<DesignSnapshot>;
}
