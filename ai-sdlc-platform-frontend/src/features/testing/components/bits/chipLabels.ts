import type { FindingStatus, Severity } from "../../fixtures/types";

/**
 * The lookup maps the chips render from.
 *
 * Separated from `chips.tsx` so that file exports components only: a module
 * mixing the two cannot hot reload, and every chip in it loses state on any
 * edit here. Callers that want both import from `../bits`.
 */

export const severityVar: Record<Severity, string> = {
  critical: "var(--tp-crit)",
  high: "var(--tp-high)",
  medium: "var(--tp-med)",
  low: "var(--tp-low)",
  none: "var(--tp-low)",
};

export const severityLabel: Record<Severity, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
  // CVSS 0: the contract allows it, and a page with four severities crashed on it.
  none: "None",
};

export const findingStatusLabel: Record<FindingStatus, string> = {
  open: "Open",
  "fix-proposed": "Fix proposed",
  "fix-applied": "Fix applied",
  "re-verifying": "Re-verifying",
  verified: "Fixed and re-verified",
  dismissed: "Dismissed",
};
