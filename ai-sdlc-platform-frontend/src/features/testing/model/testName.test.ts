import { describe, expect, it } from "vitest";
import { firstLine, lineIn, testLabel } from "./testName";

/**
 * A generated acceptance test is named with its whole story and its whole
 * criterion: "As a receptionist, I can record a doctor ... US-2 AC-2-1: given
 * ..., when ..., then ...". Used as a title it filled seven lines of the
 * decision bar, and three failures in one story read as the same row three
 * times, because the list cut each off before the part that differs.
 */
describe("a test's name, taken apart", () => {
  const NAME =
    "As a receptionist, I can record a doctor with a name US-2 AC-2-1: given no doctor, when one is saved, then it is retrievable";

  it("gives the story and criterion it is for as its reference", () => {
    expect(testLabel(NAME)).toEqual({
      ref: "US-2 AC-2-1",
      story: "As a receptionist, I can record a doctor with a name",
      text: "given no doctor, when one is saved, then it is retrievable",
    });
  });

  it("reads a criterion numbered more deeply, and one with no story sentence", () => {
    expect(testLabel("US-12 AC-12-3-1: given a, when b, then c")).toEqual({
      ref: "US-12 AC-12-3-1",
      story: "",
      text: "given a, when b, then c",
    });
  });

  it("leaves a name with no reference as it is", () => {
    expect(testLabel("/doctors implements its contract implements get-doctors")).toEqual({
      ref: null,
      story: "",
      text: "/doctors implements its contract implements get-doctors",
    });
  });
});

describe("what a runner said about a failure", () => {
  const MESSAGE = [
    "AssertionError: expected 404 to be less than 400",
    "    at /tmp/work/p_1/v1/apps/api/src/__tests__/US-2.criteria.test.ts:37:33",
    "    at processTicksAndRejections (node:internal/process/task_queues:105:5)",
    "    at file:///tmp/work/p_1/v1/node_modules/@vitest/runner/dist/index.js:533:5",
  ].join("\n");

  it("is its first line, without the stack", () => {
    expect(firstLine(MESSAGE)).toBe("AssertionError: expected 404 to be less than 400");
    expect(firstLine("")).toBe("");
    expect(firstLine(undefined)).toBe("");
  });

  it("names the line of the test file it failed at", () => {
    expect(lineIn(MESSAGE, "apps/api/src/__tests__/US-2.criteria.test.ts")).toBe(37);
  });

  it("names no line when the stack does not pass through the test file", () => {
    expect(lineIn(MESSAGE, "apps/api/src/__tests__/US-3.criteria.test.ts")).toBe(0);
    expect(lineIn("", "apps/api/src/__tests__/US-2.criteria.test.ts")).toBe(0);
  });
});
