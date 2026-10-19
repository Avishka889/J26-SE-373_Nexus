import { describe, expect, it } from "vitest";
import { claimsSummary } from "./claims";

describe("what a closed list of release note claims says", () => {
  it("counts them by kind, the kinds a rule rates highest first", () => {
    const kinds = ["fix", "breaking", "fix", "other", "deprecation", "fix"];
    expect(claimsSummary(kinds.map((kind) => ({ kind })))).toBe(
      "6 verified claims: 1 breaking, 1 deprecation, 3 fix, 1 other",
    );
  });

  it("reads right for one", () => {
    expect(claimsSummary([{ kind: "fix" }])).toBe("1 verified claim: 1 fix");
  });
});
