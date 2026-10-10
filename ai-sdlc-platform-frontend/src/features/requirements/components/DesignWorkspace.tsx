import type { Project } from "@/types/project";
import { useRunsOn } from "@/entities/settings";
import { cn } from "@/shared/utils/cn";
import { useIsDark } from "@/shared/theme";
import { PhaseSectionHeader } from "@/shared/ui";
import { useElapsed } from "@/shared/hooks";
import {
  DecisionBar,
  ReconnectingNotice,
  RunStoppedNotice,
  readState,
  workingStage,
} from "@/shared/ui/phase";
import { useDesignWorkspace } from "../hooks/useDesignWorkspace";
import { STAGE_META } from "../model/stages";
import {
  ConversationDock,
  ConversationPanel,
  ConversationToggle,
} from "@/shared/ui/conversation";
import {
  StageFooterNav,
  StageNav,
  StageShell,
  computedBeforeIn,
  stageLabelIn,
} from "@/shared/ui/stage";
import { StageRequirements } from "./stages/StageRequirements";
import { StageDomainModel } from "./stages/StageDomainModel";
import { StageArchitectureGraph } from "./stages/StageArchitectureGraph";
import { StageArchitectureChoice } from "./stages/StageArchitectureChoice";
import { StageUml } from "./stages/StageUml";
import { StageWireframes } from "./stages/StageWireframes";
import { StageSprintPlan } from "./stages/StageSprintPlan";
import { StageDesignReview } from "./stages/StageDesignReview";
import { DESIGN_CHROME } from "../model/chrome";
import { questionsLine } from "../model/questions";
import { PageLoader, Spinner } from "@/shared/ui/Spinner";
import { messageOf } from "@/lib/http";
import { ServerUnavailable } from "@/shared/ui/ServerUnavailable";
import { composerHelper, composerSends, queuedLine } from "../model/composer";
import { approvalBlocker, designConcerns, unappliedAnswers } from "../model/gate";

/**
 * The Requirements and Design phase.
 *
 * `tp` on the root is deliberate: the shared phase chrome is styled from the
 * `--tp-*` tokens, which only resolve inside that class. The Testing phase does
 * the same, so both phases now share one set of surfaces and one focus style.
 */
