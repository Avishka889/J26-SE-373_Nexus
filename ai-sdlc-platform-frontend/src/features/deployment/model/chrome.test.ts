import { describe, expect, it } from "vitest";
import { computedBeforeIn } from "@/shared/ui/stage";
import { buildDeploySnapshot } from "../fixtures/buildDeploySnapshot";
import { DEPLOY_CHROME } from "./stages";

/**
 * The review's case: a changelog retried while the review waited left the risk
 * levels computed from the abstained vote it replaced, and nothing said so.
 */
describe("a changelog generated again under a waiting review", () => {
  it("marks the risk assessment and the impact analysis as computed before it", () => {
    const snapshot = buildDeploySnapshot("p4", "deploy");
    const stages = {
      ...snapshot.stages,
      "changelog-analysis": { ...snapshot.stages["changelog-analysis"], generatedAt: "2099-01-01 00:00" },
    };

    expect(computedBeforeIn(DEPLOY_CHROME, "risk-assessment", stages)).toEqual(["Changelog Analysis"]);
    expect(computedBeforeIn(DEPLOY_CHROME, "impact-analysis", stages)).toEqual(["Changelog Analysis"]);
    expect(computedBeforeIn(DEPLOY_CHROME, "dependency-updates", stages)).toEqual([]);
  });
});
