import { describe, expect, it } from "vitest";
import { nexuspaySeed } from "@/entities/design-seed/projects/nexuspay";
import { DESIGN_STAGE_IDS } from "@/types/project";
import type { DesignSnapshot } from "../api/types";
import { buildSnapshot } from "../fixtures/designDb";
import { designPollMs } from "./useDesign";

type Run = NonNullable<DesignSnapshot["run"]>;

const RUN: Run = {
  id: "run-1",
  state: "running",
  version: 1,
  startedAt: "2026-10-17T18:18:48Z",
  finishedAt: null,
  error: null,
  stoppedAt: null,
  model: null,
  thinking: null,
};

/** Every stage finished but the review, which the run has not opened yet. */
function finishing(state: Run["state"] | null): DesignSnapshot {
  const base = buildSnapshot("p1", nexuspaySeed, "awaiting");
  const stages = Object.fromEntries(
    DESIGN_STAGE_IDS.map((id) => [
      id,
      { ...base.stages[id], status: id === "design-review" ? "pending" : "complete" },
    ]),
  ) as DesignSnapshot["stages"];
  return { ...base, stages, run: state ? { ...RUN, state } : null };
}

describe("how often the design is read", () => {
  // Seen on a live project: Sprint Planning finished, the read that saw it was
  // the last, and the review the run opened under two seconds later appeared
  // only when something else made the page read.
  it("keeps asking while the run opens the review, with nothing generating", () => {
    expect(designPollMs(finishing("running"))).toBe(1200);
    expect(designPollMs(finishing("queued"))).toBe(1200);
  });

  it("stops once the review is open, or the run has ended", () => {
    expect(designPollMs(finishing("awaiting_gate"))).toBe(false);
    expect(designPollMs(finishing("failed"))).toBe(false);
    expect(designPollMs(finishing(null))).toBe(false);
  });

  it("asks while a stage is generating, whatever the run says", () => {
    const snapshot = finishing(null);
    snapshot.stages["sprint-plan"] = { ...snapshot.stages["sprint-plan"], status: "generating" };
    expect(designPollMs(snapshot)).toBe(1200);
  });

  it("asks nothing before there is a first answer", () => {
    expect(designPollMs(undefined)).toBe(false);
  });
});
