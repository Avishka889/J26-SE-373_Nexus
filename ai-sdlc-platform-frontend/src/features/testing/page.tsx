import {
  ConversationDock,
  ConversationPanel,
  ConversationToggle,
} from "@/shared/ui/conversation";
import {
  StageFooterNav,
  StageNav,
  StageSection,
  StageShell,
  computedBeforeIn,
  stageLabelIn,
} from "@/shared/ui/stage";
import { useRunsOn } from "@/entities/settings";
import { PageLoader } from "@/shared/ui/Spinner";
import { DecisionBar } from "./components/DecisionBar";
import { PhaseLoadError, PhaseNotStarted } from "./components/EmptyStates";
import { SummaryStrip } from "./components/PhaseChrome";
import { TestingHeader } from "./components/TestingHeader";
import { StepGeneration } from "./components/steps/StepGeneration";
import { StepHealing } from "./components/steps/StepHealing";
import { StepQuality } from "./components/steps/StepQuality";
import { StepReport } from "./components/steps/StepReport";
import { StepReverify } from "./components/steps/StepReverify";
import { StepSecurity } from "./components/steps/StepSecurity";
import { StepTests } from "./components/steps/StepTests";
import { useTestingPage } from "./hooks";
import { attentionShortcut, progressLabel } from "./model/rail";
import { testChromeFor } from "./model/stages";
import { reviewMovedPastLine } from "./model/view";
import { ReconnectingNotice, RunStoppedNotice, workingStage } from "@/shared/ui/phase";

/**
 * The testing phase, on the chrome every gated phase uses.
 *
 * It had its own before: its own stepper, its own six step ids over the
 * contract's seven stages, and no anchor pills. That is why neither the narrow
 * width sweep nor the section anchor sweep could reach it, both of which drive
 * `[data-stage-rail]`, and why a stage the server reported could have nowhere
 * on screen to report anything.
 */
