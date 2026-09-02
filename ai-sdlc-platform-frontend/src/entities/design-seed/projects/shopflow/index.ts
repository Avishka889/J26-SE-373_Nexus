import type { ProjectDesignSeed } from "../../projectSeed";
import { seedAssumptions, seedQuestions, seedRequirements } from "./requirements";
import { seedGraph } from "./graph";
import { seedArchitecture } from "./architecture";
import { seedDiagrams, seedUseCases } from "./uml";
import { seedWireframes } from "./wireframes";
import { seedSprint } from "./sprint";

/**
 * ShopFlow Commerce: catalog, cart, checkout and orders across multi-tenant
 * storefronts.
 *
 * The second full snapshot, and the one that proves the phase is reading each
 * brief rather than replaying one. Its architecture comparison lands on
 * microservices where NexusPay's lands on a modular monolith, out of the scores
 * its own graph produces.
 */
export const shopflowSeed: ProjectDesignSeed = {
  appName: "Storefront",
  requirements: seedRequirements,
  assumptions: seedAssumptions,
  questions: seedQuestions,
  nodes: seedGraph.nodes,
  edges: seedGraph.edges,
  architecture: seedArchitecture,
  useCases: seedUseCases,
  diagrams: seedDiagrams,
  flows: seedWireframes,
  sprint: seedSprint,
};
