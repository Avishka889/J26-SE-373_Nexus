import { describe, expect, it } from "vitest";
import {
  DECISION_CHAIN,
  SEVERITY_ORDER,
  coverageTrendCaption,
} from "./process";

/** What a live Testing page says about its own process, in its own words, not the demo's. */
describe("the Testing page's own words", () => {
  it("says what an applied fix does here, not what the demo's story did", () => {
    const said = DECISION_CHAIN.map(
      (step) => `${step.label}: ${step.detail}`,
    ).join(" ");
    expect(said).toContain("new code version");
    expect(said).toContain("reviewed before Deployment starts");
    expect(said).not.toMatch(/branch|run again on the new build/);
  });

  it("orders severities most serious first", () => {
    expect(SEVERITY_ORDER).toEqual(["critical", "high", "medium", "low"]);
  });

  it("captions the coverage trend from its points, with no sprint in it", () => {
    expect(coverageTrendCaption(0)).toBe("Nothing measured yet");
    expect(coverageTrendCaption(1)).toBe("One run measured so far");
    expect(coverageTrendCaption(3)).toBe("Across 3 runs");
  });
});
