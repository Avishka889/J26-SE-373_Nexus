import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { buildTestSnapshot } from "../../fixtures/buildTestSnapshot";
import { buildView, type TestingView } from "../../model/view";
import { StepQuality } from "./StepQuality";

afterEach(cleanup);

function viewWith(quality: Partial<TestingView["quality"]>): TestingView {
  const view = buildView({ data: buildTestSnapshot("p1", "awaiting", 1), reviewer: "you" });
  return { ...view, quality: { ...view.quality, ...quality } };
}

describe("the coverage chart", () => {
  // The floor was a fixed 55%, so a suite at 20% was drawn below the chart.
  it("keeps a low suite inside the plot", () => {
    const { container } = render(
      <StepQuality
        view={viewWith({
          trend: [
            { build: 1, line: 20, branch: 8 },
            { build: 2, line: 24, branch: 10 },
          ],
        })}
      />,
    );

    const chart = container.querySelector('svg[aria-label="Coverage by test version"]');
    const points = [...(chart?.querySelectorAll("circle") ?? [])].map((one) => Number(one.getAttribute("cy")));
    expect(points).toHaveLength(4);
    // The plot runs from 14 at the top to 156 at the bottom of the 190 high box.
    for (const y of points) {
      expect(y).toBeGreaterThanOrEqual(14);
      expect(y).toBeLessThanOrEqual(156);
    }
  });
});

describe("coverage by module", () => {
  // A file with no decisions read "branch 0%", as if every branch were missed.
  it("says a file has no branches rather than 0%", () => {
    render(
      <StepQuality
        view={viewWith({
          byModule: [{ name: "constants.ts", line: 100, branch: 0, branches: 0, covered: 4, total: 4 }],
        })}
      />,
    );

    expect(screen.getByText("no branches")).toBeTruthy();
    expect(screen.queryByText("branch 0%")).toBeNull();
  });
});

describe("mutation testing", () => {
  // It showed a measured "0%" for a run that never happened.
  it("says it did not run instead of scoring it", () => {
    render(
      <StepQuality
        view={viewWith({ mutationRan: false, mutationSkippedReason: "Stryker found no tests to mutate against." })}
      />,
    );

    expect(screen.getByText("Stryker found no tests to mutate against.")).toBeTruthy();
    expect(screen.queryByText("Mutation score")).toBeNull();
  });

  it("lists the survivors, eight at first and all on request", () => {
    const survivors = Array.from({ length: 11 }, (_, index) => ({
      location: `format.ts:${index + 1}`,
      change: "a string was emptied",
      note: "No test noticed.",
    }));
    render(<StepQuality view={viewWith({ mutationRan: true, survivors })} />);

    expect(screen.getAllByText(/^format\.ts:/)).toHaveLength(8);
    fireEvent.click(screen.getByRole("button", { name: "Show all 11" }));
    expect(screen.getAllByText(/^format\.ts:/)).toHaveLength(11);
  });
});

describe("a mutation score over part of the scope", () => {
  // Each app is mutated on its own, and one that gave no score says why (C3-6).
  it("names the app that was not measured, and why", () => {
    render(
      <StepQuality
        view={viewWith({
          mutationRan: true,
          mutationNotMeasured: [{ app: "apps/web", reason: "the mutation run failed and left no report" }],
        })}
      />,
    );

    expect(
      screen.getByText("apps/web was not mutated: the mutation run failed and left no report."),
    ).toBeTruthy();
  });
});

/**
 * The live page: 29 files in a list five screens long, beside a chart of one
 * point whose card stretched as tall as the list; the reason mutation did not
 * run, twice, beginning in lower case; and three files called `index.ts`.
 */
describe("the test quality stage, at the length a reader can take in", () => {
  const files = (count: number) =>
    Array.from({ length: count }, (_, i) => ({
      name: `file${i}.ts`,
      path: `apps/api/src/file${i}.ts`,
      line: i * 5,
      branch: 50,
      branches: 2,
      covered: i,
      total: 20,
    }));

  it("lists the eight least covered files and offers the rest", () => {
    render(<StepQuality view={viewWith({ byModule: files(12) })} />);

    expect(screen.getByText("The 8 least covered of 12 files")).toBeTruthy();
    expect(screen.getByTitle("apps/api/src/file7.ts")).toBeTruthy();
    expect(screen.queryByTitle("apps/api/src/file8.ts")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Show all 12 files" }));
    expect(screen.getByTitle("apps/api/src/file11.ts")).toBeTruthy();
  });

  it("offers nothing more when it lists them all", () => {
    render(<StepQuality view={viewWith({ byModule: files(8) })} />);

    expect(screen.queryByRole("button", { name: /Show all/ })).toBeNull();
  });

  it("names a file with its folder, so two of one name can be told apart", () => {
    render(
      <StepQuality
        view={viewWith({
          byModule: [
            { name: "index.ts", path: "apps/api/src/index.ts", line: 10, branch: 0, branches: 0, covered: 1, total: 10 },
            { name: "index.ts", path: "apps/web/src/index.ts", line: 20, branch: 0, branches: 0, covered: 2, total: 10 },
          ],
        })}
      />,
    );

    expect(screen.getByTitle("apps/api/src/index.ts").textContent).toBe("apps/api/src/index.ts");
    expect(screen.getByTitle("apps/web/src/index.ts").textContent).toBe("apps/web/src/index.ts");
  });

  it("draws no chart of one measurement, and says what was measured", () => {
    const { container } = render(
      <StepQuality view={viewWith({ trend: [{ build: 3, line: 70.98, branch: 69.57 }] })} />,
    );

    expect(container.querySelector('svg[aria-label="Coverage by test version"]')).toBeNull();
    expect(
      screen.getByText(/Measured once, at test version 3: line coverage 70\.98%, branch coverage 69\.57%/),
    ).toBeTruthy();
  });

  it("says why mutation did not run once, as a sentence", () => {
    render(
      <StepQuality
        view={viewWith({
          mutationRan: false,
          mutationSkippedReason: "the suite has failing tests, so mutation cannot say anything until they pass",
          trendNote: "the suite has failing tests, so mutation cannot say anything until they pass",
        })}
      />,
    );

    expect(
      screen.getAllByText("The suite has failing tests, so mutation cannot say anything until they pass."),
    ).toHaveLength(1);
    expect(screen.queryByText(/^the suite has failing tests/)).toBeNull();
  });
});
