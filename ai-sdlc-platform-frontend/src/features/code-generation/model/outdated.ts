import { CODE_STAGE_IDS, type CodeStageId } from "@/types/project";
import type { CodeSnapshot } from "../api/types";

/**
 * Two kinds of stale, on two different axes, and conflating them was the risk
 * this phase carries that the design phase does not.
 *
 * A stage is outdated when it was generated at an older *code* version than
 * the phase is at now: the scope changed and this stage has not caught up.
 *
 * The whole phase is outdated when the *design* has moved on since the code
 * was generated from it. That is not a stage level fact and no stage can carry
 * it, because every stage of that run is equally behind.
 *
 * Both are computed from versions the server reports. Storing either would let
 * a boolean disagree with the numbers it describes.
 */
export function isCodeStageOutdated(snapshot: CodeSnapshot, stageId: CodeStageId): boolean {
  const stage = snapshot.stages[stageId];
  if (stage.status !== "complete") return false;
  return stage.generatedFromVersion < snapshot.codeVersion;
}

export function outdatedCodeStageIds(snapshot: CodeSnapshot): CodeStageId[] {
  return CODE_STAGE_IDS.filter((id) => isCodeStageOutdated(snapshot, id));
}

export function generatingCodeStageIds(snapshot: CodeSnapshot): CodeStageId[] {
  return CODE_STAGE_IDS.filter((id) => snapshot.stages[id].status === "generating");
}

/** The design has moved on since this code was generated from it. */
export function designMovedOn(snapshot: CodeSnapshot): boolean {
  if (snapshot.codeVersion === 0) return false;
  return snapshot.generatedFromDesignVersion < snapshot.designVersion;
}

/**
 * What to do about a review the design has moved past, as the page says it.
 *
 * Requesting changes there would regenerate from the older design, and
 * approving would send that code on to Testing, so the server refuses both;
 * generating again closes the review and reads the newer one.
 */
export function reviewMovedPastLine(snapshot: CodeSnapshot): string {
  return `This review is of code generated from design version ${snapshot.generatedFromDesignVersion}, and design version ${snapshot.designVersion} has been approved since. Generate again to regenerate from it: that closes this review.`;
}
