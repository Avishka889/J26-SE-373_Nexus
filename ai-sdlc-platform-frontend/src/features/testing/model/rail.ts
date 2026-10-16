import type { TestSnapshot } from "../api/types";
import { TEST_STAGE_META } from "./stages";
import type { StepId, TestingView } from "./view";

/** One chevron of the stage rail, as the shared stepper draws it. */
export interface RailStep {
  id: StepId;
  label: string;
  status: "complete" | "pending" | "generating" | "failed" | "future";
  /** How many things are outstanding at this stage, when any are. */
  badge?: number;
  /** What the badge counts, read in place of the bare number. */
  badgeLabel?: string;
}

/**
 * What the rail says of each stage: whether it ran, and what it left for a
 * person.
 *
 * The server calls a stage complete once it has run, whatever it found, so a
 * run with three failures nobody had classified showed seven green chevrons
 * and a review that could not be approved. The view already knew which stages
 * had something outstanding and how many; the rail drew none of it.
 *
 * Two things are told apart. A stage that waits on a person (repairs to
 * decide, failures to classify, findings to resolve) reads as waiting, with
 * its count. Test Run with failing tests still reads as run, with the count
 * beside it: the failures are a fact about the run, and where they are acted
 * on is Self Healing. The review keeps the reading every phase's review has;
 * the decision bar under the page is what says it waits.
 */
export function railSteps(
  order: readonly { id: StepId; label: string }[],
  stages: TestSnapshot["stages"] | undefined,
  view: TestingView | null,
): RailStep[] {
  return order.map((one) => {
    const stage = stages?.[one.id];
    const ran = stage?.status === "complete" || stage?.status === "skipped";
    const status: RailStep["status"] =
      stage?.status === "generating"
        ? "generating"
        : stage?.status === "failed"
          ? "failed"
          : ran
            ? "complete"
            : "future";
    const step = view?.steps[one.id];
    if (!ran || !step || one.id === "test-review") return { ...one, status };

    const outstanding = step.state === "attention" || step.state === "waiting";
    if (!outstanding) return { ...one, status };
    return {
      ...one,
      status: one.id === "test-run" ? status : "pending",
      badge: step.count,
      badgeLabel: step.hint,
    };
  });
}

/**
 * The stage a reader should be taken to first, when one waits on a person.
 *
 * Beside the conversation the rail is one line, the open stage's name, and the
 * other six chevrons are out of sight; this is the one control that still says
 * where the work is. It was always "To the review", which is the one stage
 * that cannot be decided while a failure waits.
 */
export function attentionShortcut(
  view: TestingView | null,
): { id: StepId; label: string; title: string } | null {
  if (!view) return null;
  const waiting = (["self-healing", "security-scan", "remediation"] as const).find((id) => {
    const state = view.steps[id].state;
    return state === "attention" || state === "waiting";
  });
  if (!waiting) return null;
  const { hint, count } = view.steps[waiting];
  const stage = TEST_STAGE_META[waiting].label;
  // The stage by name: "3 need a person" alone did not say where.
  return {
    id: waiting,
    label: count ? `${count} in ${stage}` : stage,
    title: `Go to ${stage}: ${hint}`,
  };
}

/**
 * The header's progress in a word, as Design's is, where a number misleads.
 *
 * "43%" stood over seven green chevrons: it counted the stages with nothing
 * outstanding, which nothing else on the page showed. The bar keeps that
 * fraction; the label says what it means.
 */
export function progressLabel(view: TestingView | null): string | undefined {
  if (!view || view.build === 0) return undefined;
  if (view.streaming) return "Running";
  if (view.decision) return view.decision.kind === "approved" ? "Approved" : "Changes requested";
  if (!view.decisionPending) return undefined;
  const waits =
    view.failingTests.length > 0 ||
    Object.entries(view.steps).some(
      ([id, step]) => id !== "test-review" && (step.state === "attention" || step.state === "waiting"),
    );
  return waits ? "Needs attention" : "Ready for review";
}
