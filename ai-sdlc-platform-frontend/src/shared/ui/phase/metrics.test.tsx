import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { Metric } from "./metrics";

afterEach(cleanup);

/**
 * Every metric tile names its source and window or does not ship, and 39 of
 * 47 named neither: the prop was optional, so nothing asked.
 */
describe("a metric tile", () => {
  it("names where its number comes from", () => {
    render(<Metric label="Files" value={3} source="the files generated at code version 3" />);

    expect(screen.getByText("the files generated at code version 3")).toBeTruthy();
  });

  it("does not compile without a source", () => {
    // @ts-expect-error a tile with no source is a type error, not a review comment
    const unsourced = <Metric label="Files" value={3} />;
    expect(unsourced).toBeTruthy();
  });
});
