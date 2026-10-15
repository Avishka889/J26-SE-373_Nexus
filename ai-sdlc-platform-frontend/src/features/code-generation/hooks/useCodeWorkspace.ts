import { stageToFollow } from "@/shared/ui/stage";
import { stoppedRun } from "@/shared/ui/phase";
import { useCallback, useMemo, useState } from "react";
import { useStageInUrl } from "@/shared/hooks";
import { useNavigate } from "react-router-dom";
import { useUiStore } from "@/store/ui";
import { useConnections, useConnectionsLoad, useSettings } from "@/entities/settings";
import { useProjectFollowsItsRun } from "@/entities/project";
import type { Project } from "@/entities/project";
import { CODE_STAGE_IDS, type CodeStageId } from "@/types/project";
import { codeGateIsWaiting } from "../model/gate";
import { CODE_STAGE_META } from "../model/stages";
import { computeCodeProgress } from "../model/progress";
import { designMovedOn, generatingCodeStageIds } from "../model/outdated";
import { useCodeMutations, useCodeSnapshot } from "./useCode";
import { approvedVersion, refusedForSupersede } from "../model/supersede";
import { useSupersede } from "./useSupersede";
import { ARM_NAMES } from "../model/arms";
import { save } from "@/shared/viz/download";
import { messageOf } from "@/lib/http";
import { codeApi } from "../api";

/**
 * Everything the Code Generation page needs, derived once.
 *
 * The design phase's hook, for the code phase, and deliberately the same
 * shape: one status object rather than each component re-deriving "is a run in
 * flight" from the stage table and getting a different answer.
 *
 * The one thing this phase has that the design phase does not is two version
 * axes, so `status` carries `designMovedOn` beside the ordinary flags. It is
 * not a stage level fact and no stage can carry it: every stage of a run is
 * equally behind when the design has moved on underneath all of them.
 */
