import type { StageChrome } from "@/shared/ui/stage";
import { DESIGN_STAGE_IDS, type DesignStageId } from "@/types/project";
import { STAGE_META, STAGE_SECTIONS } from "./stages";

/**
 * This phase's binding of the shared stage chrome.
 *
 * The chrome (the sticky rail, the anchor pills, the pending and failed
 * guards) is shared with Code Generation; the words, the ids and the version
 * axis are what make it this phase's. Everything here already existed: this
 * only names it in the shape the shared components read.
 */
export const DESIGN_CHROME: StageChrome<DesignStageId> = {
  ids: DESIGN_STAGE_IDS,
  meta: STAGE_META,
  sections: STAGE_SECTIONS,
  versionNoun: "requirements version",
  // From the C1 nodes: the graph reads the requirements, the domain model is a
  // view over the graph, and the rest read the requirements and the graph.
  reads: {
    "architecture-graph": ["requirements"],
    "domain-model": ["architecture-graph"],
    "architecture-recommendation": ["requirements", "architecture-graph"],
    "uml-diagrams": ["architecture-graph"],
    wireframes: ["requirements", "architecture-graph"],
    "sprint-plan": ["requirements", "architecture-graph"],
  },
};
