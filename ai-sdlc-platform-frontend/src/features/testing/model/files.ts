import type { FileEntry } from "@/shared/code-viewer/buildFileTree";
import type { TestSnapshot } from "../api/types";
import type { TestFileMeta } from "../fixtures/types";
import { runnerOf } from "./view";

/**
 * The run's own test files, as the Test Run explorer lists them.
 *
 * Read from the test report rather than from a list kept here. The live page
 * showed the old demo's Java files, under "Backend tests run on JUnit", for a
 * project whose every test is TypeScript on Vitest: the explorer had never been
 * wired to the run at all.
 */
export type TestExplorer = {
  files: FileEntry[];
  meta: Record<string, TestFileMeta>;
  /** The file a reader should see first: the first with a failure, else the first. */
  first: string;
  /** The runners the suites ran on, for the panel's caption. */
  runners: string[];
};

export function testExplorerFrom(snapshot: TestSnapshot): TestExplorer {
  const suites = snapshot.tests?.suites ?? [];
  const healed = new Map(
    (snapshot.heal?.attempts ?? [])
      .filter((attempt) => attempt.accepted)
      .map((attempt) => [attempt.suitePath, attempt.testId]),
  );

  const files: FileEntry[] = [];
  const meta: Record<string, TestFileMeta> = {};
  for (const suite of suites) {
    const failed = suite.cases.find(
      (one) => one.outcome === "failed" || one.outcome === "errored",
    );
    const requirements = [
      ...new Set(suite.cases.flatMap((one) => one.traces?.requirementIds ?? [])),
    ];
    const stories = [
      ...new Set(suite.cases.map((one) => one.traces?.storyId ?? "").filter(Boolean)),
    ];
    const healedId = healed.get(suite.path);
    files.push({ path: suite.path, type: "test", ...(healedId ? { tags: ["healed"] } : {}) });
    meta[suite.path] = {
      requirement: requirements.join(", ") || "no requirement recorded",
      requirementTitle: stories.join(", ") || "no story recorded",
      ...(failed ? { failureId: failed.id } : {}),
      ...(healedId ? { healedId } : {}),
    };
  }

  const first = files.find((one) => meta[one.path].failureId)?.path ?? files[0]?.path ?? "";
  const runners = [...new Set(suites.map((suite) => runnerOf(suite.framework)))];
  return { files, meta, first, runners };
}