export function TestingSecurity() {
  const page = useTestingPage();
  const view = page.view;
  // What a send from the chat runs on: it requests changes at the review, and
  // they run again in the run that waits there.
  const runsOn = useRunsOn("testing", view?.decisionPending ? page.snapshot?.run : null);
  const chrome = testChromeFor(Boolean(page.detectorComparison));

  // The phase is read before it is rendered. A snapshot that has not arrived is
  // not an empty phase and not a failed one, and drawing either would tell the
  // reader something that is not known yet.
  if (!view) {
    return (
      <div className="tp w-full px-6 pb-10 pt-6 md:px-8 md:pt-8">
        <TestingHeader progress={0} isDark={page.isDark} running={false} />
        {page.loadError ? (
          // A first read that failed has no snapshot, so it said "Loading the
          // tests" for ever; the reason, and a retry that only reads, instead.
          <div className="mt-8">
            <PhaseLoadError message={page.loadError} onRetry={page.retryLoad} />
          </div>
        ) : (
          <PageLoader label="Loading the tests" />
        )}
      </div>
    );
  }

  if (page.effective === "empty" || page.effective === "error") {
    return (
      <div className="tp w-full px-6 pb-10 pt-6 md:px-8 md:pt-8">
        {/* No run button: the empty phase offers its own start, and a failed
            read has nothing to run again. */}
        <TestingHeader progress={view.progress} isDark={page.isDark} running={page.running} />
        <div className="mt-8">
          {page.effective === "empty" ? (
            <PhaseNotStarted
              projectName={page.project?.name ?? "this project"}
              codeApproved={page.codeApproved}
              running={page.running}
              onOpenCode={page.openCode}
              onRun={page.startRerun}
            />
          ) : (
            <PhaseLoadError message={page.loadError} onRetry={page.retryLoad} />
          )}
        </div>
      </div>
    );
  }

  const activeStage = page.step;
  // Which stage the run is working on, and for how long, said in the header; the
  // stages queued behind it say they wait for it.
  const working = workingStage(
    chrome.ids,
    page.snapshot?.stages ?? {},
    page.snapshot?.run?.state === "running" ? page.snapshot.run.startedAt : null,
  );
  const stage = page.snapshot?.stages[activeStage] ?? {
    status: "pending" as const,
    generatedFromVersion: 0,
  };

  return (
    <div className="tp flex h-full w-full min-w-0 overflow-hidden">
      <ConversationDock
        open={page.conversationOpen}
        sheetOpen={page.conversationSheetOpen}
        onSheetOpenChange={page.setConversationSheetOpen}
      >
        <ConversationPanel
          title="Conversation"
          subtitle="What each stage did and what was decided, oldest first"
          messages={page.conversation}
          focusSignal={page.chatFocusSignal}
          onClose={() => {
            page.setConversationOpen(false);
            page.setConversationSheetOpen(false);
          }}
          composer={{
            // Nothing reads the note. The tests are written again from the
            // criteria and the contract, so the box says what sending does and
            // not "say what needs to change", which it could not act on.
            placeholder: "Why the tests should run again",
            // Short, so the half that matters is not the half cut off.
            helper: `Runs again as test version ${view.build + 1}. The note does not steer the tests.`,
            pending: page.requestPending,
            onSubmit: page.requestChanges,
            // A change request answers the review, and the server refuses one
            // with no review waiting, or at one the code has moved past; saying
            // so beats a refusal after Send.
            unavailable: view.decisionPending
              ? undefined
              : view.reviewMovedPast && page.snapshot
                ? reviewMovedPastLine(page.snapshot)
                : "No review is waiting. Change requests open when the tests reach their review.",
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
            <div className="min-w-0 flex-1 basis-[24rem]">
              <TestingHeader
                progress={view.progress}
                progressLabel={progressLabel(view)}
                isDark={page.isDark}
                running={page.running}
                onRerun={page.startRerun}
                rerunBlocked={
                  view.decisionPending
                    ? "A review is waiting on this run: decide it first, or request changes."
                    : undefined
                }
                // Only a full run in progress: during a stage retry the newest
                // full run is an older one, and its age is not this wait.
                runningSince={
                  page.snapshot?.run?.state === "running" ? page.snapshot.run.startedAt : null
                }
                working={
                  working
                    ? { label: chrome.meta[working.id].label, since: working.since }
                    : undefined
                }
                target={page.snapshot?.target}
                targets={page.targets}
                onChooseTarget={page.chooseTarget}
              />
            </div>
            {!page.conversationOpen && (
              <div className="hidden shrink-0 lg:block">
                <ConversationToggle onOpen={page.openChat} />
              </div>
            )}
            {!page.conversationSheetOpen && (
              <div className="shrink-0 lg:hidden">
                <ConversationToggle onOpen={page.openChat} />
              </div>
            )}
          </div>

          {page.stopped && (
            <RunStoppedNotice
              error={page.stopped.error}
              startedAt={page.stopped.startedAt}
              onContinue={page.continueRun}
              stoppedAtLabel={stageLabelIn(chrome, page.stopped.stoppedAt)}
              onStartOver={page.startRerun}
              startOverHint="Starting over runs the tests again on the current code, as a new test version."
            />
          )}

          <StageNav
            chrome={chrome}
            steps={page.stepperSteps}
            activeStage={activeStage}
            onSelectStage={page.setStep}
            // To what waits on a person first, and to the review when
            // nothing does: the review cannot be decided while a failure waits.
            shortcut={
              attentionShortcut(view) ??
              (view.decisionPending
                ? {
                    id: "test-review",
                    label: "To the review",
                    title: "Go straight to the review",
                  }
                : null)
            }
            narrow={page.conversationOpen}
          />

          <div>
            <StageShell
              chrome={chrome}
              stage={stage}
              stageId={activeStage}
              version={view.build}
              onRetry={page.retryStageById}
              notReached={page.stopped !== null}
              waitingFor={
                working && working.id !== activeStage ? chrome.meta[working.id].label : undefined
              }
              computedBefore={
                page.snapshot
                  ? computedBeforeIn(chrome, activeStage, page.snapshot.stages)
                  : undefined
              }
            >
              {activeStage === "test-generation" && (
                <StepGeneration view={view} />
              )}

              {activeStage === "test-run" && (
                <div className="space-y-4">
                  <StageSection id="run-summary">
                    <SummaryStrip view={view} onGoTo={page.goToFromSummary} />
                  </StageSection>
                  {/* Its sections are its own: results, transcript, test files. */}
                  <StepTests
                      view={view}
                      testFiles={page.testFiles}
                      testFileMeta={page.testFileMeta}
                      testFileContents={page.testFileContents}
                      caption={page.testsCaption}
                      onGoTo={page.setStep}
                      onOpenFailure={page.openFailure}
                      tabs={page.tabs}
                      activePath={page.activePath}
                      highlight={page.highlight}
                      onSelectFile={page.selectFile}
                      onSelectTab={page.selectTab}
                      onCloseTab={page.closeTab}
                      viewerRef={page.viewerRef}
                    />
                </div>
              )}

              {activeStage === "test-quality" && <StepQuality view={view} />}

              {activeStage === "self-healing" && (
                <StepHealing
                  view={view}
                  filter={page.inboxFilter}
                  onFilter={page.setInboxFilter}
                  selectedId={page.selectedFailure}
                  onSelect={page.setSelectedFailure}
                  onApprove={page.approveRepair}
                  onReject={page.rejectRepair}
                  onDecideTest={page.decideTest}
                  onOpenFile={page.openFileAt}
                  onOpenCode={page.openCode}
                />
              )}

              {activeStage === "security-scan" && (
                <StepSecurity
                  view={view}
                  severityOrder={page.severityOrder}
                  detectorComparison={page.detectorComparison}
                  expandedId={page.expandedFinding}
                  onExpand={page.setExpandedFinding}
                  onApplyFix={page.applyFix}
                  onDismiss={page.dismissFinding}
                  onAccept={page.acceptFinding}
                  onGoTo={page.setStep}
                />
              )}

              {activeStage === "remediation" && (
                <StepReverify
                  view={view}
                  onGoTo={page.setStep}
                  onRetry={page.retryProofs}
                  onReverify={page.reverifyFix}
                />
              )}

              {activeStage === "test-review" && (
                <StepReport
                  view={view}
                  run={page.testingRun}
                  decisionChain={page.decisionChain}
                  onGoTo={page.setStep}
                  onOpenDeployment={page.openDeployment}
                  onOpenActivity={page.openActivity}
                  onRollback={page.rollback}
                />
              )}
            </StageShell>
            <StageFooterNav
              chrome={chrome}
              stageId={activeStage}
              onSelectStage={page.setStep}
            />
          </div>

          {/* A direct child of this column, as the rail is and for the rail's
              reason: a sticky element sticks only within its parent, and in a
              box of its own it sat at the end of every stage. */}
          {view.decisionPending && (
            <DecisionBar
              view={view}
              onApprove={page.approvePhase}
              onRequestChanges={page.requestChanges}
              onOpenStage={page.setStep}
              busy={page.requestPending}
            />
          )}
        </div>
      </div>
    </div>
  );
}

export default TestingSecurity;
