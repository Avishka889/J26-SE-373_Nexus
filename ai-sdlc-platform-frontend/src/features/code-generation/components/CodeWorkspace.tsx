import { useMemo } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, History, Play } from "lucide-react";
import type { Project } from "@/types/project";
import { useRunsOn } from "@/entities/settings";
import { cn } from "@/shared/utils/cn";
import { useIsDark } from "@/shared/theme";
import { Button } from "@/shared/ui/primitives";
import { PhaseSectionHeader } from "@/shared/ui";
import {
  DecisionBar,
  Note,
  Panel,
  ReconnectingNotice,
  RunStoppedNotice,
  readState,
  stageOpeningNext,
  workingStage,
} from "@/shared/ui/phase";
import { useElapsed } from "@/shared/hooks";
import { ConversationDock, ConversationPanel, ConversationToggle } from "@/shared/ui/conversation";
import {
  StageFooterNav,
  StageNav,
  StageShell,
  computedBeforeIn,
  stageLabelIn,
} from "@/shared/ui/stage";
import { useCodeWorkspace } from "../hooks/useCodeWorkspace";
import { CODE_CHROME, CODE_STAGE_META } from "../model/stages";
import { buildCodeConversation } from "../model/conversation";
import { StageSprintScope } from "./stages/StageSprintScope";
import { StageTechStack } from "./stages/StageTechStack";
import { StageApiContract } from "./stages/StageApiContract";
import { CodeStudio } from "./CodeStudio";
import { StageContractAgreement } from "./stages/StageContractAgreement";
import { StageBuild } from "./stages/StageBuild";
import { StageCodeReview } from "./stages/StageCodeReview";
import { FileViewer } from "./FileViewer";
import { PreviewPanel } from "./PreviewPanel";
import { PageLoader, Spinner } from "@/shared/ui/Spinner";
import { messageOf } from "@/lib/http";
import { ServerUnavailable } from "@/shared/ui/ServerUnavailable";
import { ConfirmDialog } from "@/shared/ui/ConfirmDialog";
import { codeConcerns } from "../model/gate";
import { reviewMovedPastLine } from "../model/outdated";
import { inferredBy } from "../model/arms";

/**
 * The Code Generation phase.
 *
 * The Requirements and Design layout, because it is the same kind of thing: a
 * gated phase whose artefacts are read, corrected and then approved once. The
 * chrome is literally shared, so a reader who has learned one phase has
 * learned both.
 *
 * Two things are this phase's own. Generation is explicit, because a run costs
 * minutes and money and nothing should start one by being navigated to. And
 * the header carries a second version: the design this code was generated
 * from, which can move on underneath it.
 */
