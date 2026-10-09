import { describe, expect, it } from "vitest";
import { reviewIsOpen } from "./reviewIsOpen";

const never = () => {
  throw new Error("asked the fixture rule with a run present");
};

/**
 * After "Request changes" the bar came back while the design regenerated, and
 * Approve was refused; Testing offered a decision after a run had failed.
 */
describe("whether a phase's review is open", () => {
  it("is open while the run waits at its gate, for the version on screen", () => {
    expect(reviewIsOpen({ state: "awaiting_gate", version: 3 }, 3, never)).toBe(true);
  });

  it("is closed while the run regenerates after a change request", () => {
    expect(reviewIsOpen({ state: "running", version: 4 }, 4, never)).toBe(false);
    expect(reviewIsOpen({ state: "queued", version: 4 }, 4, never)).toBe(false);
  });

  it("is closed after a run failed, and for a version the run is not at", () => {
    expect(reviewIsOpen({ state: "failed", version: 3 }, 3, never)).toBe(false);
    expect(reviewIsOpen({ state: "awaiting_gate", version: 2 }, 3, never)).toBe(false);
  });

  it("falls back to the fixtures' own rule when there is no run", () => {
    expect(reviewIsOpen(null, 1, () => true)).toBe(true);
  });
});
