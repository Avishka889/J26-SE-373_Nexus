import { describe, expect, it } from "vitest";
import { deriveStepStatuses, isStepDisabled, type StepperStep } from "./chevronStatus";

const steps: StepperStep[] = [
  { id: "a", label: "A" },
  { id: "b", label: "B" },
  { id: "c", label: "C" },
];

describe("deriveStepStatuses, legacy position mode", () => {
  // This block is the regression net for Testing, Deployment and Code
  // Generation, which all rely on position derivation. It must not change.
  it("marks everything before the cursor complete, the cursor pending, the rest future", () => {
    expect(deriveStepStatuses(steps, "b")).toEqual(["complete", "pending", "future"]);
  });

  it('treats the "done" sentinel as everything complete', () => {
    expect(deriveStepStatuses(steps, "done")).toEqual(["complete", "complete", "complete"]);
  });

  it("marks every step future when the cursor is not in the list", () => {
    expect(deriveStepStatuses(steps, "nope")).toEqual(["future", "future", "future"]);
  });

  it("falls back to currentId, then to the first step", () => {
    expect(deriveStepStatuses(steps, undefined, "c")).toEqual(["complete", "complete", "pending"]);
    expect(deriveStepStatuses(steps)).toEqual(["pending", "future", "future"]);
  });
});

describe("deriveStepStatuses, explicit mode", () => {
  it("uses the supplied statuses and ignores position", () => {
    const explicit: StepperStep[] = [
      { id: "a", label: "A", status: "complete" },
      { id: "b", label: "B", status: "failed" },
      { id: "c", label: "C", status: "generating" },
    ];
    expect(deriveStepStatuses(explicit, "a")).toEqual(["complete", "failed", "generating"]);
  });

  it("defaults a step with no status to future once any step is explicit", () => {
    const partial: StepperStep[] = [
      { id: "a", label: "A", status: "complete" },
      { id: "b", label: "B" },
    ];
    expect(deriveStepStatuses(partial, "done")).toEqual(["complete", "future"]);
  });
});

describe("isStepDisabled", () => {
  it("only blocks steps that have nothing to show", () => {
    expect(isStepDisabled("future")).toBe(true);
    // A running stage is worth watching and a failed one holds the retry.
    expect(isStepDisabled("generating")).toBe(false);
    expect(isStepDisabled("failed")).toBe(false);
    expect(isStepDisabled("complete")).toBe(false);
    expect(isStepDisabled("pending")).toBe(false);
  });
});
