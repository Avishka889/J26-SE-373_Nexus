import { describe, expect, it } from "vitest";
import { TEST_STAGE_IDS } from "@/types/project";
import type { TestSnapshot } from "../api/types";
import { buildTestSnapshot } from "../fixtures/buildTestSnapshot";
import { testingPollMs } from "./useTestingPage";

type Run = NonNullable<TestSnapshot["run"]>;

const RUN: Run = {
  id: "run-1",
  state: "running",
  version: 1,
  startedAt: "2026-10-17T18:30:00Z",
  finishedAt: null,
  error: null,
  stoppedAt: null,
  model: null,
  thinking: null,
};

/** Every stage finished but the review, which the run has not opened yet. */
function finishing(state: Run["state"] | null): TestSnapshot {
  const base = buildTestSnapshot("p1", "awaiting", 1);
  const stages = Object.fromEntries(
    TEST_STAGE_IDS.map((id) => [
      id,
      { ...base.stages[id], status: id === "test-review" ? "pending" : "complete" },
    ]),
  ) as TestSnapshot["stages"];
  return { ...base, stages, run: state ? { ...RUN, state } : null };
}

describe("how often the testing phase is read", () => {
  // Once Remediation finished nothing was generating, the read that saw it was
  // the last, and Test Review appeared only when something else made the page read.
  it("keeps asking while the run opens the review, with nothing generating", () => {
    expect(testingPollMs(finishing("running"))).toBe(1200);
    expect(testingPollMs(finishing("queued"))).toBe(1200);
  });

  it("stops once the review is open, or the run has ended", () => {
    expect(testingPollMs(finishing("awaiting_gate"))).toBe(false);
    expect(testingPollMs(finishing(null))).toBe(false);
  });

  it("asks while a stage is generating, whatever the run says", () => {
    const snapshot = finishing(null);
    snapshot.stages.remediation = { ...snapshot.stages.remediation, status: "generating" };
    expect(testingPollMs(snapshot)).toBe(1200);
  });
});
