import { DESIGN_STAGE_IDS, type DesignStageId } from "@/types/project";
import type { DesignSnapshot } from "../api/types";

/**
 * Outdated is computed, never stored.
 *
 * A stage records the requirements version it was generated from. If the
 * requirements have moved on since, the stage is behind, and that comparison is
 * the single source of the answer. Storing a boolean would let it disagree with
 * the versions it is supposed to describe.
 *
 * Which stages a wording change really affects would need a dependency graph
 * the service does not have, so the honest rule is that everything downstream of
 * Requirements Analysis is outdated. No claim is made that cannot be reproduced.
 */
export function isStageOutdated(snapshot: DesignSnapshot, stageId: DesignStageId): boolean {
  const stage = snapshot.stages[stageId];
  if (stage.status !== "complete") return false;
  return stage.generatedFromVersion < snapshot.requirementsVersion;
}

export function outdatedStageIds(snapshot: DesignSnapshot): DesignStageId[] {
  return DESIGN_STAGE_IDS.filter((id) => isStageOutdated(snapshot, id));
}

export function regeneratingStageIds(snapshot: DesignSnapshot): DesignStageId[] {
  return DESIGN_STAGE_IDS.filter((id) => snapshot.stages[id].status === "generating");
}
