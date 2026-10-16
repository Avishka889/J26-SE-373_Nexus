import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { buildTestSnapshot } from "../../fixtures/buildTestSnapshot";
import { buildView, type TestingView } from "../../model/view";
import { StepTests } from "./StepTests";

afterEach(cleanup);

function renderTests(view: TestingView) {
  render(
    <StepTests
      view={view}
      testFiles={[]}
      testFileMeta={{}}
      testFileContents={{}}
      caption=""
      onGoTo={vi.fn()}
      onOpenFailure={vi.fn()}
      tabs={[]}
      activePath=""
      onSelectFile={vi.fn()}
      onSelectTab={vi.fn()}
      onCloseTab={vi.fn()}
      viewerRef={{ current: null }}
    />,
  );
}

// C3-10: the review could not tell this version's new tests from the regression
// suite carried forward, and a test whose criterion had left the plan passed as
// if it still tested the build.
describe("where each test stands", () => {
  const view = buildView({ data: buildTestSnapshot("p1", "awaiting", 1), reviewer: "you" });
  const [module] = view.modules;

  it("names a module's new tests apart from the ones it carried", () => {
    renderTests({ ...view, modules: [{ ...module, fresh: 1, carried: 2 }, ...view.modules.slice(1)] });

    expect(screen.getByText(/1 new at this version, 2 carried from earlier/)).toBeTruthy();
  });

  it("lists the tests that no longer test the build, and why", () => {
    renderTests({
      ...view,
      obsolete: [
        {
          id: "c",
          name: "US-1 AC-1-9: given an old criterion",
          module: module.name,
          reason: "AC-1-9 is no longer one of US-1's acceptance criteria",
        },
      ],
    });

    expect(screen.getByText(/no longer test this build/)).toBeTruthy();
    expect(screen.getByText("US-1 AC-1-9: given an old criterion")).toBeTruthy();
    expect(screen.getByText(/AC-1-9 is no longer one of US-1's acceptance criteria/)).toBeTruthy();
  });

  it("says nothing of either when nothing is recorded", () => {
    renderTests({ ...view, obsolete: [] });

    expect(screen.queryByText(/carried/)).toBeNull();
    expect(screen.queryByText(/no longer test this build/)).toBeNull();
  });
});

// C3-12: the panel called the suites integration tests. They are unit tests and
// tests through the API, run in process on the in-memory store, and none of
// them touches the database a cloud release uses.
describe("what the suites are called", () => {
  it("does not call them integration tests, and says what they run on", () => {
    renderTests(buildView({ data: buildTestSnapshot("p1", "awaiting", 1), reviewer: "you" }));

    expect(screen.getByText("Unit and API tests, by module")).toBeTruthy();
    expect(screen.queryByText(/integration/i)).toBeNull();
    expect(screen.getByText(/in process, on the app's in-memory store/)).toBeTruthy();
  });
});

/**
 * The live Test Run: "Vitest · protects" with nothing after it, "3 new, 0
 * carried" on a first version, a transcript that opened with a hundred lines
 * of npm warnings, "build 1" for a test version, and a link to "step 3,
 * Quality" on a page whose stages are stages and whose third is Test Quality.
 */
describe("the test run, in the page's own words", () => {
  const view = buildView({ data: buildTestSnapshot("p1", "awaiting", 1), reviewer: "you" });
  const [module] = view.modules;

  it("says nothing of what a suite protects when it traces to no requirement", () => {
    renderTests({ ...view, modules: [{ ...module, requirements: [], fresh: 0, carried: 0 }] });

    expect(screen.queryByText(/protects/)).toBeNull();
  });

  it("says nothing of new and carried on a version that carried nothing", () => {
    renderTests({ ...view, modules: [{ ...module, fresh: 3, carried: 0 }] });

    expect(screen.queryByText(/carried/)).toBeNull();
    expect(screen.queryByText(/3 new/)).toBeNull();
  });

  it("points to Test Quality by its name", () => {
    renderTests(view);

    expect(screen.getByRole("button", { name: "Test Quality" })).toBeTruthy();
    expect(screen.queryByText(/step 3/)).toBeNull();
  });

  it("dates the transcript by test version, as the rest of the page does", () => {
    renderTests(view);

    expect(screen.getByText(new RegExp(`^test version ${view.build} · recorded`))).toBeTruthy();
    expect(screen.queryByText(/^build \d/)).toBeNull();
  });

  it("folds a run of npm warnings and offers every line", () => {
    const warnings = Array.from({ length: 6 }, (_, i) => ({
      kind: "info" as const,
      text: `npm warn EBADENGINE package ${i}`,
    }));
    renderTests({
      ...view,
      transcript: [
        { kind: "cmd", text: "npm install" },
        ...warnings,
        { kind: "fail", text: "tests (apps/api) failed" },
      ],
    });

    expect(screen.getByText("6 lines of npm warnings folded")).toBeTruthy();
    expect(screen.queryByText("npm warn EBADENGINE package 3")).toBeNull();
    expect(screen.getByText("tests (apps/api) failed")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Show all 8 lines" }));
    expect(screen.getByText("npm warn EBADENGINE package 3")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Fold the warnings" })).toBeTruthy();
  });

  it("offers no fold for a transcript with nothing to fold", () => {
    renderTests({ ...view, transcript: [{ kind: "cmd", text: "npm test" }] });

    expect(screen.queryByRole("button", { name: /Show all/ })).toBeNull();
  });
});
