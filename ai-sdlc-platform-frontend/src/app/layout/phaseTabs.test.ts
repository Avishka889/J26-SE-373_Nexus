import { describe, expect, it } from "vitest";
import { tabState } from "./phaseTabs";

const project = {
  id: "p1",
  phaseProgress: { design: 100, code: 80, testing: 0, deployment: 0 },
};

/**
 * The tabs showed which one was open, in colour, and nothing else: not that a
 * review waited, nor that a run had stopped, nor which phases were done.
 */
describe("a phase tab's state", () => {
  it("is done once the phase's approval is in", () => {
    expect(tabState("design", project, [])).toBe("done");
  });

  it("is waiting when a review there waits on the reader", () => {
    expect(tabState("code", project, [{ projectId: "p1", phase: "code", kind: "review" }])).toBe("waiting");
  });

  it("is stopped when the phase's run stopped, whatever else waits", () => {
    expect(
      tabState("code", project, [
        { projectId: "p1", phase: "code", kind: "review" },
        { projectId: "p1", phase: "code", kind: "stopped" },
      ]),
    ).toBe("stopped");
  });

  it("is nothing for a phase not reached, and ignores other projects", () => {
    expect(tabState("testing", project, [{ projectId: "p2", phase: "testing", kind: "review" }])).toBeNull();
  });
});
