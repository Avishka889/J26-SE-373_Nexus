import type {
  ArchitectureRecommendation,
  Assumption,
  ClarifyingQuestion,
  GraphEdge,
  GraphNode,
  ParsedRequirement,
  SprintPlan,
  UmlDiagram,
  UseCase,
  WireframeFlow,
} from "@sdlc/contracts-ts";

/**
 * A seeded question, with the answer it was given if the design was approved.
 *
 * `presetAnswer` is fixture sugar and never reaches the contract: an approved
 * project must not show open questions, and inventing "Answered during review"
 * for every one of them would read as filler. The builder strips the field.
 */
export interface SeedQuestion extends ClarifyingQuestion {
  presetAnswer?: string;
}

/**
 * One project's design content.
 *
 * Every project has its own, because a shared snapshot made four projects show
 * the same twelve payment requirements: a commerce platform claimed a KYC
 * threshold, and a project already in Testing showed an undecided design gate.
 *
 * What is deliberately absent: stage statuses, stage summaries, the gate
 * decision, the thread and the coverage table. Those are all derived by
 * `buildSnapshot` from the content below plus how far the project has got, so a
 * seed cannot state a count that disagrees with its own artifacts.
 */
export interface ProjectDesignSeed {
  /** The product name the wireframe player puts in its breadcrumb. */
  appName: string;
  requirements: ParsedRequirement[];
  assumptions: Assumption[];
  questions: SeedQuestion[];
  nodes: GraphNode[];
  edges: GraphEdge[];
  /** Null until the recommendation stage would have run, as the wire has it. */
  architecture: ArchitectureRecommendation | null;
  useCases: UseCase[];
  diagrams: UmlDiagram[];
  flows: WireframeFlow[];
  sprint: SprintPlan;
}

/**
 * How far a project has got, which is what makes its gate state coherent.
 *
 * `empty`: nothing generated yet, so every stage is pending and no decision is
 * possible. A project created from the home composer starts here.
 *
 * `awaiting`: everything generated, nobody has decided. Exactly one project is
 * in this state in the demo, and it is the only one that shows the decision bar.
 *
 * `approved`: the design was approved, which is how the project reached Code
 * Generation or later. Its questions are answered and its architecture is
 * chosen, because it could not have been approved otherwise.
 */
export type DesignPosture = "empty" | "awaiting" | "approved";
