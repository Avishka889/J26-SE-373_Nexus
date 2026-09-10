import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { DESIGN_STAGE_IDS } from "@/types/project";
import { STAGE_META, STAGE_SECTIONS, nextStageId, previousStageId } from "./stages";

/**
 * The anchor pills name blocks that exist.
 *
 * They double as the reader's position indicator, so a pill pointing at nothing
 * is worse than no pill: it scrolls nowhere and the highlight never reaches it.
 * The ids are DOM ids, which no type can check, so this reads the stage
 * components and looks for them.
 */

const STAGES_DIR = join(__dirname, "..", "components", "stages");

function renderedSectionIds(): Set<string> {
  const ids = new Set<string>();
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(path);
        continue;
      }
      if (!entry.name.endsWith(".tsx")) continue;
      const source = readFileSync(path, "utf8");
      for (const match of source.matchAll(/<StageSection\s+id="([a-z0-9-]+)"/g)) {
        ids.add(match[1]);
      }
    }
  };
  walk(STAGES_DIR);
  return ids;
}

describe("stage sections", () => {
  it("gives every stage an entry", () => {
    for (const id of DESIGN_STAGE_IDS) {
      expect(STAGE_SECTIONS[id], `no sections declared for ${id}`).toBeTruthy();
      expect(STAGE_SECTIONS[id].length).toBeGreaterThan(0);
    }
  });

  it("uses ids that are unique across the whole phase", () => {
    const all = DESIGN_STAGE_IDS.flatMap((id) => STAGE_SECTIONS[id].map((s) => s.id));
    expect(new Set(all).size).toBe(all.length);
  });

  it("names a block that the stage actually renders", () => {
    const rendered = renderedSectionIds();
    // Requirements Analysis is rendered by its own component tree rather than a
    // file under stages/, so it is checked by its own test instead.
    const skip = new Set(STAGE_SECTIONS.requirements.map((s) => s.id));

    for (const stage of DESIGN_STAGE_IDS) {
      for (const section of STAGE_SECTIONS[stage]) {
        if (skip.has(section.id)) continue;
        expect(
          rendered.has(section.id),
          `${stage} declares the anchor "${section.id}" but no StageSection renders it`,
        ).toBe(true);
      }
    }
  });

  it("gives every anchor a label short enough to be a pill", () => {
    for (const stage of DESIGN_STAGE_IDS) {
      for (const section of STAGE_SECTIONS[stage]) {
        expect(section.label.length).toBeGreaterThan(0);
        expect(section.label.length, `${section.id} label is too long for a pill`).toBeLessThan(18);
      }
    }
  });
});

describe("stage order", () => {
  it("walks forward from the first stage to the gate and stops", () => {
    const walked: string[] = [];
    let current: (typeof DESIGN_STAGE_IDS)[number] | null = DESIGN_STAGE_IDS[0];
    while (current) {
      walked.push(current);
      current = nextStageId(current);
    }
    expect(walked).toEqual([...DESIGN_STAGE_IDS]);
    // The last stage leads to the decision, not to another stage.
    expect(nextStageId("design-review")).toBeNull();
  });

  it("walks backward the same way", () => {
    expect(previousStageId("requirements")).toBeNull();
    expect(previousStageId("design-review")).toBe("sprint-plan");
    for (const id of DESIGN_STAGE_IDS.slice(1)) {
      const back = previousStageId(id);
      expect(back).toBeTruthy();
      expect(nextStageId(back!)).toBe(id);
    }
  });

  it("uses standard industry names, never an internal component code", () => {
    for (const id of DESIGN_STAGE_IDS) {
      const meta = STAGE_META[id];
      for (const text of [meta.label, meta.heading, meta.blurb]) {
        expect(text, `${id} leaks a component code`).not.toMatch(/\bC[1-4]\b/);
        expect(text).not.toContain("—");
        expect(text).not.toContain("–");
      }
      // An abbreviation is spelled out where it first appears.
      if (meta.heading.includes("SAG")) {
        expect(meta.heading).toContain("Semantic Architecture Graph");
      }
    }
  });
});
