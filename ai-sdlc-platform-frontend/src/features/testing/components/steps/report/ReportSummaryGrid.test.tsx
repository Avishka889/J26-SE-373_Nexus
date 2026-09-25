import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { buildTestSnapshot } from "../../../fixtures/buildTestSnapshot";
import { buildView } from "../../../model/view";
import { ReportSummaryGrid } from "./ReportSummaryGrid";

afterEach(cleanup);

describe("the report's summary grid", () => {
  // It showed "Mutation score 0%" for a run that never happened (review item C3-6).
  it("says a mutation score that was never measured is not measured", () => {
    const view = buildView({ data: buildTestSnapshot("p1", "awaiting", 1), reviewer: "you" });

    render(
      <ReportSummaryGrid view={{ ...view, quality: { ...view.quality, mutationRan: false } }} onGoTo={vi.fn()} />,
    );

    expect(screen.getByText("Not measured")).toBeTruthy();
    expect(screen.getByText("mutation did not run")).toBeTruthy();
  });
});

describe("the report's failing tile", () => {
  // It read "0 brittle, 0 real regressions" over three failures, because the
  // third kind, the one a first run has, was left out.
  it("counts the failures nothing classified", () => {
    const view = buildView({ data: buildTestSnapshot("p1", "awaiting", 1), reviewer: "you" });

    render(
      <ReportSummaryGrid
        view={{ ...view, inbox: { ...view.inbox, brittle: 0, regressions: 0, unclassified: 3 } }}
        onGoTo={vi.fn()}
      />,
    );

    expect(screen.getByText("0 brittle · 0 real regressions · 3 not classified")).toBeTruthy();
  });

  it("says nothing of them when there are none", () => {
    const view = buildView({ data: buildTestSnapshot("p1", "awaiting", 1), reviewer: "you" });

    render(
      <ReportSummaryGrid
        view={{ ...view, inbox: { ...view.inbox, brittle: 1, regressions: 2, unclassified: 0 } }}
        onGoTo={vi.fn()}
      />,
    );

    expect(screen.getByText("1 brittle · 2 real regressions")).toBeTruthy();
  });
});
