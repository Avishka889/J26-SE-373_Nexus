export type StepStatus = "complete" | "pending" | "generating" | "failed" | "future";

export type StepperStep = {
  id: string;
  label: string;
  badge?: unknown;
  /**
   * Explicit state for this step. Supplying it on any step switches the whole
   * stepper to explicit mode, because mixing a real state machine with
   * position guessing produces contradictions (a failed step that renders green
   * because it happens to sit left of the cursor).
   */
  status?: StepStatus;
};

/**
 * Two modes, deliberately.
 *
 * Legacy: status comes from position relative to `progressId`, and the sentinel
 * `"done"` means everything is complete. Testing, Deployment and Code Generation
 * rely on this, so it stays exactly as it was.
 *
 * Explicit: any step carrying `status` means the caller owns the state, and
 * position is ignored. A phase that knows its stages are generating or failed
 * says so rather than being inferred.
 */
export function deriveStepStatuses(
  steps: readonly StepperStep[],
  progressId?: string,
  currentId?: string,
): StepStatus[] {
  if (steps.some((s) => s.status)) {
    return steps.map((s) => s.status ?? "future");
  }

  const progress = progressId ?? currentId ?? steps[0]?.id ?? "";
  const currentIdx = steps.findIndex((s) => s.id === progress);
  const allComplete = progress === "done";

  return steps.map((_, index) => {
    if (allComplete) return "complete";
    if (currentIdx === -1) return "future";
    if (index < currentIdx) return "complete";
    if (index === currentIdx) return "pending";
    return "future";
  });
}

/** Only a step that has nothing to show yet is unreachable. */
export function isStepDisabled(status: StepStatus): boolean {
  return status === "future";
}
