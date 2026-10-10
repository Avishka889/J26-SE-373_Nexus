import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DESIGN_STAGE_IDS } from "@/types/project";
import { projectsApi } from "@/entities/project";
import { createRequirementsApi } from "../api/createRequirementsApi";
import { computeDesignProgress } from "../model/progress";
import { regeneratingStageIds } from "../model/outdated";
import { readDesign, resetDesignDb } from "./designDb";

/**
 * One source of truth for generation status, asserted over a whole run.
 *
 * The failure this replaces: a new project showed all eight chevrons green,
 * "Ready for review", the waiting-on-you decision bar and a "Generating
 * Architecture Graph" pill at the same time. Four status claims on one screen,
 * three of them false, because three different things were tracking progress. The
 * test that matters is therefore not "does it finish" but "can any two indicators
 * disagree at any point", so it checks every tick.
 */

const api = createRequirementsApi();
const STAGE_MS = 1400;
/** The api's own artificial latency, which fake timers also have to be walked through. */
const API_MS = 200;

/**
 * Start a run under fake timers.
 *
 * The api awaits a short delay of its own before doing anything, and a fake clock
 * does not move on its own, so the call is kicked off first and the clock is
 * advanced far enough for it to land.
 */
async function startRun(id: string, text: string) {
  const pending = api.startDesignRun(id, text);
  await vi.advanceTimersByTimeAsync(API_MS);
  return pending;
}

let projectId: string;

beforeEach(async () => {
  resetDesignDb();
  vi.useFakeTimers();
  const project = await projectsApi.create("Recipe Box", "keep recipes");
  projectId = project.id;
});

afterEach(async () => {
  vi.useRealTimers();
  await projectsApi.delete(projectId);
});

/** Every claim the page can make about status, read from the one snapshot. */
function claims(id: string) {
  const snapshot = readDesign(id);
  const generating = regeneratingStageIds(snapshot);
  const complete = DESIGN_STAGE_IDS.filter((s) => snapshot.stages[s].status === "complete");
  return {
    snapshot,
    pill: generating[0] ?? null,
    chevronsGenerating: generating,
    chevronsComplete: complete,
    label: computeDesignProgress(snapshot).valueLabel,
    everythingGenerated: complete.length === DESIGN_STAGE_IDS.length,
    decisionBarShowing:
      complete.length === DESIGN_STAGE_IDS.length && snapshot.gate.decision === null,
  };
}

describe("a new project", () => {
  it("starts with every stage pending and nothing decided", () => {
    const before = claims(projectId);
    expect(before.snapshot.requirementsVersion).toBe(0);
    expect(before.chevronsComplete).toHaveLength(0);
    expect(before.pill).toBeNull();
    expect(before.decisionBarShowing).toBe(false);
  });

  it("completes stages one at a time, with exactly one generating at a time", async () => {
    const started = await startRun(projectId, "Keep recipes and plan meals for the week.");
    expect(started.requirementsVersion).toBe(1);

    // Only the first stage is in flight. Nothing claims to be generating a
    // wireframe before the requirements have been read.
    let seen = claims(projectId);
    expect(seen.chevronsGenerating).toEqual(["requirements"]);
    expect(seen.decisionBarShowing).toBe(false);

    const order: string[] = [];
    for (let tick = 0; tick < DESIGN_STAGE_IDS.length; tick += 1) {
      await vi.advanceTimersByTimeAsync(STAGE_MS);
      seen = claims(projectId);

      // The invariant, checked at every tick: at most one stage generating, and
      // the pill names that stage and no other.
      expect(seen.chevronsGenerating.length).toBeLessThanOrEqual(1);
      expect(seen.pill).toBe(seen.chevronsGenerating[0] ?? null);

      // Nothing offers a decision until the last stage is done.
      if (!seen.everythingGenerated) {
        expect(seen.decisionBarShowing).toBe(false);
        expect(seen.label).toBe("Generating");
      }

      order.push(...seen.chevronsComplete.filter((id) => !order.includes(id)));
    }

    // Canonical order, one at a time, no skipping.
    expect(order).toEqual([...DESIGN_STAGE_IDS]);
  });

  it("asks for a decision only once every stage is complete", async () => {
    await startRun(projectId, "Keep recipes and plan meals for the week.");
    await vi.advanceTimersByTimeAsync(STAGE_MS * DESIGN_STAGE_IDS.length);

    const done = claims(projectId);
    expect(done.everythingGenerated).toBe(true);
    expect(done.pill).toBeNull();
    expect(done.label).toBe("Ready for review");
    expect(done.decisionBarShowing).toBe(true);
  });

  it("posts each stage summary into the thread as it finishes", async () => {
    await startRun(projectId, "Keep recipes and plan meals for the week.");
    await vi.advanceTimersByTimeAsync(STAGE_MS * 2);

    const thread = readDesign(projectId).thread;
    const summaries = thread.filter((m) => m.kind === "stage_summary");
    expect(summaries).toHaveLength(2);
    expect(summaries[0].stageId).toBe("requirements");
    // The reader's own words come first in the transcript.
    expect(thread[0].kind).toBe("user_note");
    expect(thread[0].content).toContain("Keep recipes");
  });

  it("reads a handful of requirements from a thin input, not a confident dozen", async () => {
    await startRun(projectId, "Build a simple calculator app");
    await vi.advanceTimersByTimeAsync(STAGE_MS);

    const snapshot = readDesign(projectId);
    expect(snapshot.requirements.length).toBeGreaterThan(0);
    expect(snapshot.requirements.length).toBeLessThanOrEqual(4);
    // Every one flagged, because a sentence split is not an analysis.
    for (const requirement of snapshot.requirements) {
      expect(requirement.lowConfidence).toBe(true);
      expect(requirement.confidence).toBeLessThan(60);
    }
    expect(snapshot.assumptions.length).toBeGreaterThan(0);
    expect(snapshot.questions.length).toBeLessThanOrEqual(3);
  });

  it("names no technology anywhere in a derived design", async () => {
    await startRun(projectId, "Keep recipes and plan meals for the week.");
    await vi.advanceTimersByTimeAsync(STAGE_MS * DESIGN_STAGE_IDS.length);

    for (const node of readDesign(projectId).graph.nodes) {
      expect(node).not.toHaveProperty("tech");
    }
  });

  it("moves the project record at the two transitions that really happen", async () => {
    await startRun(projectId, "Keep recipes and plan meals for the week.");
    let project = await projectsApi.get(projectId);
    expect(project?.status).toBe("analyzing");
    expect(project?.requirementText).toContain("recipes");

    await vi.advanceTimersByTimeAsync(STAGE_MS * DESIGN_STAGE_IDS.length);
    project = await projectsApi.get(projectId);
    expect(project?.status).toBe("design");
    expect(project?.reqPhase).toBe("design-review");
    // The stack belongs to Code Generation, and this phase never writes one.
    expect(project?.techStack).toHaveLength(0);
  });
});