export function CodeWorkspace({ project }: { project: Project }) {
  const isDark = useIsDark();
  const page = useCodeWorkspace(project);
  const { snapshot, progress, status } = page;
  // What a send from the chat runs on: it requests changes at the review, and
  // they regenerate the run that waits there.
  const runsOn = useRunsOn("code", status.gateWaiting ? snapshot?.run : null);
  // How long the stage the run is working on has been going, said in the
  // header; the stages queued behind it say they wait for it.
  const working = snapshot
    ? workingStage(
        CODE_CHROME.ids,
        snapshot.stages,
        snapshot.run?.state === "running" ? snapshot.run.startedAt : null,
      )
    : null;
  const workingFor = useElapsed(working?.since);
  const soFar = workingFor ? `, ${workingFor} so far` : "";

  const conversation = useMemo(
    () =>
      snapshot
        ? buildCodeConversation({ snapshot, onOpenStage: page.setSelectedStage })
        : [],
    [snapshot, page.setSelectedStage],
  );

  // Only a first read that failed replaces the workspace. A later poll that
  // fails keeps what is shown, and whatever is being typed in it, and says the
  // page may be out of date (the notice at the top of the stage column).
  if (readState(page.query) === "failed") {
    return (
      <div className="tp w-full p-4 sm:p-6 md:p-8">
        <ServerUnavailable
          title="This code could not be loaded"
          message={messageOf(page.query.error)}
          onRetry={() => page.query.refetch()}
        />
      </div>
    );
  }

  if (!snapshot) {
    return (
      <div className="tp w-full space-y-5 p-4 sm:p-6 md:p-8">
        <PageLoader label="Loading the code" />
      </div>
    );
  }

  const activeStage = page.selectedStage;
  const { generatingStageId, gateWaiting, notStarted } = status;

  return (
    <div className="tp flex h-full w-full min-w-0 overflow-hidden">
      <ConversationDock
        open={page.conversationOpen}
        sheetOpen={page.conversationSheetOpen}
        onSheetOpenChange={page.setConversationSheetOpen}
      >
        <ConversationPanel
          title="Conversation"
          subtitle="Everything the platform did to this code, oldest first"
          messages={conversation}
          focusSignal={page.chatFocusSignal}
          onClose={() => {
            page.setConversationOpen(false);
            page.setConversationSheetOpen(false);
          }}
          composer={{
            placeholder: "Say what needs to change about this code",
            helper: `Code version ${snapshot.codeVersion}. Sending requests changes at the review and regenerates.`,
            pending: page.mutations.submitDecision.isPending,
            onSubmit: page.requestChanges,
            // A change request answers the review, and the server refuses one
            // with no review waiting, or at one the design has moved past;
            // saying so beats a refusal after Send.
            unavailable: gateWaiting
              ? status.reviewMovedPast
                ? reviewMovedPastLine(snapshot)
                : undefined
              : "No review is waiting. Change requests open when the code reaches its review.",
            runsOn,
          }}
        />
      </ConversationDock>

      <div
        data-stage-scroller
        className="relative min-w-0 flex-1 overflow-y-auto overscroll-contain px-4 sm:px-6 md:px-8"
      >
        <div className="space-y-5 py-4 sm:py-6 md:py-8">
          {readState(page.query) === "stale" && (
            <ReconnectingNotice
              since={page.query.dataUpdatedAt}
              onRetry={() => void page.query.refetch()}
            />
          )}
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 flex-1 basis-[24rem]">
              <PhaseSectionHeader
                title="Code Generation"
                subtitle={
                  generatingStageId
                    ? `Generating ${CODE_STAGE_META[generatingStageId].label} from the contract${soFar}`
                    : notStarted
                      ? "Nothing has been generated yet. Generation starts when you ask for it."
                      : "Read what was generated, check it agrees with the contract, then approve it once."
                }
                progress={progress.percent}
                valueLabel={progress.valueLabel}
                isDark={isDark}
              />
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {status.canGenerate && !status.isGenerating && (
                <Button
                  variant="primary"
                  size="sm"
                  // The window this closes: the button stays visible until the
                  // snapshot comes back with the stages flipped to generating,
                  // and a second click in that gap starts a second request.
                  busy={page.mutations.generate.isPending}
                  onClick={page.generate}
                >
                  {!page.mutations.generate.isPending && <Play className="h-3.5 w-3.5" />}
                  {page.mutations.generate.isPending
                    ? "Starting"
                    : notStarted
                      ? "Generate code"
                      : "Generate again"}
                </Button>
              )}
              {!page.conversationOpen && (
                <div className="hidden lg:block">
                  {/* No badge: it counted agreement errors, which are not in the
                      conversation; Contract Agreement's chevron carries them. */}
                  <ConversationToggle onOpen={page.openChat} />
                </div>
              )}
              {!page.conversationSheetOpen && (
                <div className="lg:hidden">
                  <ConversationToggle onOpen={page.openChat} />
                </div>
              )}
            </div>
          </div>

          {status.designBlocker && !status.isGenerating && (
            <Panel
              label={notStarted ? "This phase has not started" : "Code waits for the design"}
              icon={<AlertTriangle className="h-4 w-4" />}
            >
              <Note>
                Code is generated from the approved design, so nothing starts here until it is:{" "}
                {status.designBlocker}.
              </Note>
            </Panel>
          )}

          {page.githubConnected === false && status.canGenerate && !status.isGenerating && (
            // Said before the run, not after: the build recorded "not pushed"
            // only once a run had been paid for.
            <Note className="rounded-xl border border-amber-500/30 bg-amber-500/5 px-3.5 py-2.5">
              GitHub is not connected, so the code a run generates is not pushed anywhere.{" "}
              <Link to="/settings?tab=git" className="text-blue-700 underline dark:text-blue-300">
                Connect GitHub in Settings
              </Link>{" "}
              first, or download the code from Build afterwards and push it later from there.
            </Note>
          )}

          {status.designMovedOn && (
            <section className="overflow-hidden rounded-2xl border border-amber-500/30 bg-amber-500/5">
              <div className="flex flex-wrap items-start gap-3 px-4 py-3.5">
                <History className="mt-0.5 h-4 w-4 shrink-0 text-amber-500 dark:text-amber-400" />
                <div className="min-w-0 flex-1">
                  <p className="text-[13px] font-semibold text-[color:var(--tp-ink)]">
                    This code was generated from design version{" "}
                    {snapshot.generatedFromDesignVersion}, and the design is now at{" "}
                    {snapshot.designVersion}
                  </p>
                  <Note className="mt-1">
                    Everything below still describes the older design. It is kept so nothing
                    disappears; generating again reads the newer one.
                  </Note>
                </div>
              </div>
            </section>
          )}

          {page.stopped && (
            <RunStoppedNotice
              error={page.stopped.error}
              startedAt={page.stopped.startedAt}
              onContinue={page.continueRun}
              stoppedAtLabel={stageLabelIn(CODE_CHROME, page.stopped.stoppedAt)}
              onStartOver={page.generate}
              busy={page.mutations.generate.isPending}
              startOverHint="Starting over generates the code again from the approved design, as a new code version."
            />
          )}

          <StageNav
            chrome={CODE_CHROME}
            steps={page.stageSteps}
            activeStage={activeStage}
            onSelectStage={page.setSelectedStage}
            shortcut={
              status.everythingGenerated
                ? { id: "code-review", label: "To the review", title: "Go straight to the review" }
                : null
            }
            narrow={page.conversationOpen}
          />

          <StageShell
            chrome={CODE_CHROME}
            stage={snapshot.stages[activeStage]}
            stageId={activeStage}
            version={snapshot.codeVersion}
            onRetry={page.retryStage}
            notReached={page.stopped !== null}
            computedBefore={computedBeforeIn(CODE_CHROME, activeStage, snapshot.stages)}
            waitingFor={
              working && working.id !== activeStage ? CODE_STAGE_META[working.id].label : undefined
            }
            opening={stageOpeningNext(CODE_CHROME.ids, snapshot.stages, snapshot.run) === activeStage}
          >
            {activeStage === "sprint-scope" && (
              <StageSprintScope
                snapshot={snapshot}
                onToggle={page.setStoryScope}
                onPlanNextSprint={page.planNextSprint}
                // To the screens themselves, on the design page: it opened API
                // Contract, which does not show them.
                onOpenScreens={(screenIds) => screenIds[0] && page.openScreen(screenIds[0])}
                onOpenRequirement={page.openRequirement}
                busy={
                  page.mutations.setStoryScope.isPending ||
                  page.mutations.planNextSprint.isPending ||
                  status.isGenerating
                }
                planning={page.mutations.planNextSprint.isPending}
                reviewOpen={gateWaiting}
              />
            )}
            {activeStage === "tech-stack" && (
              <StageTechStack
                snapshot={snapshot}
                onSelect={page.selectStack}
                busy={page.mutations.selectStack.isPending}
              />
            )}
            {activeStage === "api-contract" && (
              <StageApiContract
                snapshot={snapshot}
                onChooseArm={page.chooseArm}
                onJumpToScreen={page.openScreen}
                onOpenRequirement={page.openRequirement}
                onDownloadOpenApi={page.downloadOpenApi}
                busy={page.mutations.chooseArm.isPending || status.isGenerating}
              />
            )}
            {activeStage === "frontend-code" && (
              <CodeStudio
                projectId={project.id}
                snapshot={snapshot}
                sectionId="frontend-files"
                stages={["frontend-code", "build"]}
                emptyLine="The frontend stage produced no files. Its own panel above says why."
              />
            )}
            {activeStage === "backend-code" && (
              <CodeStudio
                projectId={project.id}
                snapshot={snapshot}
                sectionId="backend-files"
                stages={["backend-code"]}
                emptyLine="The backend stage produced no files. Its own panel above says why."
              />
            )}
            {activeStage === "contract-agreement" && (
              <StageContractAgreement
                snapshot={snapshot}
                onOpenLocation={(path, line) => page.setOpenFile({ path, line })}
              />
            )}
            {activeStage === "build" && (
              <StageBuild
                snapshot={snapshot}
                approved={
                  snapshot.gate.decision?.kind === "approved" || Boolean(snapshot.approvedThrough)
                }
                githubConnected={page.githubConnected}
                onPush={page.pushVersion}
                onDownload={page.downloadArchive}
                onBuildAgain={() => page.retryStage("build")}
                preview={
                  <PreviewPanel
                    projectId={project.id}
                    snapshot={snapshot}
                    buildPassed={status.buildPassed}
                  />
                }
              />
            )}
            {activeStage === "code-review" && (
              <StageCodeReview
                projectId={project.id}
                snapshot={snapshot}
                onOpenStage={page.setSelectedStage}
                onContinue={page.continueToTesting}
              />
            )}

            <StageFooterNav
              chrome={CODE_CHROME}
              stageId={activeStage}
              onSelectStage={page.setSelectedStage}
            />
          </StageShell>

          {page.supersede.ask && (
            <ConfirmDialog
              title={`Replace approved code version ${page.supersede.ask.version}?`}
              body={`Code version ${page.supersede.ask.version} is approved. A new version replaces it: Testing and Deployment start again from the new one, and their approvals no longer cover the code that runs. Generating runs the model again.`}
              confirmLabel={`Start code version ${page.supersede.ask.version + 1}`}
              isDark={isDark}
              onConfirm={page.supersede.confirm}
              onCancel={page.supersede.cancel}
            />
          )}

          {gateWaiting && (
            <DecisionBar
              busy={page.mutations.submitDecision.isPending}
              headline="This phase is waiting on you"
              detail={[
                `Code version ${snapshot.codeVersion}`,
                `${snapshot.contract?.contract.endpoints.length ?? 0} endpoints, ${inferredBy(
                  snapshot.contract?.chosen ?? "rule",
                )}`,
                ...(codeConcerns(snapshot).length === 0
                  ? ["the build passed", "the code and the contract agree"]
                  : []),
              ].join(" · ")}
              concerns={codeConcerns(snapshot)}
              approveLabel="Approve code"
              // Neither decision helps at a review the design moved past, and the
              // server refuses both: generating again closes it.
              approveDisabled={status.reviewMovedPast}
              approveDisabledReason={
                status.reviewMovedPast ? reviewMovedPastLine(snapshot) : undefined
              }
              changesDisabledReason={
                status.reviewMovedPast ? reviewMovedPastLine(snapshot) : undefined
              }
              notePrompt="What needs to change before this code is right"
              notePlaceholder="Split the order endpoints so cancelling is not a delete."
              onApprove={async (note) => {
                await page.approveCode(note);
                page.setSelectedStage("code-review");
              }}
              onRequestChanges={async (note) => {
                await page.requestChanges(note);
                page.setSelectedStage("code-review");
              }}
            />
          )}

          {generatingStageId && (
            <div
              className={cn(
                "fixed bottom-6 left-1/2 z-30 flex -translate-x-1/2 items-center gap-3 rounded-2xl border px-4 py-3 shadow-2xl",
                isDark ? "border-white/10 bg-[#0f1d32]" : "border-slate-200 bg-white",
              )}
            >
              <Spinner size="sm" tone="accent" decorative />
              <span
                className={cn(
                  "text-sm font-medium",
                  isDark ? "text-slate-200" : "text-slate-700",
                )}
              >
                Generating {CODE_STAGE_META[generatingStageId].label}
                {soFar}
              </span>
            </div>
          )}
        </div>
      </div>

      {page.openFile && (
        <FileViewer
          projectId={project.id}
          path={page.openFile.path}
          line={page.openFile.line}
          version={snapshot.codeVersion}
          onClose={() => page.setOpenFile(null)}
        />
      )}
    </div>
  );
}
