/**
 * The stage chrome both gated phases use: the sticky rail, the anchor pills,
 * the pending, generating and failed guards, and the trace chips.
 *
 * Parameterised by a `StageChrome`, so the words and the stage ids belong to
 * the phase and the behaviour belongs here. Copying it per phase would mean
 * two implementations of the one thing a reader uses to know where they are.
 */
export { stageToFollow } from "./follow";
export { computedBefore, computedBeforeIn } from "./computedBefore";
export { failedStagesConcern, failedStagesIn } from "./failed";
export { StageNav } from "./StageNav";
export { StageShell, OutdatedBanner } from "./StageShell";
export { StageSection, StageFooterNav } from "./StageSection";
export { TraceChips } from "./TraceChips";
export {
  isOutdated,
  nextStageIn,
  previousStageIn,
  stageIndexIn,
  stageLabelIn,
  type StageChrome,
  type StageChromeState,
  type StageMeta,
  type StageSectionMeta,
  type StageStatus,
} from "./types";
