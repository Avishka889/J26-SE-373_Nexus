import { describe, expect, it } from "vitest";
import { DESIGN_STAGE_IDS } from "@/types/project";
import { buildSnapshot } from "../fixtures/designDb";
import { nexuspaySeed } from "@/entities/design-seed/projects/nexuspay";
import type { DesignSnapshot } from "../api/types";
import { computeDesignProgress } from "./progress";
import { isStageOutdated, outdatedStageIds } from "./outdated";

/**
 * A generated design with nobody having decided yet.
 *
 * Spelled out rather than taken from a fixture project, since each project's
 * posture now follows its own status and these assertions are about the
 * undecided case specifically.
 */
const base = () => buildSnapshot("p1", nexuspaySeed, "awaiting");

describe("computeDesignProgress", () => {
  it("reads Ready for review when everything is generated but undecided", () => {
    const result = computeDesignProgress(base());
    expect(result.valueLabel).toBe("Ready for review");
    // The bar is full because generation really is complete; the label carries
    // the fact that nobody has decided yet.
    expect(result.percent).toBe(100);
  });

  it("only says Approved once a decision exists", () => {
    const snapshot: DesignSnapshot = {
      ...base(),
      gate: { decision: { kind: "approved", at: "x", by: "A. Chen", version: 1, note: null }, history: [] },
    };
    expect(computeDesignProgress(snapshot).valueLabel).toBe("Approved");
  });

  it("says Changes requested and drops below full when sent back", () => {
    const snapshot = base();
    snapshot.gate.decision = { kind: "changes", at: "x", by: "A. Chen", version: 1, note: "redo" };
    snapshot.stages.wireframes.status = "generating";
    const result = computeDesignProgress(snapshot);
    expect(result.valueLabel).toBe("Changes requested");
    expect(result.percent).toBeLessThan(100);
  });

  it("says Generating while stages are still generating", () => {
    const snapshot = base();
    snapshot.stages["sprint-plan"].status = "generating";
    // One word, matching the pill and the chevron spinner, rather than a third
    // way of saying the same thing.
    expect(computeDesignProgress(snapshot).valueLabel).toBe("Generating");
    expect(computeDesignProgress(snapshot).percent).toBeLessThan(100);
  });

  it("flags a failed stage rather than reporting a number", () => {
    const snapshot = base();
    snapshot.stages.wireframes.status = "failed";
    expect(computeDesignProgress(snapshot).valueLabel).toBe("Needs attention");
  });
});

describe("isStageOutdated", () => {
  it("is false when nothing has changed", () => {
    const snapshot = base();
    expect(outdatedStageIds(snapshot)).toEqual([]);
  });

  it("marks every completed stage behind the current version", () => {
    const snapshot = base();
    snapshot.requirementsVersion = 2;
    snapshot.stages.requirements.generatedFromVersion = 2;
    expect(isStageOutdated(snapshot, "requirements")).toBe(false);
    expect(isStageOutdated(snapshot, "wireframes")).toBe(true);
    expect(outdatedStageIds(snapshot)).toEqual(
      DESIGN_STAGE_IDS.filter((id) => id !== "requirements"),
    );
  });

  it("does not call a regenerating stage outdated, because it is already being fixed", () => {
    const snapshot = base();
    snapshot.requirementsVersion = 2;
    snapshot.stages.wireframes.status = "generating";
    expect(isStageOutdated(snapshot, "wireframes")).toBe(false);
  });
});
