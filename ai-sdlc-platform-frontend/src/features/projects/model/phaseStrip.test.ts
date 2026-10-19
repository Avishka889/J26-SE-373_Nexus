import { describe, expect, it } from "vitest";
import { phaseStrip, phaseStripWords } from "./phaseStrip";

/**
 * The four segments on a Home card are the four phases, but they were coloured
 * from the project's overall average: a project whose design was approved (a
 * quarter of the whole) showed Design in progress, and one whose code was
 * approved showed Code in progress.
 */
describe("the four-phase strip", () => {
  it("shows an approved design as done, and Code not started", () => {
    const strip = phaseStrip({
      progress: 25,
      phaseProgress: { design: 100, code: 0, testing: 0, deployment: 0 },
    });

    expect(strip).toEqual(["done", "none", "none", "none"]);
  });

  it("shows each phase from its own progress", () => {
    const strip = phaseStrip({
      progress: 50,
      phaseProgress: { design: 100, code: 100, testing: 0, deployment: 0 },
    });

    expect(strip).toEqual(["done", "done", "none", "none"]);
  });

  it("shows a phase waiting on its review as in progress", () => {
    const strip = phaseStrip({
      progress: 20,
      phaseProgress: { design: 80, code: 0, testing: 0, deployment: 0 },
    });

    expect(strip).toEqual(["active", "none", "none", "none"]);
  });

  it("falls back to the overall figure for a project that carries no phase figures", () => {
    expect(phaseStrip({ progress: 60 })).toEqual(["done", "done", "active", "none"]);
    expect(phaseStrip({ progress: 100 })).toEqual(["done", "done", "done", "done"]);
  });

  it("says in words what the colours say", () => {
    expect(phaseStripWords(["done", "active", "none", "none"])).toBe(
      "Design complete, Code in progress, Testing not started, Deployment not started",
    );
  });
});
