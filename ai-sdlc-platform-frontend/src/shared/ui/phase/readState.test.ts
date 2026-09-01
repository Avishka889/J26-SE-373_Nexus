import { describe, expect, it } from "vitest";
import { readState } from "./readState";

/**
 * One rule for what a phase shows about its last read.
 *
 * TanStack Query marks a query as errored when a background refetch fails, and
 * keeps the data it had. Design and Code took any error for a failed page and
 * replaced the workspace, drafts and all; Testing and Deployment showed nothing.
 */
describe("a phase's read state", () => {
  it("is loading before anything arrived", () => {
    expect(readState({ isError: false, data: undefined })).toBe("loading");
  });

  it("failed when the first read failed", () => {
    expect(readState({ isError: true, data: undefined })).toBe("failed");
  });

  it("stale when a later read failed and the last answer is still shown", () => {
    expect(readState({ isError: true, data: { version: 3 } })).toBe("stale");
  });

  it("fresh otherwise", () => {
    expect(readState({ isError: false, data: { version: 3 } })).toBe("fresh");
  });
});
