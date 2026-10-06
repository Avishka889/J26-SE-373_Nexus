import { DecisionBar as PhaseDecisionBar } from "@/shared/ui/phase";
import { approval, type DeploymentPageView } from "../model/view";

/**
 * Deployment's wording for the shared phase gate.
 *
 * Approval is held while the server's release guards refuse it, and the bar
 * says what they refuse, in their words. Requesting changes is how a person
 * rebuilds the candidate without an update they left out, and it is open
 * unless the review is of code the project has moved past: changes there would
 * analyse the older code again, and the bar says what to do instead.
 */
export function DecisionBar({
  view,
  goAhead,
  busy,
  onApprove,
  onRequestChanges,
  changesDisabledReason,
}: {
  view: DeploymentPageView;
  /** The go ahead a cloud release needs, given on the review. */
  goAhead: boolean;
  busy: boolean;
  onApprove: () => void;
  onRequestChanges: (note: string) => void | Promise<unknown>;
  changesDisabledReason?: string;
}) {
  const state = approval(view, goAhead);
  const detail = [
    `Deploy version ${view.version}`,
    `${view.levels.high} High, ${view.levels.medium} Medium, ${view.levels.low} Low`,
    view.needDecision > 0
      ? `${view.needDecision} ${view.needDecision === 1 ? "decision" : "decisions"} owed`
      : "every decision taken",
  ].join(" · ");

  return (
    <PhaseDecisionBar
      headline="This release is waiting on you"
      detail={detail}
      approveLabel="Approve and release"
      approveDisabled={state.disabled}
      approveDisabledReason={state.disabled ? state.reason : undefined}
      notePrompt="What needs to change before this can ship"
      notePlaceholder="Leave supertest out until its release notes are checked, then rebuild the candidate."
      onApprove={onApprove}
      onRequestChanges={onRequestChanges}
      changesDisabledReason={changesDisabledReason}
      busy={busy}
    />
  );
}
