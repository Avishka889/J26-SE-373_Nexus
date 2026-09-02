import { describe, expect, it } from "vitest";
import { DESCRIPTION_LIMIT, NAME_LIMIT, projectDescription, projectName } from "./naming";

const FOMMP =
  "Build a web application for FOMMP (Farmer Organizations Management and Monitoring Platform) as specified in the attached BRD. Core modules: AC Profile Management, Business Plan Management, Asset Management, Knowledge Management, and role based Dashboards. Start with the pilot scale MVP.";

describe("projectName", () => {
  it("uses the first paragraph of what was typed", () => {
    // The first paragraph itself carries a single newline, so this only passes
    // if the split is on a blank line and not on any newline.
    expect(
      projectName("Build a calculator\nfor students\n\nIt should add and subtract.", []),
    ).toBe("Build a calculator\nfor students");
  });

  it("truncates a long sentence, because a name is a label", () => {
    const name = projectName(FOMMP, ["srs.pdf"]);
    expect(name).toHaveLength(NAME_LIMIT + 1);
    expect(name.endsWith("…")).toBe(true);
  });

  it("falls back to the filename when nothing was typed", () => {
    // Never the document body: forty eight characters of an SRS preamble is
    // not a name, which is the property a previous fix round established.
    expect(projectName("   ", ["FOMMP-BRD.pdf"])).toBe("FOMMP-BRD.pdf");
  });

  it("prefers the typed text when both are present", () => {
    expect(projectName("Pharmacy dispensing", ["FOMMP-BRD.pdf"])).toBe("Pharmacy dispensing");
  });

  it("names the unreachable empty case rather than returning a blank", () => {
    expect(projectName("", [])).toBe("Untitled project");
  });
});

describe("projectDescription", () => {
  it("cuts a long description at a word boundary", () => {
    const out = projectDescription(FOMMP, ["srs.pdf"]);

    expect(out.length).toBeLessThanOrEqual(DESCRIPTION_LIMIT + 1);
    expect(out.endsWith("…")).toBe(true);
    // Nothing invented: what is kept is a prefix of what was typed.
    expect(FOMMP.startsWith(out.slice(0, -1))).toBe(true);
    // A word boundary, not a mid word cut: the input carries on with a space.
    expect(FOMMP[out.length - 1]).toBe(" ");
  });

  it("returns text under the cap untouched, with no ellipsis", () => {
    const text = "Build a calculator that adds and subtracts.";
    expect(projectDescription(text, [])).toBe(text);
  });

  it("returns text with no sentence terminator untouched", () => {
    // No period, no exclamation mark, no question mark anywhere in it: this
    // used to depend on splitSentences finding at least one, and now must not.
    const text = "Build a calculator that adds and subtracts";
    expect(projectDescription(text, [])).toBe(text);
  });

  it("returns text of exactly the limit untouched", () => {
    const text = "x".repeat(DESCRIPTION_LIMIT);
    expect(projectDescription(text, [])).toBe(text);
  });

  it("cuts a single word longer than the cap, since there is no space to cut at", () => {
    const text = "x".repeat(DESCRIPTION_LIMIT + 20);
    expect(projectDescription(text, [])).toBe(`${"x".repeat(DESCRIPTION_LIMIT)}…`);
  });

  it("names the source when nothing was typed", () => {
    expect(projectDescription("", ["FOMMP-BRD.pdf"])).toBe("From FOMMP-BRD.pdf");
    expect(projectDescription("", ["a.pdf", "b.docx"])).toBe("From a.pdf and b.docx");
    expect(projectDescription("", ["a.pdf", "b.docx", "c.md"])).toBe("From a.pdf and 2 more");
  });

  it("is empty when there is nothing to describe", () => {
    expect(projectDescription("", [])).toBe("");
  });
});

describe("limits", () => {
  it("pins the limits, because one of them is mirrored in Python", () => {
    // A later task mirrors NAME_LIMIT as PROVISIONAL_NAME_LIMIT in the
    // orchestrator's runner, to decide whether a name was truncated and is worth
    // replacing. Nothing links the two files, so this is the link.
    expect(NAME_LIMIT).toBe(48);
    expect(DESCRIPTION_LIMIT).toBe(200);
  });
});
