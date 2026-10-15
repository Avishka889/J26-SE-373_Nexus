import { failedStagesConcern, failedStagesIn } from "@/shared/ui/stage";
import { reviewIsOpen } from "@/shared/ui/phase/reviewIsOpen";
import type { CodeSnapshot } from "../api/types";
import { CODE_CHROME } from "./stages";

/**
 * The design phase's rule on the code axis: see `requirements/model/gate.ts`
 * for why it is these two facts and not the health of every stage.
 */
export function codeGateIsWaiting(snapshot: CodeSnapshot): boolean {
  return reviewIsOpen(
    snapshot.run,
    snapshot.codeVersion,
    () => snapshot.stages["code-review"].status === "complete" && !snapshot.gate.decision,
  );
}

const STEP_WORDS: Record<string, string> = {
  passed: "passed",
  failed: "failed",
  "not-run": "did not run",
  "timed-out": "timed out",
};

/**
 * What failed or is still open in this code version, which approving over
 * needs a note for: the server refuses the approval without one, by the same
 * rule. A code version was approved with its typecheck failing, in one click.
 */
export function codeConcerns(snapshot: CodeSnapshot): string[] {
  const build = snapshot.repository?.build;
  const failedStep = build?.steps.find((step) => step.outcome !== "passed");
  const errors = (snapshot.agreement?.findings ?? []).filter(
    (finding) => finding.severity === "error",
  ).length;
  return [
    failedStagesConcern(failedStagesIn(CODE_CHROME, snapshot.stages)),
    !build
      ? "the build did not run"
      : failedStep
        ? `the build did not pass: ${failedStep.name} ${STEP_WORDS[failedStep.outcome]}`
        : null,
    errors > 0 ? `${errors} agreement ${errors === 1 ? "error" : "errors"} between the code and the contract` : null,
  ].filter((concern): concern is string => concern !== null);
}
