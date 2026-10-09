import type { ConsoleLine } from "./Console";

/**
 * What a step needs for the console to write it: the command, what came of it,
 * and the tail of what it printed.
 *
 * Structural rather than any one contract's type, because three phases hand the
 * console steps of three shapes that agree on these four fields: the code
 * phase's build steps, the testing phase's harness steps, and the deployment
 * phase's staging build. A phase whose steps carry other names maps them onto
 * this rather than growing its own copy.
 */
export type TranscriptStep = {
  name: string;
  command: string;
  /** `passed`, `failed`, `not-run` or `timed-out`; anything else is shown as it is. */
  outcome: string;
  logTail?: string | null;
};

const OUTCOME_WORDS: Record<string, string> = {
  passed: "passed",
  failed: "failed",
  "not-run": "did not run",
  "timed-out": "timed out",
};

/**
 * The real tails, in order, labelled by the step that produced them.
 *
 * Moved here when deployment became its third consumer: the code and testing
 * phases each kept a private copy, and a third would have been the one that
 * drifted. A step that never ran says so rather than looking clean, and only a
 * step that passed is marked as passing.
 */
export function transcriptOf(steps: readonly TranscriptStep[]): ConsoleLine[] {
  const lines: ConsoleLine[] = [];
  for (const step of steps) {
    lines.push({ kind: "cmd", text: step.command });
    if (step.outcome === "not-run") {
      lines.push({ kind: "muted", text: "not run: a step before this one failed" });
      continue;
    }
    for (const line of (step.logTail ?? "").split("\n").filter(Boolean)) {
      lines.push({ kind: "info", text: line });
    }
    lines.push({
      kind: step.outcome === "passed" ? "pass" : "fail",
      text: `${step.name} ${OUTCOME_WORDS[step.outcome] ?? step.outcome}`,
    });
  }
  return lines;
}
