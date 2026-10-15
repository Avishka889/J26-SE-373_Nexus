import { HttpError } from "@/lib/http";
import type { CodeSnapshot } from "../api/types";

/**
 * The code version a new one would replace, when the current one is approved.
 *
 * Generate again, a scope toggle and an arm choice each start a new version,
 * and over approved code that leaves Testing's and Deployment's work behind,
 * so the page asks first. Null when nothing approved would be replaced.
 */
export function approvedVersion(snapshot: CodeSnapshot): number | null {
  const decision = snapshot.gate.decision;
  // A version an accepted security fix wrote has no review of its own and
  // counts as approved through the version it patched.
  return (decision?.kind === "approved" && decision.version === snapshot.codeVersion) ||
    snapshot.approvedThrough
    ? snapshot.codeVersion
    : null;
}

/**
 * The approved version a refusal says would be replaced, which a confirmation
 * can answer; null for any other refusal. The server's backstop for a page
 * whose snapshot had not yet seen the approval.
 */
export function refusedForSupersede(error: unknown): number | null {
  if (!(error instanceof HttpError) || error.status !== 409) return null;
  const detail = (error.body as { detail?: { supersede?: unknown; approvedVersion?: unknown } } | undefined)
    ?.detail;
  return detail?.supersede === "required" && typeof detail.approvedVersion === "number"
    ? detail.approvedVersion
    : null;
}
