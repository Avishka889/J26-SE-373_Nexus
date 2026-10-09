import type { Project } from "@/types/project";

/** A phase tab's route segment and the key its progress and attention use. */
export const TAB_PHASE = {
  requirements: "design",
  code: "code",
  testing: "testing",
  deployment: "deployment",
} as const;

export type TabState = "done" | "waiting" | "stopped";

/** What a tab's state is called, for the tooltip and for a screen reader. */
export const TAB_STATE_WORDS: Record<TabState, string> = {
  done: "complete",
  waiting: "waiting on you",
  stopped: "its run stopped",
};

type Waiting = { projectId: string; phase: string; kind: "review" | "rollback" | "stopped" };

/**
 * Where a phase stands, for its tab: waiting on a decision, stopped, or done.
 *
 * The tabs showed nothing but which one was open, and that only in colour, so
 * a reader could not tell from the project's own header that its test review
 * was waiting, or that its design run had stopped. Read from the server's facts:
 * each phase's progress (100 once its approval, or its release, is in) and the
 * items waiting on the signed-in person.
 */
export function tabState(
  phase: (typeof TAB_PHASE)[keyof typeof TAB_PHASE],
  project: Pick<Project, "id" | "phaseProgress">,
  waiting: readonly Waiting[],
): TabState | null {
  const here = waiting.filter((item) => item.projectId === project.id && item.phase === phase);
  if (here.some((item) => item.kind === "stopped")) return "stopped";
  if (here.length > 0) return "waiting";
  if (project.phaseProgress?.[phase] === 100) return "done";
  return null;
}
