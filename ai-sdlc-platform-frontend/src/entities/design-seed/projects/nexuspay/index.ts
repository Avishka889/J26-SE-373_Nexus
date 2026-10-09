import type { ProjectDesignSeed } from "../../projectSeed";
import { seedAssumptions, seedQuestions, seedRequirements } from "./requirements";
import { seedGraph } from "./graph";
import { seedArchitecture } from "./architecture";
import { seedDiagrams, seedUseCases } from "./uml";
import { seedWireframes } from "./wireframes";
import { seedSprint } from "./sprint";

/**
 * NexusPay Banking: payments, identity verification and an audit trail.
 *
 * The original content, and the fullest of the four. It stays as it was because
 * it genuinely fits the project it belongs to: the problem was never this
 * content, it was every other project being served it too.
 */
export const nexuspaySeed: ProjectDesignSeed = {
  appName: "Payments",
  requirements: seedRequirements,
  assumptions: seedAssumptions,
  questions: [
    {
      ...seedQuestions[0],
      presetAnswer: "Hold it for manual review. Refusing outright loses good customers.",
    },
    { ...seedQuestions[1], presetAnswer: "Seven years, to match the existing retention policy." },
  ],
  nodes: seedGraph.nodes,
  edges: seedGraph.edges,
  architecture: seedArchitecture,
  useCases: seedUseCases,
  diagrams: seedDiagrams,
  flows: seedWireframes,
  sprint: seedSprint,
};
