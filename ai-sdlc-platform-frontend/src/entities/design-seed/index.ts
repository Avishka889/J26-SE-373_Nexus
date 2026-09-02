/**
 * The four demo projects' design content, as data.
 *
 * It lived in the Requirements feature until Code Generation needed it: the
 * code phase's fixtures derive their contract from the same nodes, edges,
 * screens and stories, so every traceability chip in the demo resolves to
 * something that exists rather than to a plausible looking string.
 *
 * A feature may not import another feature, and rightly: two features reading
 * one blob of demo data is exactly the coupling that rule exists to stop. Data
 * both of them read belongs here, where entities live, and where the guardrail
 * is that it stays data with no JSX in it.
 */
export { BLANK_SEED, DESIGN_SEEDS, postureFor } from "./projects";
export type { DesignPosture, ProjectDesignSeed, SeedQuestion } from "./projectSeed";
