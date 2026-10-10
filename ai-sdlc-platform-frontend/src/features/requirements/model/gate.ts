import { failedStagesConcern, failedStagesIn } from "@/shared/ui/stage";
import { reviewIsOpen } from "@/shared/ui/phase/reviewIsOpen";
import type { DesignSnapshot } from "../api/types";
import { DESIGN_CHROME } from "./chrome";

/**
 * Whether this phase is waiting on a decision, and so whether to offer one.
 *
 * Two facts, and both were wrong at once until a reader found the consequence
 * from the browser: a project whose design had been approved twice had nowhere
 * on the page to approve a third version.
 *
 * The decision has to be the one covering *this* version. The server reported
 * the newest decision whatever version it covered, so after any approval this
 * was never null again and the phase never asked a second time, while the run
 * sat at its gate for good.
 *
 * And the fact that a decision is wanted is the review stage, not the health
 * of every other stage. The runner marks the review stage complete on reaching
 * the gate. Requiring all eight stages complete meant one leaf stage the rule
 * catalogue kept refusing removed the only place a decision could be made,
 * which is not the reader overruling a machine, it is the reader being locked
 * out by one.
 */
export function designGateIsWaiting(snapshot: DesignSnapshot): boolean {
  return reviewIsOpen(
    snapshot.run,
    snapshot.requirementsVersion,
    () => snapshot.stages["design-review"].status === "complete" && !snapshot.gate.decision,
  );
}

/**
 * What failed or is still open in this design, which approving over needs a
 * note for: the server refuses the approval without one, by the same rule.
 *
 * Approving was one click whatever had failed, and eighteen live projects sat
 * at an open design review with a failed stage.
 */
export function designConcerns(snapshot: DesignSnapshot): string[] {
  const errors = snapshot.consistency.filter((finding) => finding.severity === "error").length;
  const unapplied = unappliedAnswers(snapshot);
  return [
    failedStagesConcern(failedStagesIn(DESIGN_CHROME, snapshot.stages)),
    errors > 0 ? `${errors} consistency ${errors === 1 ? "error" : "errors"} open` : null,
    unapplied > 0
      ? `${unapplied} ${unapplied === 1 ? "answer" : "answers"} given and not applied to the design`
      : null,
  ].filter((concern): concern is string => concern !== null);
}

/**
 * Why approving would leave Code Generation nothing to build from, or null.
 *
 * As the server refuses it (`_unbuildable`, `api/design.py`): a failed Sprint
 * Planning was approved with a note, and Code Generation then failed on "no
 * sprint plan at the design version this run pinned".
 */
export function approvalBlocker(snapshot: DesignSnapshot): string | null {
  // Not Wireframes: Code Generation builds without them, and approving over
  // them with a note ("drawn by hand this sprint") stays the reader's call.
  const missing = (["sprint-plan"] as const)
    .filter((id) => snapshot.stages[id]?.status === "failed")
    .map((id) => DESIGN_CHROME.meta[id].label);
  if (missing.length === 0) return null;
  const many = missing.length > 1;
  return `${missing.join(" and ")} failed, and Code Generation builds from ${many ? "them" : "it"}, so approving would leave nothing to build. Try ${many ? "those stages" : "that stage"} again first.`;
}

/**
 * Answers given and not yet applied to the design.
 *
 * Answering records an answer; only Apply the answers regenerates the design
 * with them, and the design that regenerates asks its own questions afresh. So
 * an answered question in this snapshot is an answer nothing downstream has
 * seen. An approval over them lost them while the bar read "every question
 * answered".
 */
export function unappliedAnswers(snapshot: DesignSnapshot): number {
  return snapshot.questions.filter((question) => Boolean(question.answer)).length;
}
