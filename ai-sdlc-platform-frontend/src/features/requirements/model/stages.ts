import { DESIGN_STAGE_IDS, type DesignStageId } from "@/types/project";

/**
 * How each stage presents itself. Identity and order live in `types/project`
 * because `shared/` and `entities/` read them too; only the words live here.
 *
 * Typing this as a Record over the id union means a new stage cannot be added
 * without giving it a label, so the two can never drift apart again.
 */
export type StageMeta = {
  /** The chevron label: short, and no unexplained abbreviations. */
  label: string;
  /** The stage header, which may spell out what the label abbreviates. */
  heading: string;
  /** One line under the heading saying what this stage is for. */
  blurb: string;
};

export const STAGE_META: Record<DesignStageId, StageMeta> = {
  requirements: {
    label: "Requirements Analysis",
    heading: "Requirements Analysis",
    blurb:
      "What the system has to do, parsed from your input and open to correction.",
  },
  "domain-model": {
    label: "Domain Model",
    heading: "Domain Model",
    blurb: "The actors, the things they act on, and who does what to what.",
  },
  "architecture-graph": {
    label: "Architecture Graph",
    heading: "Semantic Architecture Graph (SAG)",
    blurb:
      "One typed graph of the system, and the source every other artifact is generated from.",
  },
  "architecture-recommendation": {
    label: "Architecture Recommendation",
    heading: "Architecture Recommendation",
    blurb:
      "Candidate shapes scored against the parsed scope and constraints. You pick one.",
  },
  "uml-diagrams": {
    label: "UML Diagrams",
    heading: "UML Diagrams",
    blurb:
      "Class, entity relationship, activity and sequence views of the same graph.",
  },
  wireframes: {
    label: "Wireframes",
    heading: "Wireframes",
    blurb:
      "A screen per user journey, clickable, and checked against the backlog for coverage.",
  },
  "sprint-plan": {
    label: "Sprint Planning",
    heading: "Sprint Planning",
    blurb:
      "A proposed first sprint and the remaining backlog, ordered by priority.",
  },
  "design-review": {
    label: "Design Review",
    heading: "Design Review",
    blurb:
      "Everything above in one place, and the decision that starts Code Generation.",
  },
};

export const stageIds = DESIGN_STAGE_IDS;

export function stageLabel(id: DesignStageId): string {
  return STAGE_META[id].label;
}

/** Index in the pipeline, or -1 for the `input` pre-stage. */
export function stageIndex(id: string): number {
  return DESIGN_STAGE_IDS.indexOf(id as DesignStageId);
}

export function isDesignStageId(id: string): id is DesignStageId {
  return stageIndex(id) >= 0;
}

/**
 * The blocks a stage is made of, in the order they appear.
 *
 * These are the anchor pills, and they double as the reader's position
 * indicator, so the list has to match what the stage actually renders. A stage
 * with one block gets no pills: a single anchor pointing at the whole page is
 * noise.
 *
 * The id is used verbatim as the DOM id, so it has to stay unique across a
 * stage. Prefixing with the stage id keeps that true without thinking about it.
 */
export type StageSection = { id: string; label: string };

export const STAGE_SECTIONS: Record<DesignStageId, StageSection[]> = {
  requirements: [
    { id: "requirements-summary", label: "Summary" },
    { id: "requirements-list", label: "Requirements" },
    { id: "requirements-assumptions", label: "Assumptions" },
    { id: "requirements-questions", label: "Questions" },
  ],
  // One section, so no anchor row: the domain model is four columns on one
  // screen and a pill that scrolls the reader to what is already in front of
  // them is noise. The row hides itself below two sections, and declaring the
  // block that is really rendered keeps the anchor and the markup honest.
  "domain-model": [{ id: "domain-columns", label: "Domain model" }],
  "architecture-graph": [
    { id: "graph-canvas", label: "Graph" },
    { id: "graph-detail", label: "Node detail" },
  ],
  "architecture-recommendation": [
    { id: "architecture-candidates", label: "Shapes" },
    { id: "architecture-style", label: "Code style" },
  ],
  "uml-diagrams": [
    { id: "uml-structure", label: "Structure" },
    { id: "uml-behaviour", label: "Behaviour" },
  ],
  // Coverage first, because that is the order the page renders them in. The
  // pills doubled as a position indicator, so listing them backwards lit Flows
  // while the reader was looking at Coverage.
  wireframes: [
    { id: "wireframes-coverage", label: "Coverage" },
    { id: "wireframes-flows", label: "Flows" },
  ],
  "sprint-plan": [
    { id: "sprint-summary", label: "Summary" },
    { id: "sprint-proposed", label: "Proposed" },
    { id: "sprint-backlog", label: "Backlog" },
  ],
  "design-review": [
    { id: "review-checks", label: "Checks" },
    { id: "review-artifacts", label: "Artifacts" },
    { id: "review-decision", label: "Decision" },
  ],
};

/** The stage after this one, or null at the end of the pipeline. */
export function nextStageId(id: DesignStageId): DesignStageId | null {
  return DESIGN_STAGE_IDS[stageIndex(id) + 1] ?? null;
}

/** The stage before this one, or null at the start. */
export function previousStageId(id: DesignStageId): DesignStageId | null {
  const index = stageIndex(id);
  return index > 0 ? DESIGN_STAGE_IDS[index - 1] : null;
}
