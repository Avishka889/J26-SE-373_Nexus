import type { Project } from "@/types/project";

/** Where one phase stands on a project card's strip. */
export type PhaseMark = "done" | "active" | "none";

const PHASES = ["design", "code", "testing", "deployment"] as const;

const PHASE_NAMES: Record<(typeof PHASES)[number], string> = {
  design: "Design",
  code: "Code",
  testing: "Testing",
  deployment: "Deployment",
};

const MARK_WORDS: Record<PhaseMark, string> = {
  done: "complete",
  active: "in progress",
  none: "not started",
};

/** The overall figure spread over four segments: all there is for a project with no phase figures. */
function fromOverall(progress: number): PhaseMark[] {
  const filled = Math.max(1, Math.min(4, Math.ceil(progress / 25)));
  return PHASES.map((_, i) => {
    if (i < filled - 1) return "done";
    if (i === filled - 1) return progress >= 100 ? "done" : "active";
    return "none";
  });
}

/**
 * The four phases of a project, each from its own progress.
 *
 * They were coloured from the overall average, so a project whose design was
 * approved (a quarter of the whole) read as Design in progress. A phase is done
 * at 100, which its approval or its release brings, and in progress above 0.
 */
export function phaseStrip(project: Pick<Project, "progress" | "phaseProgress">): PhaseMark[] {
  const each = project.phaseProgress;
  if (!each) return fromOverall(project.progress);
  return PHASES.map((phase) => (each[phase] >= 100 ? "done" : each[phase] > 0 ? "active" : "none"));
}

/** The strip in words, for a reader who cannot see its colours. */
export function phaseStripWords(strip: readonly PhaseMark[]): string {
  return PHASES.map((phase, i) => `${PHASE_NAMES[phase]} ${MARK_WORDS[strip[i] ?? "none"]}`).join(", ");
}
