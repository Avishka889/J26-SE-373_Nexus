import { describe, expect, it } from "vitest";
import { computedBefore } from "./computedBefore";

type Id = "changelog" | "impact" | "risk";
const reads = { risk: ["changelog", "impact"], impact: ["changelog"] } as const;

/**
 * A stage retried alone regenerates that stage and nothing after it: a
 * changelog retried while the review waited left the risk levels computed from
 * the vote it replaced, and nothing said so.
 */
describe("a stage computed before what it reads was generated again", () => {
  it("names what changed under it", () => {
    const stages = {
      changelog: { status: "complete", generatedAt: "2026-10-03 10:05" },
      impact: { status: "complete", generatedAt: "2026-10-03 09:01" },
      risk: { status: "complete", generatedAt: "2026-10-03 09:02" },
    };

    expect(computedBefore<Id>(reads, "risk", stages)).toEqual(["changelog"]);
    expect(computedBefore<Id>(reads, "impact", stages)).toEqual(["changelog"]);
  });

  it("is nothing for a stage computed after what it reads", () => {
    const stages = {
      changelog: { status: "complete", generatedAt: "2026-10-03 09:00" },
      impact: { status: "complete", generatedAt: "2026-10-03 09:01" },
      risk: { status: "complete", generatedAt: "2026-10-03 09:02" },
    };

    expect(computedBefore<Id>(reads, "risk", stages)).toEqual([]);
  });

  it("compares moments, whatever shape each time was stored in", () => {
    // As text, "2026-10-03 09:30" sorts before "2026-10-03T09:02:00Z".
    const stages = {
      changelog: { status: "complete", generatedAt: "2026-10-03 09:30" },
      impact: { status: "complete", generatedAt: "2026-10-03T09:01:00Z" },
      risk: { status: "complete", generatedAt: "2026-10-03T09:02:00Z" },
    };

    expect(computedBefore<Id>(reads, "risk", stages)).toEqual(["changelog"]);
  });

  it("is nothing while either side is not complete", () => {
    const stages = {
      changelog: { status: "generating", generatedAt: "2026-10-03 10:05" },
      impact: { status: "complete", generatedAt: "2026-10-03 09:01" },
      risk: { status: "failed", generatedAt: null },
    };

    expect(computedBefore<Id>(reads, "risk", stages)).toEqual([]);
    expect(computedBefore<Id>(reads, "impact", stages)).toEqual([]);
  });
});
