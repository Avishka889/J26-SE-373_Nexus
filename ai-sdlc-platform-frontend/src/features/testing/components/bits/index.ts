/**
 * Testing's chrome. The generic pieces moved to `shared/ui/phase` so other
 * phases can use them; they are re-exported here so this feature's imports did
 * not have to change. What stays below is specific to Testing.
 */
export { Panel, Hairline, Note, Chip, Metric, Bar, ActorMark } from "@/shared/ui/phase";
export { SeverityChip, FindingStatusChip, TriageChip, StateChip, ProofChip } from "./chips";
export { severityVar, severityLabel, findingStatusLabel } from "./chipLabels";
export { Console } from "@/shared/ui/console";
