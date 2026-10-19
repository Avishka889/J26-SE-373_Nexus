import { describe, expect, it } from "vitest";
import { runIsWorking, stageOpeningNext } from "./runProgress";

const ORDER = ["first", "second", "review"] as const;

describe("runIsWorking", () => {
  it("is true while the run is queued or running, and only then", () => {
    expect(runIsWorking({ state: "queued" })).toBe(true);
    expect(runIsWorking({ state: "running" })).toBe(true);
    for (const state of ["awaiting_gate", "done", "failed", "superseded"]) {
      expect(runIsWorking({ state })).toBe(false);
    }
    expect(runIsWorking(null)).toBe(false);
    expect(runIsWorking(undefined)).toBe(false);
  });
});

describe("stageOpeningNext", () => {
  it("names the review while the run opens it: every stage finished, the review not yet open", () => {
    const stages = {
      first: { status: "complete" },
      second: { status: "complete" },
      review: { status: "pending" },
    };
    expect(stageOpeningNext(ORDER, stages, { state: "running" })).toBe("review");
  });

  it("names nothing while a stage is generating, since that stage is the one at work", () => {
    const stages = {
      first: { status: "complete" },
      second: { status: "generating" },
      review: { status: "pending" },
    };
    expect(stageOpeningNext(ORDER, stages, { state: "running" })).toBeNull();
  });

  it("names nothing once the run waits at its gate or has ended", () => {
    const stages = {
      first: { status: "complete" },
      second: { status: "complete" },
      review: { status: "pending" },
    };
    expect(stageOpeningNext(ORDER, stages, { state: "awaiting_gate" })).toBeNull();
    expect(stageOpeningNext(ORDER, stages, { state: "failed" })).toBeNull();
    expect(stageOpeningNext(ORDER, stages, null)).toBeNull();
  });

  it("names the first stage of a queued run that has not marked any yet", () => {
    const stages = {
      first: { status: "pending" },
      second: { status: "pending" },
      review: { status: "pending" },
    };
    expect(stageOpeningNext(ORDER, stages, { state: "queued" })).toBe("first");
  });
});
