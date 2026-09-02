/**
 * The shape the activity view reads, which is now a real payload.
 *
 * These lived in the fixtures module, imported from there by the API that talks
 * to the orchestrator. That was the wrong way round: the contract a live
 * endpoint answers cannot be owned by the demo data, or deleting the demo data
 * takes the contract with it.
 *
 * `/activity` is a view over the audit log rather than a fifth phase, so an entry
 * is one recorded event: who did what, when, and to which artifact.
 */
/** The audit log's own categories, as the orchestrator files them. The page
 * said `test` and `deploy`, so every live testing and deployment event showed
 * its raw category and those two filters matched nothing. */
export type ActivityLogCategory =
  | "requirement"
  | "design"
  | "code"
  | "testing"
  | "security"
  | "deployment"
  | "approval"
  | "settings";

export type ActivityLogEntry = {
  id: string;
  /** ISO 8601 with its zone, shown in the reader's own zone by `formatWhen`. */
  timestamp: string;
  title: string;
  description: string;
  actor: string;
  category: ActivityLogCategory;
  /**
   * Optional, and absent on real entries. A number beside an event has to name
   * its source and window, and the audit log records what happened rather than
   * measuring it, so the server does not send one.
   */
  metric?: string;
  metricTone?: "success" | "neutral" | "warning" | "error";
  artifactRef?: string;
  /**
   * How the event went, from the server's reading of its action: the mark
   * came from the category, so a change request and a failed run drew the
   * green check. Absent on the demo's entries, which keep their category mark.
   */
  outcome?: "failed" | "changes" | "done" | "info";
};
