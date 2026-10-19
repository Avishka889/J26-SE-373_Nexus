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
    contractConcern(snapshot.contract),
  ].filter((concern): concern is string => concern !== null);
}

/**
 * The errors in the API contract the code was built from, in the server's words
 * (`contract_concern` in `api/code.py`), which refuses the approval without a
 * note by the same rule.
 *
 * The clinic project was approved over a contract with no way to create a
 * doctor or a patient: the rule arm's own check had said so, the model's arm had
 * thirteen endpoints and no error, and the review asked about neither. Which
 * contract to build from stays a person's choice at the API Contract stage; a
 * merged contract is judged by neither arm's count.
 */
function contractConcern(artefact: CodeSnapshot["contract"]): string | null {
  if (!artefact || artefact.chosen === "merged") return null;
  const ruleErrors = (artefact.ruleFindings ?? []).filter((finding) => finding.severity === "error");
  const comparison = artefact.comparison;
  const rule = artefact.chosen === "rule";
  const count = rule ? ruleErrors.length : (comparison?.llm.errors ?? 0);
  if (count === 0) return null;
  // The other arm's count is known only when the model answered and the two were compared.
  const other = rule ? (artefact.llmArm && comparison ? comparison.llm.errors : null) : ruleErrors.length;
  const first = rule ? ruleErrors[0]?.reason : undefined;
  return [
    `${count} ${count === 1 ? "error" : "errors"} in the API contract it was built from`,
    first ? ` (${first})` : "",
    other === 0 ? `; ${rule ? "the AI model's" : "the rule-based"} contract has none` : "",
  ].join("");
}
