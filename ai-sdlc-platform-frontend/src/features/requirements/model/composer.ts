import type { DesignSnapshot } from "../api/types";
import { designGateIsWaiting } from "./gate";

/**
 * What the chat does with a message: request changes at a pending review, or
 * add a change note.
 *
 * A note sent while a review waits only queues until the review is decided,
 * and the page used to say it was regenerating; at a review, what a reader who
 * writes a change means is "request changes", so that is what is sent.
 */
export function composerSends(snapshot: DesignSnapshot): "request-changes" | "change-note" {
  return designGateIsWaiting(snapshot) ? "request-changes" : "change-note";
}

/** The line under the chat, saying what sending does. */
export function composerHelper(snapshot: DesignSnapshot): string {
  const version = snapshot.requirementsVersion;
  // Paused on its questions, a note waits for the reader to continue, and goes
  // into the analysis with the answers rather than regenerating anything now.
  if (snapshot.questionsPending) {
    return `Version ${version} waits on its questions. A note sent now is read with your answers when you continue with them.`;
  }
  return composerSends(snapshot) === "request-changes"
    ? `Version ${version} waits on your review. Sending requests changes at it, and the design regenerates.`
    : `Version ${version}. Sending regenerates the design, Requirements Analysis included.`;
}

/**
 * The changes waiting on the review, as the decision bar says them, or null.
 *
 * They came another way (a note sent while a run was going, feedback sent from
 * production), and they apply when the review is decided: approving starts a
 * new version with them, which the reader should know before approving.
 */
export function queuedLine(snapshot: DesignSnapshot): string | null {
  const count = snapshot.queuedChanges.length;
  if (count === 0) return null;
  return `${count} ${count === 1 ? "change waits" : "changes wait"} on this decision: approving starts version ${
    snapshot.requirementsVersion + 1
  } with ${count === 1 ? "it" : "them"}`;
}
