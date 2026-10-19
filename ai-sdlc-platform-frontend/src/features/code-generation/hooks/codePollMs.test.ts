import { describe, expect, it } from "vitest";
import { DESIGN_SEEDS } from "@/entities/design-seed";
import { CODE_STAGE_IDS } from "@/types/project";
import type { CodeSnapshot } from "../api/types";
import { buildCodeSnapshot } from "../fixtures/buildCodeSnapshot";
import { codePollMs } from "./useCode";

type Run = NonNullable<CodeSnapshot["run"]>;

const RUN: Run = {
  id: "run-1",
  state: "running",
  version: 1,
  startedAt: "2026-10-17T18:21:10Z",
  finishedAt: null,
  error: null,
  stoppedAt: null,
  model: null,
  thinking: null,
};

/** Every stage finished but the review, which the run has not opened yet. */
function finishing(state: Run["state"] | null): CodeSnapshot {
  const base = buildCodeSnapshot("p1", DESIGN_SEEDS.p1, "awaiting", 1);
  const stages = Object.fromEntries(
    CODE_STAGE_IDS.map((id) => [
      id,
      { ...base.stages[id], status: id === "code-review" ? "pending" : "complete" },
    ]),
  ) as CodeSnapshot["stages"];
  return { ...base, stages, run: state ? { ...RUN, state } : null };
}

describe("how often the code is read", () => {
  // Once Build finished nothing was generating, so the review the run opened a
  // moment later waited for the next minute's read.
  it("keeps asking quickly while the run opens the review, with nothing generating", () => {
    expect(codePollMs(finishing("running"))).toBe(1200);
    expect(codePollMs(finishing("queued"))).toBe(1200);
  });

  it("drops to once a minute once the review is open", () => {
    expect(codePollMs(finishing("awaiting_gate"))).toBe(60_000);
    expect(codePollMs(finishing(null))).toBe(60_000);
  });

  it("asks quickly while a stage is generating, whatever the run says", () => {
    const snapshot = finishing(null);
    snapshot.stages.build = { ...snapshot.stages.build, status: "generating" };
    expect(codePollMs(snapshot)).toBe(1200);
  });
});
