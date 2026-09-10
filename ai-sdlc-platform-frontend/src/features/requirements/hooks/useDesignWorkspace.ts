import { stageToFollow } from "@/shared/ui/stage";
import { stoppedRun } from "@/shared/ui/phase";
import { useCallback, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useStageInUrl } from "@/shared/hooks";
import type { DesignStageId, Project } from "@/types/project";
import { useProjectFollowsItsRun } from "@/entities/project";
import { useUiStore } from "@/store/ui";
import { useSettings } from "@/entities/settings";
import { projectsApi } from "@/entities/project";
import { DESIGN_STAGE_IDS } from "@/types/project";
import { designGateIsWaiting } from "../model/gate";
import { STAGE_META } from "../model/stages";
import { projectDomain } from "../model/domain";
import { computeDesignProgress } from "../model/progress";
import { regeneratingStageIds } from "../model/outdated";
import { buildConversation } from "../model/conversation";
import { useDesignMutations, useDesignSnapshot } from "./useDesign";
import { composerSends } from "../model/composer";

/**
 * Everything the Requirements and Design page needs, in one place: the artifact,
 * the mutations, which stage is open, and the trace jump.
 */
export function useDesignWorkspace(project: Project) {
  const addToast = useUiStore((s) => s.addToast);
  const conversationOpen = useUiStore((s) => s.conversationOpen);
  const setConversationOpen = useUiStore((s) => s.setConversationOpen);
  const conversationSheetOpen = useUiStore((s) => s.conversationSheetOpen);
  const setConversationSheetOpen = useUiStore(
    (s) => s.setConversationSheetOpen,
  );
  const navigate = useNavigate();
  const settings = useSettings();
  const reviewer = settings.profile.name;

  const query = useDesignSnapshot(project.id);
  // The run renames the project and moves its status; this is what tells the
  // sidebar and the header.
  useProjectFollowsItsRun(
    project.id,
    query.data ? regeneratingStageIds(query.data).length > 0 : undefined,
  );
  const snapshot = query.data;
  const mutations = useDesignMutations(project.id);

  // Requirements Analysis by default. The old landing state asked the reader to
  // "pick a stage above" before showing anything, which is a menu standing in
  // front of the artifact they came to read.
  const [selectedStage, setSelectedStage] =
    useState<DesignStageId>("requirements");
  /**
   * Set the moment the reader chooses for themselves; after that they win.
   *
   * State rather than a ref: it is read while deciding whether the run may move
   * the view, and a value React cannot see is exactly what the refs rule is
   * about. One extra render on the first click is a fair price.
   */
  const [userChoseStage, setUserChoseStage] = useState(false);
  // Another phase links to a requirement, or to a screen, by the address:
  // Code's trace chips did nothing, and its screen links opened a stage of its
  // own. Read once, on arrival.
  const [params] = useSearchParams();
  /** The requirement a trace chip asked to see, cleared once it has been shown. */
  const [focusedRequirementId, setFocusedRequirementId] = useState<
    string | null
  >(() => params.get("requirement"));
  const [linkedScreenId] = useState(() => params.get("screen"));
  /**
   * Bumped whenever something asks the conversation for attention.
   *
   * A counter rather than a boolean so two requests in a row both land: the
   * second would be a no-op if this were "is the panel focused".
   */
  const [chatFocusSignal, setChatFocusSignal] = useState(0);

  // The graph is the generative source, and the projection is derived from it,
  // so memoise on the graph rather than the whole snapshot. Otherwise every
  // keystroke elsewhere would rebuild it and remount the canvas.
  const domain = useMemo(
    () => (snapshot ? projectDomain(snapshot.graph) : null),
    [snapshot?.graph], // eslint-disable-line react-hooks/exhaustive-deps
  );

  const progress = useMemo(
    () =>
      snapshot
        ? computeDesignProgress(snapshot)
        : { percent: 0, valueLabel: "0%" },
    [snapshot],
  );

  const chooseStage = useCallback((stageId: DesignStageId) => {
    setUserChoseStage(true);
    setSelectedStage(stageId);
  }, []);

  /**
   * One source for every status claim on this page.
   *
   * The chevrons, the floating pill, the phase progress label, the review banner
   * and the decision bar all read these, so they cannot disagree. They used to
   * come from three places: the snapshot, a zustand flag, and a client side timer
   * walking `reqPhase`, which is how a new project came to show eight green
   * chevrons, "Ready for review", the waiting-on-you bar and a "Generating
   * Architecture Graph" pill at the same moment.
   */
  const status = useMemo(() => {
    if (!snapshot) {
      return {
        generatingStageId: null as DesignStageId | null,
        isGenerating: false,
        everythingGenerated: false,
        gateWaiting: false,
        openQuestions: 0,
      };
    }
    const generating = regeneratingStageIds(snapshot);
    const everythingGenerated = DESIGN_STAGE_IDS.every(
      (id) => snapshot.stages[id].status === "complete",
    );
    return {
      generatingStageId: generating[0] ?? null,
      isGenerating: generating.length > 0,
      everythingGenerated,
      gateWaiting: designGateIsWaiting(snapshot),
      openQuestions: snapshot.questions.filter((q) => !q.answer).length,
    };
  }, [snapshot]);

  /**
   * While a run is going, the view follows it: each stage opens as it completes.
   *
   * It stops the instant the reader clicks anything, because watching is only
   * useful until somebody wants to look at something specific, and pulling the
   * page out from under them after that is worse than showing nothing.
   */
  // Adjusted during render rather than in an effect, so the stage that just
  // finished is the one this paint shows. An effect would open it a render
  // late, which during a run is a visible stutter on every stage.
  //
  // `sawGenerating` is what carries the follow onto the last stage: it
  // completes in the same snapshot that reports nothing generating, so a rule
  // asking only about the present tense stopped one stage short and never
  // opened the review.
  const [followedTo, setFollowedTo] = useState<DesignStageId | null>(null);
  const [sawGenerating, setSawGenerating] = useState(false);
  if (status.isGenerating && !sawGenerating) setSawGenerating(true);
  const following = snapshot
    ? stageToFollow<DesignStageId>({
        order: DESIGN_STAGE_IDS,
        isComplete: (id) => snapshot.stages[id].status === "complete",
        isGenerating: status.isGenerating,
        sawGenerating,
        userChoseStage,
        followedTo,
      })
    : null;
  if (following) {
    setFollowedTo(following);
    setSelectedStage(following);
  }

  /** One jump, used by every stage: open Requirements Analysis at that row. */
  const jumpToRequirement = useCallback(
    (requirementId: string) => {
      chooseStage("requirements");
      setFocusedRequirementId(requirementId);
    },
    [chooseStage],
  );

  const clearFocus = useCallback(() => setFocusedRequirementId(null), []);

  useStageInUrl(selectedStage, chooseStage, DESIGN_STAGE_IDS);

  /**
   * Open the conversation and put the cursor in it.
   *
   * Every pointer to the chat goes through here: the questions block, the
   * assumption correction control and the design review warning. One function,
   * so they cannot land differently.
   */
  const openChat = useCallback(() => {
    // Both surfaces: the desk column and, below lg, the sheet. Opening only
    // the preference left phone readers with a focused composer they could
    // not see.
    setConversationOpen(true);
    setConversationSheetOpen(true);
    setChatFocusSignal((n) => n + 1);
  }, [setConversationOpen, setConversationSheetOpen]);

  const stageSteps = useMemo(
    () =>
      DESIGN_STAGE_IDS.map((id) => ({
        id,
        label: STAGE_META[id].label,
        status: snapshot
          ? mapStageStatus(snapshot.stages[id].status)
          : ("future" as const),
      })),
    [snapshot],
  );

  // The stable pieces of the mutation, not the mutation object: `mutateAsync`
  // keeps its identity across renders, so the transcript is rebuilt when the
  // design changes rather than on every render. The promise is what keeps an
  // answer in its box until the server has it.
  const answerQuestion = mutations.answerQuestion.mutateAsync;
  const answering = mutations.answerQuestion.isPending;

  const conversation = useMemo(
    () =>
      snapshot
        ? buildConversation({
            snapshot,
            onOpenStage: chooseStage,
            onAnswerQuestion: (id, answer) => answerQuestion({ id, answer }),
            answering,
          })
        : [],
    [snapshot, chooseStage, answerQuestion, answering],
  );

  // Each of these resolves only when the server has accepted the change, and
  // rejects when it refused: the box that sent it keeps the text until then.
  const submitChange = useCallback(
    async (note: string) => {
      const before = snapshot?.requirementsVersion ?? 0;
      const next = await mutations.submitChange.mutateAsync({ note, by: reviewer });
      // Said as it happened: a note that arrives while a run is going waits for
      // it, and only a note that opened a version starts regenerating.
      addToast(
        next.requirementsVersion > before
          ? {
              type: "info",
              title: `Requirements now at version ${next.requirementsVersion}`,
              message: "The design is regenerating, Requirements Analysis included",
            }
          : {
              type: "info",
              title: "The change waits for the run in progress",
              message: "It applies, as a new version, once that run finishes",
            },
      );
      // The note is a requirement amendment, so it belongs in the project's own
      // source history that the other phases read, not only in this thread. A
      // refused note is not an amendment, so it is written only once accepted.
      void projectsApi.appendRequirementChatMessage(project.id, {
        role: "user",
        type: "source_requirement",
        content: note,
      });
    },
    [addToast, mutations.submitChange, project.id, reviewer, snapshot?.requirementsVersion],
  );

  // Resolves once the server accepted it and rejects when it refused, so a note
  // saying why to approve over a failure stays open with its text until then.
  const approveDesign = useCallback(
    async (note?: string) => {
      await mutations.submitGateDecision.mutateAsync({
        kind: "approved",
        by: reviewer,
        ...(note ? { note } : {}),
      });
      addToast({
        type: "success",
        title: "Design approved",
        message: "Code Generation can start",
      });
    },
    [addToast, mutations.submitGateDecision, reviewer],
  );

  const requestChanges = useCallback(
    async (note: string) => {
      await mutations.submitGateDecision.mutateAsync({ kind: "changes", by: reviewer, note });
      addToast({
        type: "warning",
        title: "Changes requested",
        message: "The affected stages are regenerating",
      });
    },
    [addToast, mutations.submitGateDecision, reviewer],
  );

  /** The chat's message: a change request at a pending review, a change note otherwise. */
  const sendFromChat = useCallback(
    (note: string) =>
      snapshot && composerSends(snapshot) === "request-changes"
        ? requestChanges(note)
        : submitChange(note),
    [requestChanges, snapshot, submitChange],
  );

  /** Only taken after approval: this is what unlocks the next phase. */
  /**
   * The way on from an approved design, which is a route and nothing else.
   *
   * This used to PATCH the project to `status: "code"` with a progress number.
   * Both are derived from the runs and the gates now, so `patch_project` drops
   * them and answers 200: the button sent a request that changed nothing, the
   * page stayed where it was, and it read as a dead control. Status is not
   * something a client may assert, which is the point of deriving it; going to
   * the next phase is navigation.
   */
  const continueToCodeGeneration = useCallback(() => {
    navigate(`/projects/${project.id}/code`);
  }, [navigate, project.id]);

  // Resolves when the server has answered, so Try again stays busy until then.
  const retryStage = useCallback(
    (stageId: DesignStageId) => mutations.retryStage.mutateAsync(stageId),
    [mutations.retryStage],
  );

  // The newest full run stopped before it finished, and nothing runs now.
  const stopped = stoppedRun(snapshot?.run, status.isGenerating);
  const startOver = useCallback(
    () => mutations.startOver.mutateAsync(),
    [mutations.startOver],
  );
  const continueRun = useCallback(
    () => (stopped ? mutations.continueRun.mutateAsync(stopped.id) : undefined),
    [mutations.continueRun, stopped],
  );

  // The reader's own act, because it runs the model: answering only records.
  const applyAnswers = useCallback(async () => {
    await mutations.applyAnswers.mutateAsync();
    addToast({
      type: "info",
      title: "Regenerating with your answers",
      message: "The design runs again from Requirements Analysis",
    });
  }, [addToast, mutations.applyAnswers]);

  // Going on from the questions the run paused on. Each resolves when the server
  // has answered, so the button that asked stays busy; a refusal is reported by
  // the mutation cache.
  const continueWithAnswers = useCallback(
    () => mutations.continueFromQuestions.mutateAsync("answers").catch(() => undefined),
    [mutations.continueFromQuestions],
  );
  const continueWithAssumptions = useCallback(
    () => mutations.continueFromQuestions.mutateAsync("assumptions").catch(() => undefined),
    [mutations.continueFromQuestions],
  );

  return {
    query,
    sendFromChat,
    applyAnswers,
    continueWithAnswers,
    continueWithAssumptions,
    snapshot,
    domain,
    progress,
    reviewer,
    mutations,
    selectedStage,
    setSelectedStage: chooseStage,
    status,
    stageSteps,
    conversation,
    conversationOpen,
    setConversationOpen,
    conversationSheetOpen,
    setConversationSheetOpen,
    openChat,
    chatFocusSignal,
    focusedRequirementId,
    jumpToRequirement,
    linkedScreenId,
    clearFocus,
    submitChange,
    approveDesign,
    requestChanges,
    continueToCodeGeneration,
    retryStage,
    stopped,
    startOver,
    continueRun,
  };
}

function mapStageStatus(
  status: "pending" | "generating" | "complete" | "failed",
) {
  if (status === "complete") return "complete" as const;
  if (status === "generating") return "generating" as const;
  if (status === "failed") return "failed" as const;
  return "future" as const;
}
