import { describe, expect, it } from "vitest";
import { buildTestSnapshot } from "../fixtures/buildTestSnapshot";
import type { TestSnapshot } from "../api/types";
import { testExplorerFrom } from "./files";

/**
 * The Test Run explorer, from the run's own report.
 *
 * A live page listed the old demo's Java files under "Backend tests run on
 * JUnit" for a project whose every test is TypeScript on Vitest. The explorer
 * now lists what the report ran, and nothing else.
 */
describe("the test explorer", () => {
  const snapshot = buildTestSnapshot("p1", "awaiting", 1);
  const explorer = testExplorerFrom(snapshot);

  it("lists exactly the files the run's report holds", () => {
    const reported = snapshot.tests!.suites.map((suite) => suite.path);

    expect(explorer.files.map((file) => file.path)).toEqual(reported);
    expect(explorer.files.some((file) => file.path.endsWith(".java"))).toBe(false);
  });

  it("opens on a file with a failure, and names what the file protects", () => {
    const failing = snapshot.tests!.suites.find((suite) =>
      suite.cases.some((one) => one.outcome === "failed"),
    )!;

    expect(explorer.first).toBe(failing.path);
    expect(explorer.meta[failing.path].failureId).toBeTruthy();
    expect(explorer.meta[failing.path].requirement).not.toBe("");
  });

  it("names the runners the suites ran on", () => {
    expect(explorer.runners).toEqual(["Vitest"]);
  });

  it("is empty before anything has run", () => {
    const none = { ...snapshot, tests: null } as TestSnapshot;

    expect(testExplorerFrom(none)).toEqual({ files: [], meta: {}, first: "", runners: [] });
  });
});
