import { describe, expect, it } from "vitest";
import { buildTestSnapshot } from "../fixtures/buildTestSnapshot";
import type { TestSnapshot } from "../api/types";
import { attentionShortcut, progressLabel, railSteps } from "./rail";
import { buildView, stepOrder } from "./view";

/**
 * The stage rail said every stage was done while three of them needed a
 * person: a stage is "complete" once it has run, whatever it found. The page
 * already worked out which stages have something outstanding, and how many;
 * the rail drew none of it, and the header's "43%" was the only trace.
 */
function firstRun(failing: number): TestSnapshot {
  const snapshot = buildTestSnapshot("p1", "awaiting", 1);
  const cases = Array.from({ length: 4 }, (_, i) => ({
    id: `c${i}`,
    name: `A record is kept US-1 AC-1-${i + 1}: given a, when b, then c`,
    outcome: i < failing ? "failed" : "passed",
    message: i < failing ? "expected 5, received 6" : "",
    traces: { storyId: "US-1", criterionId: `AC-1-${i + 1}`, requirementIds: ["R-1"] },
  }));
  return {
    ...snapshot,
    target: "generated",
    heal: null,
    healDecisions: [],
    validation: snapshot.validation && { ...snapshot.validation, findings: [], openFindings: 0 },
    remediation: snapshot.remediation && { ...snapshot.remediation, proposals: [] },
    tests: snapshot.tests && {
      ...snapshot.tests,
      target: "the generated app at code version 1",
      // The report's own totals, which the page reads beside its cases.
      total: 4,
      passed: 4 - failing,
      failed: failing,
      skipped: 0,
      suites: [{ path: "apps/api/src/__tests__/us-1.criteria.test.ts", framework: "vitest", cases }],
    },
  } as TestSnapshot;
}

const rail = (snapshot: TestSnapshot) =>
  railSteps(stepOrder, snapshot.stages, buildView({ data: snapshot, reviewer: "you" }));

const step = (snapshot: TestSnapshot, id: string) => rail(snapshot).find((one) => one.id === id)!;

describe("the stage rail", () => {
  it("counts the failing tests on Test Run, which did run", () => {
    const run = step(firstRun(3), "test-run");

    expect(run.status).toBe("complete");
    expect(run.badge).toBe(3);
    expect(run.badgeLabel).toBe("3 failing");
  });

  it("says Self Healing waits on a person, and for how many failures", () => {
    const healing = step(firstRun(3), "self-healing");

    expect(healing.status).toBe("pending");
    expect(healing.badge).toBe(3);
    expect(healing.badgeLabel).toBe("3 need a person");
  });

  it("marks nothing on a run with nothing outstanding", () => {
    const steps = rail(firstRun(0));

    expect(steps.filter((one) => one.badge !== undefined)).toEqual([]);
    expect(steps.every((one) => one.status === "complete")).toBe(true);
  });

  it("leaves a stage that is generating, failed or not reached as the server says", () => {
    const snapshot = firstRun(3);
    const stages = {
      ...snapshot.stages,
      "self-healing": { ...snapshot.stages["self-healing"], status: "generating" },
      "security-scan": { ...snapshot.stages["security-scan"], status: "failed" },
      remediation: { ...snapshot.stages.remediation, status: "pending" },
    } as TestSnapshot["stages"];
    const steps = railSteps(stepOrder, stages, buildView({ data: { ...snapshot, stages }, reviewer: "you" }));
    const status = (id: string) => steps.find((one) => one.id === id)!.status;

    expect(status("self-healing")).toBe("generating");
    expect(status("security-scan")).toBe("failed");
    expect(status("remediation")).toBe("future");
  });
});

describe("a stage that failed while something waits there", () => {
  // The stage failed, and its failures are still listed from the run: it
  // reads as failed, which is what happened to it, not as waiting on a person.
  it("reads as failed, not as waiting", () => {
    const snapshot = firstRun(3);
    const stages = {
      ...snapshot.stages,
      "self-healing": { ...snapshot.stages["self-healing"], status: "failed", error: "it broke" },
    } as TestSnapshot["stages"];
    const view = buildView({ data: { ...snapshot, stages }, reviewer: "you" });
    const healing = railSteps(stepOrder, stages, view).find((one) => one.id === "self-healing")!;

    expect(view.steps["self-healing"].state).toBe("attention");
    expect(healing.status).toBe("failed");
    expect(healing.badge).toBeUndefined();
  });
});

describe("the way to what needs a person", () => {
  it("leads to Self Healing while failures wait there", () => {
    const view = buildView({ data: firstRun(3), reviewer: "you" });

    expect(attentionShortcut(view)).toEqual({
      id: "self-healing",
      label: "3 in Self Healing",
      title: "Go to Self Healing: 3 need a person",
    });
  });

  it("is nothing when no stage waits on a person", () => {
    expect(attentionShortcut(buildView({ data: firstRun(0), reviewer: "you" }))).toBeNull();
  });
});

describe("the phase's progress, in a word", () => {
  it("says the run needs attention while a stage waits on a person", () => {
    expect(progressLabel(buildView({ data: firstRun(3), reviewer: "you" }))).toBe("Needs attention");
  });

  it("says it is ready for review when nothing is outstanding", () => {
    expect(progressLabel(buildView({ data: firstRun(0), reviewer: "you" }))).toBe("Ready for review");
  });

  it("says nothing of its own before a run", () => {
    expect(progressLabel(buildView({ data: buildTestSnapshot("p1", "not-started", 1), reviewer: "you" }))).toBeUndefined();
  });
});
