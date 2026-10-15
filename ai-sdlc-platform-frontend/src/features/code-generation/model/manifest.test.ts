import { describe, expect, it } from "vitest";
import type { ManifestRow } from "../api/types";
import { fileTags } from "./manifest";

const page: ManifestRow = {
  path: "apps/web/src/pages/ListPage.tsx",
  stage: "frontend-code",
  generator: "model",
  arm: "rule",
  implements: [],
  summary: "",
  writtenFrom: "abc",
  reusedFromVersion: 0,
  carriedFixes: [],
};

/**
 * A page kept from an earlier generation says so, so a reviewer knows it has
 * not changed since they read it.
 */
describe("a file's tags", () => {
  it("say who wrote it and from which arm", () => {
    expect(fileTags(page)).toEqual(["model", "Rule-based"]);
  });

  it("say a page was kept unchanged, and since which version", () => {
    expect(fileTags({ ...page, reusedFromVersion: 3 })).toContain("unchanged since v3");
  });

  it("name each security fix carried into the file by the version it was applied as", () => {
    expect(fileTags({ ...page, carriedFixes: [2, 5] })).toEqual([
      "model",
      "Rule-based",
      "security fix from v2",
      "security fix from v5",
    ]);
  });
});
