import { describe, expect, it } from "vitest";
import { composeRequirementText } from "./compose";
import type { Attachment } from "@/types/document";

const doc = (id: string, text: string): Attachment => ({
  id,
  name: `${id}.md`,
  format: "md",
  bytes: text.length,
  pages: null,
  pagesWithoutText: null,
  words: text.split(/\s+/).length,
  chars: text.length,
  charsAvailable: text.length,
  truncated: false,
  text,
});

describe("composeRequirementText", () => {
  it("puts the typed text first, then each document in order", () => {
    expect(composeRequirementText("Focus on dispensing.", [doc("a", "One."), doc("b", "Two.")])).toBe(
      "Focus on dispensing.\n\nOne.\n\nTwo.",
    );
  });

  it("adds no separator markers", () => {
    // A "--- name.md ---" line would land in the string split_sentences()
    // measures and that source_span offsets index into, inflating the evidence
    // count with text nobody wrote.
    const composed = composeRequirementText("Typed.", [doc("a", "One.")]);
    expect(composed).not.toMatch(/---/);
    expect(composed).not.toMatch(/a\.md/);
  });

  it("works with no typed text", () => {
    expect(composeRequirementText("   ", [doc("a", "One.")])).toBe("One.");
  });

  it("works with no attachments", () => {
    expect(composeRequirementText("Typed.", [])).toBe("Typed.");
  });

  it("drops a removed document from the result", () => {
    const all = [doc("a", "One."), doc("b", "Two.")];
    expect(composeRequirementText("", all.filter((d) => d.id !== "a"))).toBe("Two.");
  });
});