export function useCodeWorkspace(project: Project) {
  const navigate = useNavigate();
  const addToast = useUiStore((s) => s.addToast);
  const conversationOpen = useUiStore((s) => s.conversationOpen);
  const setConversationOpen = useUiStore((s) => s.setConversationOpen);
  const conversationSheetOpen = useUiStore((s) => s.conversationSheetOpen);
  const setConversationSheetOpen = useUiStore(
    (s) => s.setConversationSheetOpen,
  );
  const settings = useSettings();
  const reviewer = settings.profile.name;
  // Whether a run's code can go anywhere: without GitHub nothing is pushed,
  // and the page said so only after a run had been paid for. Unknown until the
  // connections are read.
  const connections = useConnections();
  const connectionsLoad = useConnectionsLoad();
  const githubConnected =
    connectionsLoad.status === "loaded"
      ? connections.some((one) => one.provider === "github" && one.connected)
      : null;

  const query = useCodeSnapshot(project.id);
  const snapshot = query.data;
  // Status and progress settle when the run does, with no mutation to say so.
  useProjectFollowsItsRun(
    project.id,
    snapshot ? generatingCodeStageIds(snapshot).length > 0 : undefined,
  );
  const mutations = useCodeMutations(project.id);
  // Approved code is replaced only after the reader confirms it (see the
  // dialog in CodeWorkspace); the server refuses otherwise.
  const supersede = useSupersede();
  const approved = snapshot ? approvedVersion(snapshot) : null;

  const [selectedStage, setSelectedStage] =
    useState<CodeStageId>("sprint-scope");
  const [userChoseStage, setUserChoseStage] = useState(false);
  /** The file a manifest row asked to open, cleared when the viewer closes. */
  /** The file the viewer shows, and the line a finding cited, if one did. */
  const [openFile, setOpenFile] = useState<{ path: string; line?: number } | null>(null);
  const [chatFocusSignal, setChatFocusSignal] = useState(0);

  const chooseStage = useCallback((id: CodeStageId) => {
    setUserChoseStage(true);
    setSelectedStage(id);
  }, []);

  const status = useMemo(() => {
    if (!snapshot) {
      return {
        generatingStageId: null as CodeStageId | null,
        isGenerating: false,
        everythingGenerated: false,
        gateWaiting: false,
        notStarted: true,
        canGenerate: false,
        designBlocker: null as string | null,
        designMovedOn: false,
        reviewMovedPast: false,
        agreementErrors: 0,
        buildPassed: false,
      };
    }
    const generating = generatingCodeStageIds(snapshot);
    const everythingGenerated =
      snapshot.codeVersion > 0 &&
      CODE_STAGE_IDS.every((id) => snapshot.stages[id].status !== "pending") &&
      generating.length === 0;
    // The precondition is the current design version, approved and settled,
    // which the server reads and says. The project's status said only that some
    // version was approved once, so a design changed after its approval offered
    // "Generate again" over a version nobody had reviewed.
    const designBlocker = snapshot.designBlocker ?? null;
    return {
      generatingStageId: generating[0] ?? null,
      isGenerating: generating.length > 0,
      everythingGenerated,
      gateWaiting: codeGateIsWaiting(snapshot),
      notStarted: snapshot.codeVersion === 0,
      canGenerate: designBlocker === null && generating.length === 0,
      designBlocker,
      designMovedOn: designMovedOn(snapshot),
      // A newer design, settled, since the code the review waits on was
      // generated: changes there would regenerate from the older design, and
      // an approval would send that code on, so generating again, which closes
      // the review, is the way on.
      reviewMovedPast:
        codeGateIsWaiting(snapshot) && designMovedOn(snapshot) && designBlocker === null,
      agreementErrors: (snapshot.agreement?.findings ?? []).filter(
        (finding) => finding.severity === "error",
      ).length,
      buildPassed:
        (snapshot.repository?.build?.steps ?? []).length > 0 &&
        (snapshot.repository?.build?.steps ?? []).every(
          (step) => step.outcome === "passed",
        ),
    };
  }, [snapshot]);

  /**
   * While a run is going, the view follows it: each stage opens as it
   * completes, and stops the instant the reader clicks anything.
   */
  // Adjusted during render rather than in an effect, so the stage that just
  // finished is the one this paint shows. An effect would open it a render
  // late, which during a run is a visible stutter on every stage.
  //
  // `sawGenerating` is what carries the follow onto the last stage: it
  // completes in the same snapshot that reports nothing generating, so a rule
  // asking only about the present tense stopped one stage short and never
  // opened the review.
  const [followedTo, setFollowedTo] = useState<CodeStageId | null>(null);
  const [sawGenerating, setSawGenerating] = useState(false);
  if (status.isGenerating && !sawGenerating) setSawGenerating(true);
  const following = snapshot
    ? stageToFollow<CodeStageId>({
        order: CODE_STAGE_IDS,
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

  useStageInUrl(selectedStage, chooseStage, CODE_STAGE_IDS);

  // The evidence a stage cites, where it lives: a requirement or a screen on the
  // design page. Requirement chips did nothing, and screen links opened a code
  // stage that does not show screens.
  const openRequirement = useCallback(
    (requirementId: string) =>
      navigate(
        `/projects/${project.id}/requirements?stage=requirements&requirement=${encodeURIComponent(requirementId)}`,
      ),
    [navigate, project.id],
  );
  const openScreen = useCallback(
    (screenId: string) =>
      navigate(
        `/projects/${project.id}/requirements?stage=wireframes&screen=${encodeURIComponent(screenId)}`,
      ),
    [navigate, project.id],
  );

  const openChat = useCallback(() => {
    setConversationOpen(true);
    setConversationSheetOpen(true);
    setChatFocusSignal((n) => n + 1);
  }, [setConversationOpen, setConversationSheetOpen]);

  const stageSteps = useMemo(
    () =>
      CODE_STAGE_IDS.map((id) => ({
        id,
        label: CODE_STAGE_META[id].label,
        status: snapshot
          ? mapStageStatus(snapshot.stages[id].status)
          : ("future" as const),
        // The agreement's errors, on the stage that shows them: the count sat
        // on the conversation button, which says nothing about them.
        ...(id === "contract-agreement" && status.agreementErrors > 0
          ? {
              badge: status.agreementErrors,
              badgeLabel: `${status.agreementErrors} agreement error${status.agreementErrors === 1 ? "" : "s"}`,
            }
          : {}),
      })),
    [snapshot, status.agreementErrors],
  );

  const progress = useMemo(
    () =>
      snapshot
        ? computeCodeProgress(snapshot)
        : { percent: 0, valueLabel: "Not started" },
    [snapshot],
  );

  const generate = useCallback(() => {
    const start = (force: boolean) =>
      mutations.generate.mutate(force, {
        onSuccess: () => {
          addToast({
            type: "info",
            title: "Generating code",
            message:
              "The contract is inferred first, then both sides are generated from it",
          });
        },
        onError: (error: Error) => {
          // The server saw an approval this page had not yet: ask now.
          const version = refusedForSupersede(error);
          if (version !== null) {
            supersede.askAfterRefusal(version, () => start(true));
            return;
          }
          // The refusal is the server's sentence: an unapproved design, a run
          // already in flight. "Nothing to generate from" was only ever one of them.
          addToast({
            type: "warning",
            title: "Could not start generation",
            message: error.message,
          });
        },
      });
    supersede.guard(approved, start);
  }, [addToast, approved, mutations.generate, supersede]);

  const setStoryScope = useCallback(
    (storyId: string, inScope: boolean) => {
      supersede.guard(approved, (force) =>
        mutations.setStoryScope.mutate(
          { storyId, inScope, by: reviewer, supersede: force },
          {
            onSuccess: (next) => {
              addToast({
                type: "info",
                title: `Code now at version ${next.codeVersion}`,
                message:
                  "The contract and both sides regenerate from the new scope",
              });
            },
          },
        ),
      );
    },
    [addToast, approved, mutations.setStoryScope, reviewer, supersede],
  );

  const planNextSprint = useCallback(() => {
    supersede.guard(approved, (force) =>
      mutations.planNextSprint.mutate(
        { by: reviewer, supersede: force },
        {
          onSuccess: (next) => {
            addToast({
              type: "info",
              title: `Code now at version ${next.codeVersion}`,
              message: "The next sprint's stories are in the build, and the code regenerates once",
            });
          },
        },
      ),
    );
  }, [addToast, approved, mutations.planNextSprint, reviewer, supersede]);

  const selectStack = useCallback(
    (stackId: string) => {
      mutations.selectStack.mutate({ stackId, by: reviewer });
    },
    [mutations.selectStack, reviewer],
  );

  const chooseArm = useCallback(
    (arm: "rule" | "llm" | "merged") => {
      supersede.guard(approved, (force) =>
        mutations.chooseArm.mutate(
          { arm, by: reviewer, supersede: force },
          {
            onSuccess: () => {
              addToast({
                type: "info",
                title: `Generating from the ${ARM_NAMES[arm] ?? arm} contract`,
                message: "Both sides regenerate from the contract you chose",
              });
            },
          },
        ),
      );
    },
    [addToast, approved, mutations.chooseArm, reviewer, supersede],
  );

  // Resolves when the server has answered, so Try again stays busy until then.
  const retryStage = useCallback(
    (stageId: CodeStageId) => mutations.retryStage.mutateAsync(stageId),
    [mutations.retryStage],
  );

  // Resolves once the server accepted it and rejects when it refused, so a note
  // saying why to approve over a failure stays open with its text until then.
  const approveCode = useCallback(
    async (note?: string) => {
      await mutations.submitDecision.mutateAsync({
        kind: "approved",
        by: reviewer,
        ...(note ? { note } : {}),
      });
      addToast({
        type: "success",
        title: "Code approved",
        message: "Testing and Security can start",
      });
    },
    [addToast, mutations.submitDecision, reviewer],
  );

  const continueToTesting = useCallback(() => {
    navigate(`/projects/${project.id}/testing`);
  }, [navigate, project.id]);

  // Resolves once the server accepted the change and rejects when it refused,
  // so the note or the composer keeps the text until then.
  const requestChanges = useCallback(
    async (note: string) => {
      await mutations.submitDecision.mutateAsync({
        kind: "changes",
        by: reviewer,
        note,
      });
      addToast({
        type: "warning",
        title: "Changes requested",
        message: "The code regenerates at a new version",
      });
    },
    [addToast, mutations.submitDecision, reviewer],
  );

  // The newest full run stopped before it finished, and nothing runs now.
  // Starting over is generating again, with the same confirmation over an
  // approved version.
  const stopped = stoppedRun(snapshot?.run, status.isGenerating);
  const continueRun = useCallback(
    () => (stopped ? mutations.continueRun.mutateAsync(stopped.id) : undefined),
    [mutations.continueRun, stopped],
  );

  /**
   * The contract on screen, as the OpenAPI document the server translates it
   * to. The route existed and nothing on the page reached it.
   */
  const shownVersion = snapshot?.codeVersion ?? 0;
  const downloadOpenApi = useCallback(async () => {
    if (!shownVersion) return;
    try {
      const document = await codeApi.getOpenApi(project.id, shownVersion);
      save(
        new Blob([`${JSON.stringify(document, null, 2)}\n`], { type: "application/json" }),
        `${fileStem(project.name)}-openapi-v${shownVersion}.json`,
      );
    } catch (error) {
      addToast({ type: "error", title: "The OpenAPI document could not be read", message: messageOf(error) });
    }
  }, [addToast, project.id, project.name, shownVersion]);

  /** The version on screen as a zip of its generated files. */
  const downloadArchive = useCallback(async () => {
    if (!shownVersion) return;
    try {
      const archive = await codeApi.getArchive(project.id, shownVersion);
      save(archive, `${fileStem(project.name)}-code-v${shownVersion}.zip`);
    } catch (error) {
      addToast({ type: "error", title: "The code could not be downloaded", message: messageOf(error) });
    }
  }, [addToast, project.id, project.name, shownVersion]);

  /** Push the version on screen, which was never pushed; the server lands an approved one. */
  const pushVersion = useCallback(async () => {
    if (!shownVersion) return;
    try {
      const next = await codeApi.pushVersion(project.id, shownVersion);
      mutations.commit(next);
      addToast({
        type: "success",
        title: `Code version ${shownVersion} pushed`,
        message: next.repository?.repository?.url ?? "",
      });
    } catch (error) {
      addToast({ type: "error", title: "That did not go through", message: messageOf(error) });
    }
  }, [addToast, mutations, project.id, shownVersion]);

  return {
    query,
    supersede,
    stopped,
    continueRun,
    downloadOpenApi,
    downloadArchive,
    pushVersion,
    githubConnected,
    openRequirement,
    openScreen,
    snapshot,
    progress,
    reviewer,
    mutations,
    selectedStage,
    setSelectedStage: chooseStage,
    status,
    stageSteps,
    conversationOpen,
    setConversationOpen,
    conversationSheetOpen,
    setConversationSheetOpen,
    openChat,
    chatFocusSignal,
    openFile,
    setOpenFile,
    generate,
    setStoryScope,
    planNextSprint,
    selectStack,
    chooseArm,
    retryStage,
    approveCode,
    continueToTesting,
    requestChanges,
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

/** "Book Tracker" as "book-tracker", for a file a person saves. */
function fileStem(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "project";
}
