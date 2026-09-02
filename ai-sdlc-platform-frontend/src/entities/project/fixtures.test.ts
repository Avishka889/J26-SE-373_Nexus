import { describe, expect, it } from "vitest";
import type { PhaseProgress, ProjectStatus } from "@/types/project";
import { MOCK_PROJECTS } from "./fixtures";

/**
 * What the server's rule gives a project whose current phase waits on its
 * review, which is the posture every phase's fixture derives from a status.
 * The demo's figures were written by hand (72, 54, 38, 91) and matched no rule.
 */
const AWAITING: Partial<Record<ProjectStatus, PhaseProgress>> = {
  design: { design: 80, code: 0, testing: 0, deployment: 0 },
  code: { design: 100, code: 80, testing: 0, deployment: 0 },
  testing: { design: 100, code: 100, testing: 80, deployment: 0 },
  deploy: { design: 100, code: 100, testing: 100, deployment: 80 },
};

describe("the demo projects' progress", () => {
  it("is what the server's rule gives each project's phase", () => {
    for (const project of MOCK_PROJECTS) {
      expect(project.phaseProgress, project.id).toEqual(AWAITING[project.status]);
    }
  });

  it("is the mean of the four phases, rounded half up", () => {
    for (const project of MOCK_PROJECTS) {
      const phases = Object.values(project.phaseProgress ?? {});
      expect(phases).toHaveLength(4);
      const mean = phases.reduce((sum, value) => sum + value, 0) / phases.length;
      expect(project.progress, project.id).toBe(Math.round(mean));
    }
  });
});
