import { useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  CheckCircle2,
  GitBranch,
  History,
  MessageSquare,
  RotateCcw,
} from "lucide-react";
import { Button } from "@/shared/ui/primitives";
import { ActorMark, Note, Panel } from "../bits/index";
import type { DecisionChainStep, TestingRun } from "../../fixtures/types";
import type { StepId, TestingView } from "../../model/view";
import { ReportDecisionChain } from "./report/ReportDecisionChain";
import { ReportSummaryGrid } from "./report/ReportSummaryGrid";
import { StageSection } from "@/shared/ui/stage";
import { formatWhen } from "@/shared/utils/time";

export function StepReport({
  view,
  run,
  decisionChain,
  onGoTo,
  onOpenDeployment,
  onOpenActivity,
  onRollback,
}: {
  view: TestingView;
  /** The demo's run and its last verified build; null on a live page, which has neither. */
  run: TestingRun | null;
  decisionChain: DecisionChainStep[];
  onGoTo: (step: StepId) => void;
  onOpenDeployment: () => void;
  /** Opens the project's Activity Log on this phase's entries. */
  onOpenActivity: () => void;
  onRollback: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const last = run?.lastVerified;

  return (
    <div className="space-y-4">
      {view.superseded && (
        <section className="overflow-hidden rounded-2xl border border-amber-500/30 bg-amber-500/5">
          <div className="flex flex-wrap items-start gap-3 px-4 py-3.5">
            <History className="mt-0.5 h-4 w-4 shrink-0 text-amber-500 dark:text-amber-400" />
            <div className="min-w-0 flex-1">
              <p className="text-[13px] font-semibold">
                Test version {view.build} superseded the decision on test version {view.superseded.build}
              </p>
              <Note className="mt-1">
                {view.superseded.by}{" "}
                {view.superseded.kind === "approved" ? "approved" : "requested changes on"} test
                version {view.superseded.build} at {formatWhen(view.superseded.at)}. That decision
                covered that version only, so this phase is waiting on a decision again. The earlier
                one stays in the audit log.
              </Note>
            </div>
          </div>
        </section>
      )}

      {view.decision?.kind === "approved" && (
        // Recorded as Design Review and Code Review record theirs: who and when,
        // and the way on to the next phase as a button. It was one line here and
        // an underlined "Open Deployment" link.
        <Panel className="border-emerald-500/30 bg-emerald-500/[0.04]">
          <div className="flex flex-wrap items-start gap-3">
            <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-500" />
            <div className="min-w-0 flex-1">
              <p className="text-[15px] font-semibold text-[color:var(--tp-ink)]">
                Tests approved for test version {view.decision.build}
              </p>
              <p className="tp-den mt-1 flex flex-wrap items-center gap-1.5">
                <ActorMark actor={view.decision.by} kind="human" /> at{" "}
                {formatWhen(view.decision.at)}
              </p>
              {view.decision.note && <Note className="mt-2">“{view.decision.note}”</Note>}
              <Note className="mt-2">
                If the tests run again, the approval covers the version it was given for and this
                phase asks again.
              </Note>
              <Button variant="primary" className="mt-3" onClick={onOpenDeployment}>
                Continue to Deployment
                <ArrowRight className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        </Panel>
      )}

      {view.decision && view.decision.kind !== "approved" && (
        <section className="overflow-hidden rounded-2xl border border-amber-500/30 bg-amber-500/5">
          <div className="flex flex-wrap items-start gap-3 px-4 py-3.5">
            <MessageSquare className="mt-0.5 h-4 w-4 shrink-0 text-amber-500 dark:text-amber-400" />
            <div className="min-w-0 flex-1">
              <p className="text-[13px] font-semibold">
                {`Changes requested by ${view.decision.by} at ${formatWhen(view.decision.at)}`}
              </p>
              {view.decision.note && <Note className="mt-1">“{view.decision.note}”</Note>}
            </div>
          </div>
        </section>
      )}

      <StageSection id="review-summary">
        <ReportSummaryGrid
          view={view}
          runSprint={run?.sprint}
          runBranch={run?.branch}
          onGoTo={onGoTo}
        />
      </StageSection>
      <StageSection id="review-decision">
        <ReportDecisionChain decisionChain={decisionChain} />
      </StageSection>
      {/* The record is the Activity Log, and this leads to it. The review
          carried a copy as a table: no other phase's review has one, it was
          the same entries, and it scrolled inside the scrolling page. */}
      <p className="tp-den flex flex-wrap items-center gap-x-2 gap-y-1 px-1">
        <span>
          Everything this phase did and everything decided in it is in the project&apos;s Activity
          Log{view.audit.length > 0 ? `: ${view.audit.length} entries so far` : ""}.
        </span>
        <button
          type="button"
          onClick={onOpenActivity}
          className="inline-flex items-center gap-1 font-medium text-blue-600 underline underline-offset-2 hover:decoration-2 dark:text-blue-400"
        >
          Open the Activity Log
          <ArrowUpRight className="h-3 w-3" />
        </button>
      </p>

      {last && (
        <Panel
          icon={<GitBranch className="h-4 w-4 text-blue-400" />}
          label="Rollback"
          title="Return to the last verified build"
          meta="Only if this build should not ship at all"
        >
          <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
            <div className="min-w-0 flex-1">
              <p className="font-mono text-[12.5px]">
                {last.sprint} · Build {last.build}
              </p>
              <Note className="mt-1 text-[12.5px]">
                Verified {formatWhen(last.at)} - {last.note}. Everything from Build {view.build} stays in the
                branch history.
              </Note>
            </div>
            {!confirming ? (
              <Button variant="outline" onClick={() => setConfirming(true)}>
                <RotateCcw className="h-3.5 w-3.5" />
                Roll back…
              </Button>
            ) : (
              <div className="w-full rounded-lg border border-red-500/30 bg-red-500/5 px-3.5 py-3">
                <p className="text-[13px] font-semibold">
                  Return the deployable build to {last.sprint} · Build {last.build}?
                </p>
                <Note className="mt-1 text-[12.5px]">
                  That build ran {last.note}. Build {view.build} stops being the candidate for
                  Deployment, and this rollback is written to the audit log.
                </Note>
                <div className="mt-2.5 flex flex-wrap gap-2">
                  <Button
                    variant="error"
                    size="sm"
                    onClick={() => {
                      onRollback();
                      setConfirming(false);
                    }}
                  >
                    <RotateCcw className="h-3.5 w-3.5" />
                    Return to Build {last.build}
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => setConfirming(false)}>
                    Cancel
                  </Button>
                </div>
              </div>
            )}
          </div>
        </Panel>
      )}
    </div>
  );
}
