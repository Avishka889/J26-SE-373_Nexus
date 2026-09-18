import { describe, expect, it } from "vitest";
import { total } from "../total";

describe("total", () => {
  it("adds price times quantity across the items", () => {
    expect(total([{ price: 2, quantity: 3 }, { price: 1, quantity: 1 }])).toBe(7);
  });

  it("is zero for an empty basket", () => {
    expect(total([])).toBe(0);
  });

  it.skip("handles a currency other than the default", () => {
    // Skipped on purpose: the fixture needs one case the framework declined to
    // run, so `skipped` and `not-run` can be told apart in a real report.
    expect(true).toBe(true);
  });
});
