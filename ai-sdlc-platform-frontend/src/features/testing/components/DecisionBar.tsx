import { DecisionBar as PhaseDecisionBar } from "@/shared/ui/phase";
import type { TestStageId } from "@/types/project";
import { counted, type TestingView } from "../model/view";

/** How many failing tests the bar names before it counts the rest. */
const NAMED = 3;

/** "A, B and C", or "A, B, C and 2 more": the bar has a line, not a list. */
function named(refs: string[]): string {
  if (refs.length <= 1) return refs.join("");
  if (refs.length <= NAMED) return `${refs.slice(0, -1).join(", ")} and ${refs[refs.length - 1]}`;
  return `${refs.slice(0, NAMED).join(", ")} and ${refs.length - NAMED} more`;
}

/**
 * Testing's wording for the shared phase gate. The bar itself is shared so every
 * phase decides the same way; only the sentences differ, and they belong here
 * because they read off this phase's view.
 */
export function DecisionBar({
  view,
  onApprove,
  onRequestChanges,
  onOpenStage,
  busy = false,
}: {
  view: TestingView;
  /** The note is the reviewer's reason for approving with something outstanding. */
  onApprove: (note?: string) => void | Promise<unknown>;
  onRequestChanges: (note: string) => void | Promise<unknown>;
  /** Opens a stage; the reason Approve is held leads to where it is dealt with. */
  onOpenStage?: (stage: TestStageId) => void;
  /** A decision is on its way, so neither action may be sent twice. */
  busy?: boolean;
}) {
  const failing = view.failingTests.length;
  const outstanding = [
    // What the run did not prove comes first: approving over it was one click
    // that read as "every proof passed".
    ...view.unproven,
    view.inbox.awaiting > 0 ? `${counted(view.inbox.awaiting, "repair", "repairs")} awaiting you` : null,
    // While failing tests hold the approval they are named below, by
    // reference. Counted here as well they were said twice, and the pinned
    // bar ran to five lines on a laptop.
    failing === 0 && view.inbox.regressions > 0
      ? `${counted(view.inbox.regressions, "regression", "regressions")} needing a code change`
      : null,
    failing === 0 && view.inbox.unclassified > 0
      ? `${counted(view.inbox.unclassified, "failure", "failures")} not yet called a stale test or a regression`
      : null,
    view.findingCounts.toResolve > 0
      ? `${counted(view.findingCounts.toResolve, "finding", "findings")} to resolve`
      : null,
  ].filter(Boolean) as string[];

  const prefix = view.superseded
    ? `${view.superseded.kind === "approved" ? "Approved" : "Changes requested"} for test version ${view.superseded.build} by ${view.superseded.by}`
    : `Test version ${view.build}`;

  return (
    <PhaseDecisionBar
      headline={
        view.superseded
          ? `Test version ${view.build} arrived after your approval, so this phase is waiting on you again`
          : "This phase is waiting on you"
      }
      detail={outstanding.length > 0 ? prefix : `${prefix} · nothing outstanding, every proof passed`}
      concerns={outstanding}
      // It said "and start Deployment", and nothing started: Deployment is
      // started from its own page, which this approval unlocks.
      approveLabel="Approve the tests"
      approveDisabled={failing > 0}
      // By reference, and in a line. It quoted the first test's whole name, a
      // story and a criterion of forty words, and the bar ran to seven lines.
      approveDisabledReason={
        failing > 0
          ? `${failing} test${failing === 1 ? "" : "s"} fail${failing === 1 ? "s" : ""} (${named(view.failingRefs)}). Deployment runs the same tests and would refuse this build.`
          : undefined
      }
      approveDisabledAction={
        failing > 0 && onOpenStage
          ? { label: "See why in Self Healing", onClick: () => onOpenStage("self-healing") }
          : undefined
      }
      // A change request here runs the phase again. Nothing reads the note as
      // an instruction, so it is asked for as what it is: the reason.
      notePrompt="Why the tests should run again"
      notePlaceholder="For example: two tests quarantined and one repair kept. The note is kept on the record. It does not steer how the tests are written."
      onApprove={onApprove}
      onRequestChanges={onRequestChanges}
      busy={busy}
    />
  );
}
