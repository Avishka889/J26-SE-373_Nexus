import { describe, expect, it } from "vitest";
import { stoppedRun } from "./stoppedRun";

const failed = { id: "r1", state: "failed", error: "it broke", startedAt: "2026-10-03 09:12" };

/**
 * One rule for every phase: the newest full run failed, and nothing is
 * running now. A new run starting is the way on, not another stopped run.
 */
describe("a stopped run", () => {
  it("is the newest full run when it failed", () => {
    expect(stoppedRun(failed, false)).toEqual(failed);
  });

  it("is not one while something is generating again", () => {
    expect(stoppedRun(failed, true)).toBeNull();
  });

  it("is not a run that finished, or no run at all", () => {
    expect(stoppedRun({ ...failed, state: "done", error: null }, false)).toBeNull();
    expect(stoppedRun(null, false)).toBeNull();
  });
});
