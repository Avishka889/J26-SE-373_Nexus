import { describe, expect, it } from "vitest";
import { testChromeFor } from "./stages";

/** The live page kept a "Detectors" pill for a table only the demo renders. */
describe("the security scan's section pills", () => {
  const ids = (hasComparison: boolean) =>
    testChromeFor(hasComparison).sections["security-scan"].map((section) => section.id);

  it("leave out Detectors when no comparison is shown", () => {
    expect(ids(false)).toEqual(["security-counts", "security-findings"]);
  });

  it("keep it when the comparison is on the page", () => {
    expect(ids(true)).toContain("security-detectors");
  });
});
