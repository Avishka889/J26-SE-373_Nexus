import { ConversationDock, ConversationPanel, ConversationToggle } from "@/shared/ui/conversation";
import {
  StageFooterNav,
  StageNav,
  StageShell,
  computedBeforeIn,
  stageLabelIn,
} from "@/shared/ui/stage";
import { useRunsOn } from "@/entities/settings";
import { PageLoader } from "@/shared/ui/Spinner";
import { useNavigate } from "react-router-dom";
import { DEPLOY_STAGE_IDS } from "@/types/project";
import { DecisionBar } from "./components/DecisionBar";
import { DeploymentHeader } from "./components/DeploymentHeader";
import {
  CodeMovedOnNotice,
  NewerCodeNotice,
  PhaseLoadError,
  PhaseNotRun,
  PhaseWaitingOnTesting,
} from "./components/EmptyStates";
import { StageChangelog } from "./components/stages/StageChangelog";
import { StageImpact } from "./components/stages/StageImpact";
import { StageMonitoring } from "./components/stages/StageMonitoring";
import { StagePipeline } from "./components/stages/StagePipeline";
import { StageRelease } from "./components/stages/StageRelease";
import { StageReview } from "./components/stages/StageReview";
import { StageRisk } from "./components/stages/StageRisk";
import { StageRollbackPlan } from "./components/stages/StageRollbackPlan";
import { StageStaging } from "./components/stages/StageStaging";
import { StageUpdates } from "./components/stages/StageUpdates";
import { useDeploymentPage } from "./hooks";
import { DEPLOY_CHROME, DEPLOY_STAGE_META } from "./model/stages";
import { reviewMovedPastLine } from "./model/view";
import {
  ReconnectingNotice,
  RunStoppedNotice,
  stageOpeningNext,
  workingStage,
} from "@/shared/ui/phase";

/**
 * The deployment phase, on the chrome every gated phase uses.
 *
 * Ten stages: seven analysis stages a run produces, the review that gates the
 * release, and the release and monitoring the orchestrator carries out after
 * it. Everything on the page is read from one `DeploySnapshot`; the page never
 * computes a risk level and never decides whether a release may go ahead.
 */
