import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { buildTestSnapshot } from "../fixtures/buildTestSnapshot";
import { buildView } from "../model/view";
import { SummaryStrip } from "./PhaseChrome";

afterEach(cleanup);

describe("the summary strip", () => {
  // It showed "Mutation score 0%" for a run that never happened (review item C3-6).
  it("says a mutation score that was never measured is not measured", () => {
    const view = buildView({ data: buildTestSnapshot("p1", "awaiting", 1), reviewer: "you" });

    render(
      <SummaryStrip
        view={{ ...view, streaming: false, quality: { ...view.quality, mutationRan: false } }}
        onGoTo={vi.fn()}
      />,
    );

    expect(screen.getByText("Not measured")).toBeTruthy();
    expect(screen.getByText("mutation did not run")).toBeTruthy();
  });
});

describe("the summary strip's tiles", () => {
  // Five across by the window's width, in a column the conversation had
  // narrowed to 650 pixels: "Not measured" wrapped and the labels were cut.
  it("go five across by the width of their own column, not the window's", () => {
    const view = buildView({ data: buildTestSnapshot("p1", "awaiting", 1), reviewer: "you" });
    const { container } = render(<SummaryStrip view={view} onGoTo={vi.fn()} />);

    const tiles = container.querySelector("[data-summary-tiles]") as HTMLElement;
    const classes = tiles.className.split(/\s+/);
    expect(classes).toContain("@5xl:grid-cols-5");
    expect(classes.some((one) => /^(sm|md|lg|xl):grid-cols-/.test(one))).toBe(false);
    expect((tiles.parentElement as HTMLElement).className.split(/\s+/)).toContain("@container");
  });
});
