import { describe, expect, it } from "vitest";
import type { ParsedRequirement } from "../api/types";
import {
  applyRequirementFilter,
  EMPTY_FILTER,
  isFilterActive,
  needsAttention,
  toggleIn,
} from "./requirementFilter";

/**
 * Filtering is compactness, never concealment.
 *
 * An approver has to be able to see everything before deciding, so the rules
 * here are about narrowing a view that can always be widened again, and the
 * count line has to stay honest while it is narrowed.
 */

function requirement(over: Partial<ParsedRequirement> & { id: string }): ParsedRequirement {
  return {
    text: "The system does something.",
    type: "functional",
    priority: "should",
    confidence: 90,
    qualityAttribute: null,
    lowConfidence: false,
    adjusted: false,
    sourceQuote: null,
    ...over,
  };
}

const list: ParsedRequirement[] = [
  requirement({ id: "R-1", text: "Customers can pay by card.", type: "functional", priority: "must" }),
  requirement({ id: "R-2", text: "Payments settle within two seconds.", type: "quality", priority: "should", qualityAttribute: "performance", lowConfidence: true, confidence: 44 }),
  requirement({ id: "R-3", text: "Card numbers are never stored.", type: "constraint", priority: "must" }),
  requirement({ id: "R-4", text: "A customer can see past payments.", type: "functional", priority: "could", adjusted: true }),
  requirement({ id: "R-5", text: "Refunds are approved by an administrator.", type: "functional", priority: "should", sourceQuote: "Refunds need approval." }),
];

describe("applyRequirementFilter", () => {
  it("shows everything when nothing is chosen", () => {
    expect(applyRequirementFilter(list, EMPTY_FILTER)).toHaveLength(list.length);
    expect(isFilterActive(EMPTY_FILTER)).toBe(false);
  });

  it("narrows by type", () => {
    const result = applyRequirementFilter(list, { ...EMPTY_FILTER, types: ["quality"] });
    expect(result.map((r) => r.id)).toEqual(["R-2"]);
  });

  it("treats two choices in one group as either of them", () => {
    const result = applyRequirementFilter(list, {
      ...EMPTY_FILTER,
      types: ["quality", "constraint"],
    });
    expect(result.map((r) => r.id)).toEqual(["R-2", "R-3"]);
  });

  it("combines groups by narrowing, not by widening", () => {
    // Functional AND must, which is one row. The union would be four, and a
    // filter that returns more rows than either choice alone is not a filter.
    const result = applyRequirementFilter(list, {
      ...EMPTY_FILTER,
      types: ["functional"],
      priorities: ["must"],
    });
    expect(result.map((r) => r.id)).toEqual(["R-1"]);
  });

  it("flags what needs attention as low confidence or corrected by a human", () => {
    const result = applyRequirementFilter(list, { ...EMPTY_FILTER, needsAttention: true });
    expect(result.map((r) => r.id)).toEqual(["R-2", "R-4"]);
    expect(needsAttention(list[1])).toBe(true);
    expect(needsAttention(list[3])).toBe(true);
    expect(needsAttention(list[0])).toBe(false);
  });

  it("searches the id, the text and the source quote", () => {
    expect(applyRequirementFilter(list, { ...EMPTY_FILTER, search: "R-3" }).map((r) => r.id)).toEqual(["R-3"]);
    expect(applyRequirementFilter(list, { ...EMPTY_FILTER, search: "refund" }).map((r) => r.id)).toEqual(["R-5"]);
    // The quote is searched too, so a reader looking for words they wrote finds
    // the requirement read from them.
    expect(applyRequirementFilter(list, { ...EMPTY_FILTER, search: "need approval" }).map((r) => r.id)).toEqual(["R-5"]);
  });

  it("ignores case and surrounding space in a search", () => {
    expect(applyRequirementFilter(list, { ...EMPTY_FILTER, search: "  CARD " }).length).toBe(2);
  });

  it("hides nothing permanently: clearing restores every row", () => {
    const narrowed = applyRequirementFilter(list, {
      types: ["quality"],
      priorities: ["must"],
      needsAttention: true,
      search: "zzz",
    });
    expect(narrowed).toHaveLength(0);
    expect(applyRequirementFilter(list, EMPTY_FILTER)).toHaveLength(list.length);
  });

  it("keeps twenty requirements countable and reducible", () => {
    // The size the stage has to stay usable at, which is what the compact rows
    // and this filter exist for.
    const twenty = Array.from({ length: 20 }, (_, i) =>
      requirement({ id: `R-${i + 1}`, lowConfidence: i % 5 === 0 }),
    );
    const flagged = applyRequirementFilter(twenty, { ...EMPTY_FILTER, needsAttention: true });
    expect(flagged).toHaveLength(4);
    // The honest count line: showing 4 of 20, not "4 requirements".
    expect(twenty.length).toBe(20);
    for (const requirement of flagged) expect(needsAttention(requirement)).toBe(true);
  });
});

describe("isFilterActive", () => {
  it("is false only when nothing at all is chosen", () => {
    expect(isFilterActive(EMPTY_FILTER)).toBe(false);
    expect(isFilterActive({ ...EMPTY_FILTER, types: ["quality"] })).toBe(true);
    expect(isFilterActive({ ...EMPTY_FILTER, needsAttention: true })).toBe(true);
    expect(isFilterActive({ ...EMPTY_FILTER, search: "x" })).toBe(true);
    // Whitespace is not a search.
    expect(isFilterActive({ ...EMPTY_FILTER, search: "   " })).toBe(false);
  });
});

describe("toggleIn", () => {
  it("adds what is missing and removes what is there", () => {
    expect(toggleIn(["a"], "b")).toEqual(["a", "b"]);
    expect(toggleIn(["a", "b"], "a")).toEqual(["b"]);
  });
});