export function DeploymentDependency() {
  const page = useDeploymentPage();
  const navigate = useNavigate();
  const view = page.view;
  const snapshot = page.snapshot;
  // What a send from the chat runs on: it requests changes at the review, and
  // the run that waits there analyses again.
  const runsOn = useRunsOn("deployment", view?.decisionPending ? snapshot?.run : null);

  // Why the phase cannot start again now, or undefined when it can. Starting
  // again closes a review that newer tested code replaced; any other waiting
  // review is decided first. Newer code without approved tests blocks nothing:
  // a run analyses the tested code, which is what may ship.
  const runBlocked = !view
    ? "Reading the phase"
    : view.empty === "not-approved"
      ? "The test review has not approved a run on the generated app yet"
      : view.decisionPending && !view.reviewMovedPast
        ? "Decide the waiting review first"
        : undefined;
  // Which stage the run is working on, and for how long, said in the header; the
  // stages queued behind it say they wait for it.
  const working = snapshot
    ? workingStage(
        DEPLOY_CHROME.ids,
        snapshot.stages,
        snapshot.run?.state === "running" ? snapshot.run.startedAt : null,
      )
    : null;
  const header = (
    <DeploymentHeader
      progress={view?.progress ?? 0}
      isDark={page.isDark}
      canRun={!runBlocked}
      runBlocked={runBlocked}
      running={Boolean(view?.running)}
      version={view?.version ?? 0}
      onRun={page.run}
      targets={page.targets}
      target={page.shownTarget}
      onChooseTarget={page.chooseTarget}
      working={
        working ? { label: DEPLOY_CHROME.meta[working.id].label, since: working.since } : undefined
      }
    />
  );

  // The phase is read before it is rendered: a snapshot that has not arrived is
  // neither an empty phase nor a failed one.
  if (!view || !snapshot) {
    return (
      <div className="tp w-full px-6 pb-10 pt-6 md:px-8 md:pt-8">
        {header}
        {page.loadFailed ? (
          <div className="mt-8">
            <PhaseLoadError onRetry={page.retryLoad} />
          </div>
        ) : (
          <PageLoader label="Loading the deployment" />
        )}
      </div>
    );
  }

  if (view.empty) {
    return (
      <div className="tp w-full px-6 pb-10 pt-6 md:px-8 md:pt-8">
        {header}
        <div className="mt-8">
          {view.empty === "not-approved" ? (
            <PhaseWaitingOnTesting
              projectName={page.project?.name ?? "this project"}
              onOpenTesting={page.openTesting}
            />
          ) : (
            <PhaseNotRun
              onRun={page.run}
              busy={page.pending}
              testVersion={snapshot.approvedTestVersion}
              testedCode={snapshot.approvedTestedCodeVersion}
              currentCode={snapshot.codeVersion}
              targets={page.targets}
              target={page.shownTarget ?? snapshot.releaseTarget}
              onChooseTarget={page.chooseTarget}
              scopePackages={snapshot.scopePackages}
              onChooseScope={page.chooseScope}
              onOpenTesting={page.openTesting}
            />
          )}
        </div>
      </div>
    );
  }

  const stage = page.stage;
  const packageOf = (updateId: string) =>
    view.updates.find((one) => one.updateId === updateId)?.package ?? updateId;
  const attention = view.needDecision + (view.release.awaitingRollback ? 1 : 0);

  return (
    <div className="tp flex h-full w-full min-w-0 overflow-hidden">
      <ConversationDock
        open={page.conversationOpen}
        sheetOpen={page.conversationSheetOpen}
        onSheetOpenChange={page.setConversationSheetOpen}
      >
        <ConversationPanel
          title="Conversation"
          subtitle="Everything the platform did to this phase, oldest first"
          messages={page.conversation}
          focusSignal={page.chatFocusSignal}
          onClose={() => {
            page.setConversationOpen(false);
            page.setConversationSheetOpen(false);
          }}
          composer={{
            placeholder: "Say what needs to change about this release",
            helper: `Deploy version ${view.version}. Sending requests changes at the review and analyses again.`,
            pending: page.pending,
            onSubmit: page.requestChanges,
            // A change request answers the review, and the server refuses one
            // with no review waiting, or at one the code has moved past; saying
            // so beats a refusal after Send.
            unavailable: view.decisionPending
              ? view.reviewMovedPast
                ? reviewMovedPastLine(snapshot)
                : undefined
              : "No review is waiting. Change requests open when the analysis reaches its review.",
            runsOn,
          }}
        />
      </ConversationDock>

      <div
        data-stage-scroller
        className="relative min-w-0 flex-1 overflow-y-auto overscroll-contain px-4 sm:px-6 md:px-8"
      >
        {/* The rail is a direct child of this column, as in Design and Code: a
            sticky element sticks only within its parent, and the div it had to
            itself was exactly its own height, so it scrolled away with it. The
            vertical padding is here rather than on the scrollport, because a
            sticky child pins to the scrollport's padding box. */}
        <div className="space-y-5 py-4 sm:py-6 md:py-8">
          {page.stale && <ReconnectingNotice since={page.lastReadAt} onRetry={page.retryLoad} />}
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 flex-1 basis-[24rem]">{header}</div>
            {!page.conversationOpen && (
              <div className="hidden shrink-0 lg:block">
                <ConversationToggle onOpen={page.openChat} unread={attention} />
              </div>
            )}
            {!page.conversationSheetOpen && (
              <div className="shrink-0 lg:hidden">
                <ConversationToggle onOpen={page.openChat} unread={attention} />
              </div>
            )}
          </div>

          {snapshot.codeMovedOn ? (
            <CodeMovedOnNotice
              analysedCode={snapshot.deployedCodeVersion}
              testedCode={snapshot.approvedTestedCodeVersion}
              reviewWaiting={view.reviewMovedPast}
            />
          ) : (
            view.codeAwaitingTests > 0 && (
              <NewerCodeNotice
                testedCode={snapshot.approvedTestedCodeVersion}
                newerCode={view.codeAwaitingTests}
                onOpenTesting={page.openTesting}
              />
            )
          )}

          {page.stopped && (
            <RunStoppedNotice
              error={page.stopped.error}
              startedAt={page.stopped.startedAt}
              onContinue={page.continueRun}
              stoppedAtLabel={stageLabelIn(DEPLOY_CHROME, page.stopped.stoppedAt)}
              onStartOver={page.run}
              startOverHint="Starting over analyses the updates again and stages a new candidate, as a new deploy version."
            />
          )}

          <StageNav
            chrome={DEPLOY_CHROME}
            steps={DEPLOY_STAGE_IDS.map((id) => ({
              id,
              label: DEPLOY_STAGE_META[id].label,
              status: view.chevrons[id],
            }))}
            activeStage={stage}
            onSelectStage={page.setStage}
            shortcut={
              view.decisionPending
                ? { id: "deployment-review", label: "To the review", title: "Go straight to the review" }
                : null
            }
            narrow={page.conversationOpen}
          />

          <div className="space-y-4">
            <StageShell
              chrome={DEPLOY_CHROME}
              stage={view.stages[stage]}
              stageId={stage}
              version={view.version}
              onRetry={page.retryStage}
              notReached={page.stopped !== null}
              computedBefore={computedBeforeIn(DEPLOY_CHROME, stage, snapshot.stages)}
              waitingFor={
                working && working.id !== stage ? DEPLOY_CHROME.meta[working.id].label : undefined
              }
              opening={stageOpeningNext(DEPLOY_CHROME.ids, snapshot.stages, snapshot.run) === stage}
            >
              {stage === "dependency-updates" && <StageUpdates snapshot={snapshot} />}
              {stage === "changelog-analysis" && <StageChangelog snapshot={snapshot} />}
              {stage === "impact-analysis" && (
                <StageImpact snapshot={snapshot} onJump={page.openRequirement} />
              )}
              {stage === "risk-assessment" && <StageRisk view={view} version={view.version} />}
              {stage === "pipeline-generation" && <StagePipeline snapshot={snapshot} />}
              {stage === "staging-verification" && (
                <StageStaging
                  snapshot={snapshot}
                  view={view}
                  onRetry={() => page.retryStage("staging-verification")}
                  onOpenTesting={() => navigate(`/projects/${snapshot.projectId}/testing`)}
                />
              )}
              {stage === "rollback-planning" && (
                <StageRollbackPlan snapshot={snapshot} packageOf={packageOf} />
              )}
              {stage === "deployment-review" && (
                <StageReview
                  snapshot={snapshot}
                  view={view}
                  targets={page.targets}
                  shownTarget={page.shownTarget ?? snapshot.releaseTarget}
                  busy={page.pending}
                  goAhead={page.goAhead}
                  onGoAhead={page.setGoAhead}
                  onDecideUpdate={page.decideUpdate}
                  onChooseTarget={page.chooseTarget}
                  onChoosePolicy={page.choosePolicy}
                  onOpenStage={page.setStage}
                  onOpenTesting={page.openTesting}
                />
              )}
              {stage === "release" && (
                <StageRelease
                  view={view}
                  busy={page.pending}
                  isDark={page.isDark}
                  onDecideRollback={page.decideRollback}
                  onLoadHistory={page.loadLedger}
                  onReleaseAgain={page.releaseAgain}
                />
              )}
              {stage === "monitoring" && (
                <StageMonitoring
                  view={view}
                  busy={page.pending}
                  watching={page.watching}
                  onWatch={page.watch}
                  onDecideFeedback={page.decideFeedback}
                  onSendFeedback={page.sendFeedback}
                  isDark={page.isDark}
                />
              )}
            </StageShell>
            <StageFooterNav chrome={DEPLOY_CHROME} stageId={stage} onSelectStage={page.setStage} />
          </div>

          {/* A direct child of the stage column, so it sticks to its foot as
              Design's and Code's do: in a box of its own height it had nowhere
              to stick, and sat at the end of every stage. */}
          {view.decisionPending && (
            <DecisionBar
              view={view}
              changesDisabledReason={
                view.reviewMovedPast ? reviewMovedPastLine(snapshot) : undefined
              }
              goAhead={page.goAhead}
              busy={page.pending}
              onApprove={page.approve}
              onRequestChanges={page.requestChanges}
            />
          )}
        </div>
      </div>
    </div>
  );
}

export default DeploymentDependency;
