/**
 * Chrome every SDLC phase page is built from. It lives in shared because a
 * feature may never import another feature, and Testing, Deployment and
 * Requirements all need the same panels, chips and gate.
 *
 * Anything here must be free of domain types: a phase-specific chip belongs to
 * its phase, built on `Chip`.
 */
export { Panel, Hairline } from "./Panel";
export { Note } from "./Note";
export { Chip, ActorMark, type ChipTone } from "./chips";
export { Metric, Bar } from "./metrics";
export { DecisionBar } from "./DecisionBar";
export { Expandable } from "./Expandable";
export { ReconnectingNotice } from "./ReconnectingNotice";
export { RunStoppedNotice } from "./RunStoppedNotice";
export { stoppedRun } from "./stoppedRun";
export { readState, type ReadState } from "./readState";
export { reviewIsOpen } from "./reviewIsOpen";
export { workingStage } from "./workingStage";