export function DesignWorkspace({ project }: { project: Project }) {
  const isDark = useIsDark();
  const page = useDesignWorkspace(project);
  const { snapshot, domain, progress, status } = page;
  // What a send from the chat runs on. A request for changes regenerates the
  // run that waits at the review; a change note starts a run of its own.
  const runsOn = useRunsOn(
    "design",
    snapshot && composerSends(snapshot) === "request-changes" ? snapshot.run : null,
  );
  // How long the stage the run is working on has been going, said in the
  // header; the stages queued behind it say they wait for it.
  const working = snapshot
    ? workingStage(
        DESIGN_CHROME.ids,
        snapshot.stages,
        snapshot.run?.state === "running" ? snapshot.run.startedAt : null,
      )
    : null;
  const workingFor = useElapsed(working?.since);

  // Only a first read that failed replaces the workspace. A later poll that
  // fails keeps what is shown, and whatever is being typed in it, and says the
  // page may be out of date (the notice at the top of the stage column).
  if (readState(page.query) === "failed") {
    return (
      <div className="tp w-full p-4 sm:p-6 md:p-8">
        <ServerUnavailable
          title="This design could not be loaded"
          message={messageOf(page.query.error)}
          onRetry={() => page.query.refetch()}
        />
      </div>
    );
  }

  if (!snapshot || !domain) {
    return (
      <div className="tp w-full space-y-5 p-4 sm:p-6 md:p-8">
        <PageLoader label="Loading the design" />
      </div>
    );
  }

  const activeStage = page.selectedStage;
  const { gateWaiting, openQuestions, generatingStageId } = status;

  return (
    // The fixed height region. Everything above it is chrome that stays put;
    // the two columns below fill it and each does its own scrolling.
    <div className="tp flex h-full w-full min-w-0 overflow-hidden">
      {/* Chat on one side, the work on the other. The panel is a sibling of the
          stage content rather than a floating overlay, so the artifact keeps a
          real column and nothing is covered up. */}
      <ConversationDock
        open={page.conversationOpen}
        sheetOpen={page.conversationSheetOpen}
        onSheetOpenChange={page.setConversationSheetOpen}
      >
        <ConversationPanel
          title="Conversation"
          subtitle="Everything said about these requirements, oldest first"
          messages={page.conversation}
          focusSignal={page.chatFocusSignal}
          onClose={() => {
            // Whichever surface is showing: the desk preference, and the sheet.
            page.setConversationOpen(false);
            page.setConversationSheetOpen(false);
          }}
          composer={{
            placeholder: "Add a change or a clarification",
            helper: composerHelper(snapshot),
            pending:
              page.mutations.submitChange.isPending || page.mutations.submitGateDecision.isPending,
            onSubmit: page.sendFromChat,
            runsOn,
          }}
        />
      </ConversationDock>

      {/* The stage column is the scroller now, not the page. overscroll-contain
          so reaching its end does not hand the wheel to anything outside. */}
      {/* The vertical padding belongs inside, not on the scrollport. A sticky
          child pins to the scrollport's padding box, so padding here made the
          stage rail stop 32px down and let the header scroll visibly through the
          strip above it. Horizontal padding stays: the rail bleeds through it
          with negative margins on purpose. */}
      {/* `relative`, load bearing: sr-only spans inside the stages are
          position:absolute, so without a positioned ancestor here their
          containing block is the app shell root. That inflated the root's
          scrollHeight to the full stage list and handed <main> a scrollbar it
          must never have, so clicking a stage scrolled the project header and
          the phase tabs off the top. The scrollport owns its own overflow. */}
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
            {/* A floor, not just a share. `flex-1 min-w-0` alone let this column be
            squeezed to whatever the buttons left over, and beside them at around
            900px that was narrow enough to break "Requirements and Design" across
            three lines and put the subtitle one word per line. The basis makes the
            row wrap the buttons underneath instead once the header would go below
            it, which is the right trade: the title is the thing being read. */}
            <div className="min-w-0 flex-1 basis-[24rem]">
              <PhaseSectionHeader
                title="Requirements and Design"
                subtitle={
                  snapshot.questionsPending
                    ? questionsLine(openQuestions)
                    : generatingStageId
                      ? `Generating ${STAGE_META[generatingStageId].label} from your requirements${workingFor ? `, ${workingFor} so far` : ""}`
                      : "Read the design, correct anything that is wrong, then approve it once."
                }
                progress={progress.percent}
                valueLabel={progress.valueLabel}
                isDark={isDark}
              />
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {/* Beside the header rather than inside the stage row: sharing that row
              cost it one chevron, and the one that fell off the end was always
              Design Review. */}
              {status.everythingGenerated &&
                activeStage !== "design-review" && (
                  <button
                    type="button"
                    onClick={() => page.setSelectedStage("design-review")}
                    className="hidden rounded-xl border border-[color:var(--tp-line-strong)] px-3 py-2 text-[12.5px] font-medium text-[color:var(--tp-ink-2)] transition-colors hover:border-blue-500/50 hover:text-blue-600 sm:block"
                  >
                    Go straight to the review
                  </button>
                )}
              {/* Two toggles, one per surface: the desk column follows the
                  remembered preference, the phone sheet starts closed every
                  visit, so below lg the way in must not depend on it. */}
              {!page.conversationOpen && (
                <div className="hidden lg:block">
                  <ConversationToggle
                    onOpen={page.openChat}
                    unread={openQuestions}
                  />
                </div>
              )}
              {!page.conversationSheetOpen && (
                <div className="lg:hidden">
                  <ConversationToggle
                    onOpen={page.openChat}
                    unread={openQuestions}
                  />
                </div>
              )}
            </div>
          </div>

          {page.stopped && (
            <RunStoppedNotice
              error={page.stopped.error}
              startedAt={page.stopped.startedAt}
              onContinue={page.continueRun}
              stoppedAtLabel={stageLabelIn(DESIGN_CHROME, page.stopped.stoppedAt)}
              onStartOver={page.startOver}
              startOverHint="Starting over generates every design stage again at this version."
            />
          )}

          <StageNav
            chrome={DESIGN_CHROME}
            steps={page.stageSteps}
            activeStage={activeStage}
            onSelectStage={page.setSelectedStage}
            shortcut={
              status.everythingGenerated
                ? {
                    id: "design-review",
                    label: "To the review",
                    title: "Go straight to the review",
                  }
                : null
            }
            narrow={page.conversationOpen}
          />

          {
            <StageShell
              chrome={DESIGN_CHROME}
              stage={snapshot.stages[activeStage]}
              stageId={activeStage}
              version={snapshot.requirementsVersion}
              onRetry={page.retryStage}
              notReached={page.stopped !== null}
              computedBefore={computedBeforeIn(DESIGN_CHROME, activeStage, snapshot.stages)}
              waitingFor={
                working && working.id !== activeStage ? STAGE_META[working.id].label : undefined
              }
              pendingNote={
                snapshot.questionsPending
                  ? "This stage starts once you continue from the design's questions, with your answers or with the assumptions."
                  : undefined
              }
            >
              {activeStage === "requirements" && (
                <StageRequirements
                  snapshot={snapshot}
                  mutations={page.mutations}
                  focusedRequirementId={page.focusedRequirementId}
                  onClearFocus={page.clearFocus}
                  onJump={page.jumpToRequirement}
                  onOpenChat={page.openChat}
                  onContinueWithAnswers={page.continueWithAnswers}
                  onContinueWithAssumptions={page.continueWithAssumptions}
                />
              )}

              {activeStage === "domain-model" && (
                <StageDomainModel
                  domain={domain}
                  onJump={page.jumpToRequirement}
                />
              )}

              {activeStage === "architecture-graph" && (
                <StageArchitectureGraph
                  snapshot={snapshot}
                  isDark={isDark}
                  onJump={page.jumpToRequirement}
                  onRename={(nodeId, label) =>
                    page.mutations.renameGraphNode.mutateAsync({ nodeId, label })
                  }
                />
              )}

              {activeStage === "architecture-recommendation" && (
                <StageArchitectureChoice
                  architecture={snapshot.architecture}
                  reviewer={page.reviewer}
                  isSelecting={page.mutations.selectArchitecture.isPending}
                  // Returned, so the chosen candidate's button stays busy until
                  // the server answers; a refusal is reported by the mutation cache.
                  onSelect={(candidateId) =>
                    page.mutations.selectArchitecture
                      .mutateAsync({ candidateId, by: page.reviewer })
                      .catch(() => undefined)
                  }
                />
              )}

              {activeStage === "uml-diagrams" && (
                <StageUml
                  snapshot={snapshot}
                  domain={domain}
                  projectName={project.name}
                  isDark={isDark}
                  onJump={page.jumpToRequirement}
                />
              )}

              {activeStage === "wireframes" && (
                <StageWireframes
                  snapshot={snapshot}
                  projectName={project.name}
                  isDark={isDark}
                  onJump={page.jumpToRequirement}
                  onRequestRefinement={(flowId, note) =>
                    page.mutations.requestRefinement.mutateAsync({ flowId, note })
                  }
                  linkedScreenId={page.linkedScreenId}
                />
              )}

              {activeStage === "sprint-plan" && (
                <StageSprintPlan
                  sprint={snapshot.sprint}
                  version={snapshot.requirementsVersion}
                  onJump={page.jumpToRequirement}
                />
              )}

              {activeStage === "design-review" && (
                <StageDesignReview
                  snapshot={snapshot}
                  domain={domain}
                  onGoToStage={page.setSelectedStage}
                  onJump={page.jumpToRequirement}
                  onContinue={() => void page.continueToCodeGeneration()}
                  onOpenChat={page.openChat}
                  onApplyAnswers={page.applyAnswers}
                  applying={page.mutations.applyAnswers.isPending}
                />
              )}

              <StageFooterNav
                chrome={DESIGN_CHROME}
                stageId={activeStage}
                onSelectStage={page.setSelectedStage}
              />
            </StageShell>
          }

          {gateWaiting && (
            <DecisionBar
              busy={page.mutations.submitGateDecision.isPending}
              headline="This phase is waiting on you"
              detail={[
                `Requirements version ${snapshot.requirementsVersion}`,
                ...(queuedLine(snapshot) ? [queuedLine(snapshot) as string] : []),
                snapshot.architecture?.selectedCandidateId
                  ? `${
                      snapshot.architecture.candidates.find(
                        (c) =>
                          c.id === snapshot.architecture?.selectedCandidateId,
                      )?.name
                    } selected`
                  : snapshot.architecture
                    ? "no architecture selected"
                    : "no architecture was scored",
                openQuestions > 0
                  ? `${openQuestions} unanswered ${openQuestions === 1 ? "question" : "questions"}`
                  : unappliedAnswers(snapshot) > 0
                    ? `${unappliedAnswers(snapshot)} ${unappliedAnswers(snapshot) === 1 ? "answer" : "answers"} not applied yet`
                    : "every question answered",
              ].join(" · ")}
              approveLabel="Approve design"
              notePrompt="What needs to change before this design is right"
              notePlaceholder="Split the review queue by document type before we build it."
              // A design with no recommendation cannot be approved either, and for a
              // better reason: there is no shape to record. Reading through the null
              // here is what took the whole phase down when a leaf stage had failed.
              approveDisabled={
                !snapshot.architecture?.selectedCandidateId || approvalBlocker(snapshot) !== null
              }
              approveDisabledReason={
                approvalBlocker(snapshot) ??
                (snapshot.architecture
                  ? "Select an architecture before approving, so the record says which shape was chosen"
                  : "No shapes were scored, so there is no architecture to record. Retry that stage first.")
              }
              concerns={designConcerns(snapshot)}
              onApprove={async (note) => {
                await page.approveDesign(note);
                page.setSelectedStage("design-review");
              }}
              onRequestChanges={async (note) => {
                await page.requestChanges(note);
                page.setSelectedStage("design-review");
              }}
            />
          )}

          {/* The one generating indicator. It names the stage the snapshot says is
          being generated, which is the same stage the chevron spins on and the
          same one the header subtitle mentions. */}
          {generatingStageId && (
            <div
              className={cn(
                "fixed bottom-6 left-1/2 z-30 flex -translate-x-1/2 items-center gap-3 rounded-2xl border px-4 py-3 shadow-2xl",
                isDark
                  ? "border-white/10 bg-[#0f1d32]"
                  : "border-slate-200 bg-white",
              )}
            >
              <Spinner size="sm" tone="accent" decorative />
              <span
                className={cn(
                  "text-sm font-medium",
                  isDark ? "text-slate-200" : "text-slate-700",
                )}
              >
                Generating {STAGE_META[generatingStageId].label}
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
