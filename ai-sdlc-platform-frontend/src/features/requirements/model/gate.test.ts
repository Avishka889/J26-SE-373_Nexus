import { describe, expect, it } from "vitest";
import { DESIGN_STAGE_IDS } from "@/types/project";
import { approvalBlocker, designConcerns, designGateIsWaiting } from "./gate";
import type { DesignSnapshot, StageState, GateDecision } from "../api/types";

/**
 * Found from the browser, not from here: a project whose design had been
 * approved twice had nowhere on the page to approve a third version. Two
 * independent causes, one test each.
 */
function snapshot(
  overrides: Partial<Record<string, StageState["status"]>>,
  decision: GateDecision | null,
): DesignSnapshot {
  const stages = Object.fromEntries(
    DESIGN_STAGE_IDS.map((id) => [
      id,
      {
        id,
        status: overrides[id] ?? "complete",
        generatedFromVersion: 3,
        generatedAt: null,
        summary: null,
        error: null,
      },
    ]),
  );
  // The contract always carries the questions, answered or not.
  return { stages, gate: { decision, history: [] }, questions: [] } as unknown as DesignSnapshot;
}

const APPROVED: GateDecision = {
  kind: "approved",
  at: "2026-08-21T00:00:00Z",
  by: "you",
  version: 3,
  note: null,
};

describe("whether the design phase is waiting on a decision", () => {
  it("is waiting when the run reached the gate and this version is undecided", () => {
    expect(designGateIsWaiting(snapshot({}, null))).toBe(true);
  });

  it("is still waiting when a leaf stage failed", () => {
    /**
     * The wireframes catalogue refusing a flow must not remove the only place
     * a decision can be made. Approving over a known problem is the reader's
     * call; being unable to decide at all is not theirs to make.
     */
    expect(designGateIsWaiting(snapshot({ wireframes: "failed" }, null))).toBe(true);
  });

  it("is not waiting once this version has been decided", () => {
    expect(designGateIsWaiting(snapshot({}, APPROVED))).toBe(false);
  });

  it("is not waiting while the run has not reached the gate", () => {
    expect(
      designGateIsWaiting(snapshot({ "design-review": "pending", wireframes: "generating" }, null)),
    ).toBe(false);
  });
});

/**
 * Approving was one click whatever had failed: eighteen live projects sat at
 * an open design review with a failed stage. What failed is now said first,
 * and approving over it needs a note.
 */
describe("what a design approval has to answer for", () => {
  const withFindings = (
    stages: Partial<Record<string, StageState["status"]>>,
    severities: ("error" | "warning")[],
  ) => ({
    ...snapshot(stages, null),
    consistency: severities.map((severity) => ({ severity })),
  }) as unknown as DesignSnapshot;

  it("names each failed stage and counts the consistency errors", () => {
    expect(designConcerns(withFindings({ "domain-model": "failed", "uml-diagrams": "failed" }, ["error", "warning"]))).toEqual([
      "2 stages failed: Domain Model, UML Diagrams",
      "1 consistency error open",
    ]);
  });

  it("is nothing for a design where everything completed and agrees", () => {
    expect(designConcerns(withFindings({}, ["warning"]))).toEqual([]);
  });

  // Answering records an answer; only applying it reaches the design. An
  // approval over answers never applied lost them.
  it("counts the answers given and not applied to the design", () => {
    const answered = {
      ...withFindings({}, []),
      questions: [
        { id: "Q-1", answer: "Only me." },
        { id: "Q-2", answer: null },
      ],
    } as unknown as DesignSnapshot;

    expect(designConcerns(answered)).toEqual(["1 answer given and not applied to the design"]);
  });
});

/**
 * A failed Sprint Planning was approved with a note, and Code Generation then
 * failed on "no sprint plan at the design version this run pinned".
 */
describe("what Code Generation needs before a design is approved", () => {
  it("holds the approval while Sprint Planning or Wireframes failed, and says why", () => {
    expect(approvalBlocker(snapshot({ "sprint-plan": "failed" }, null))).toBe(
      "Sprint Planning failed, and Code Generation builds from it, so approving would leave nothing to build. Try that stage again first.",
    );
  });

  it("does not hold it over a failed stage Code Generation does not read", () => {
    expect(approvalBlocker(snapshot({ "uml-diagrams": "failed" }, null))).toBeNull();
  });
});

/**
 * After "Request changes" the decision bar came back at once while every stage
 * regenerated, and Approve was refused: the review stage still read complete
 * and the new version had no decision yet. The run says whether it waits.
 */
describe("whether the design review is open, when the server's run is known", () => {
  const atVersion = (state: string, runVersion: number) =>
    ({
      ...snapshot({}, null),
      requirementsVersion: 4,
      run: { id: "r1", state, version: runVersion },
    }) as unknown as DesignSnapshot;

  it("is closed while the requested changes regenerate", () => {
    expect(designGateIsWaiting(atVersion("running", 4))).toBe(false);
  });

  it("is open once the run waits at the review for this version", () => {
    expect(designGateIsWaiting(atVersion("awaiting_gate", 4))).toBe(true);
    expect(designGateIsWaiting(atVersion("awaiting_gate", 3))).toBe(false);
  });
});
