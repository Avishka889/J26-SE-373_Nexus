import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { messageOf } from "@/lib/http";
import { deploymentKeys } from "@/lib/query";
import { useSessionStore } from "@/store/session";
import { useUiStore } from "@/store/ui";
import { refreshProject, useProject, useProjectFollowsItsRun } from "@/entities/project";
import { useSettings } from "@/entities/settings";
import { DEPLOY_STAGE_IDS, type DeployStageId } from "@/types/project";
import { useStageInUrl } from "@/shared/hooks";
import { deploymentApi } from "../api";
import type {
  DeploySnapshot,
  FeedbackDecisionInput,
  ReleaseTarget,
  ReleaseTargetOption,
  RollbackDecisionInput,
  UpdateDecisionInput,
} from "../api";
import { buildDeploymentConversation } from "../model/conversation";
import { buildView, stageToOpen } from "../model/view";
import { readState, stoppedRun } from "@/shared/ui/phase";

/** How often the phase is read while something is being carried out. */
const BUSY_POLL_MS = 1200;
/** And while a monitoring window this page opened is still running. */
const WINDOW_POLL_MS = 5000;
/** A window's length as the page asked for it: rounds times the interval. */
const WINDOW = { rounds: 10, interval: 30 };

/**
 * The deployment workspace's state.
 *
 * Everything the page renders derives from one `DeploySnapshot`, which the
 * fixtures and the orchestrator both return, and every action answers with the
 * whole snapshot: call, write the answer into the cache, done. What is left in
 * `useState` is genuinely local, such as which stage is open. Whether a
 * monitoring window runs is the server's to say (`watching`): the orchestrator
 * opens one on release as well as on request, and a page that kept its own
 * clock offered to open a second window the server refuses.
 */
/** How much of the ledger "Show every attempt" reads: more than any project here has made. */
const LEDGER_LIMIT = 500;

export function useDeploymentPage() {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const theme = useUiStore((s) => s.theme);
  const addToast = useUiStore((s) => s.addToast);
  const settings = useSettings();
  const isDark = theme === "dark";
  // The route wins over the session's active project, as the code phase found
  // the hard way: preferring the session showed whichever project was visited
  // last under this one's URL, and nothing on screen said so.
  const project = useProject(projectId);
  const setActiveProjectId = useSessionStore((s) => s.setActiveProjectId);
  useEffect(() => {
    if (project) setActiveProjectId(project.id);
  }, [project, setActiveProjectId]);
  const id = projectId;
  const reviewer = settings.profile.name;
  const queryClient = useQueryClient();

  const snapshot = useQuery({
    queryKey: deploymentKeys.snapshot(id),
    queryFn: () => deploymentApi.getDeployment(id),
    enabled: Boolean(id),
    refetchInterval: (query) => {
      const data = query.state.data;
      const busy =
        Object.values(data?.stages ?? {}).some((one) => one.status === "generating") ||
        (data?.deployments ?? []).some((one) => one.state === "pending" || one.state === "running");
      if (busy) return BUSY_POLL_MS;
      // Polled while a window runs, so its report shows when it closes.
      return data?.watching ? WINDOW_POLL_MS : false;
    },
  });

  const [pending, setPending] = useState(false);
  // The target just chosen, shown in the dropdowns until the server answers.
  // The answer is the whole phase composed again, two or three seconds on a
  // hosted database, and the dropdown showing the old choice meanwhile read
  // as a click that missed. Only the dropdowns show it: everything that acts
  // on the target (the go ahead, the release) still reads the server's.
  const [choosingTarget, setChoosingTarget] = useState<ReleaseTarget | null>(null);
  // The go ahead a cloud release needs. Local, and given afresh for each
  // release: a standing yes to spending provider minutes is the policy's job.
  const [goAhead, setGoAhead] = useState(false);

  /** Write a mutation's answer straight into the cache: it is the whole phase. */
  const apply = useCallback(
    async (call: Promise<DeploySnapshot>): Promise<DeploySnapshot | null> => {
      setPending(true);
      try {
        const next = await call;
        queryClient.setQueryData(deploymentKeys.snapshot(id), next);
        // The project's status and progress move with what this phase decides,
        // and the header and the lists read them.
        void refreshProject(id).catch(() => {
          // A stale badge is the badge that was already on screen.
        });
        return next;
      } catch (error) {
        addToast({ type: "error", title: "That did not go through", message: messageOf(error) });
        return null;
      } finally {
        setPending(false);
      }
    },
    [addToast, id, queryClient],
  );

  const view = useMemo(() => (snapshot.data ? buildView(snapshot.data) : null), [snapshot.data]);

  // The stage a reader lands on is the one that needs them, chosen once when
  // the phase first arrives; after that the reader moves and the page follows.
  const [chosenStage, setStage] = useState<DeployStageId | null>(null);
  const stage: DeployStageId = chosenStage ?? (view ? stageToOpen(view) : "dependency-updates");
  useStageInUrl(stage, setStage, DEPLOY_STAGE_IDS);

  const [targets, setTargets] = useState<ReleaseTargetOption[]>([]);
  useEffect(() => {
    let live = true;
    void deploymentApi
      .listTargets(id)
      .then((found) => {
        if (live) setTargets(found);
      })
      .catch(() => {
        if (live) setTargets([]);
      });
    return () => {
      live = false;
    };
  }, [id]);

  const conversationOpen = useUiStore((one) => one.conversationOpen);
  const setConversationOpen = useUiStore((one) => one.setConversationOpen);
  const conversationSheetOpen = useUiStore((one) => one.conversationSheetOpen);
  const setConversationSheetOpen = useUiStore((one) => one.setConversationSheetOpen);
  const [chatFocusSignal, setChatFocusSignal] = useState(0);

  const conversation = useMemo(
    () =>
      snapshot.data
        ? buildDeploymentConversation({ snapshot: snapshot.data, onOpenStage: setStage })
        : [],
    [snapshot.data],
  );

  /* ------------------------------------------------------------- actions */

  // Resolves when the server has answered, so the button that asked stays busy.
  const run = () =>
    apply(deploymentApi.run(id)).then((next) => {
      if (!next) return;
      setStage("dependency-updates");
      addToast({
        type: "info",
        title: `Deploy version ${next.deployVersion} started`,
        message: "Updates, release notes, impact, risk, pipeline, staging and the rollback plan.",
      });
    });

  // Resolves when the server has answered, so Try again stays busy until then.
  const retryStage = (stageId: DeployStageId) => apply(deploymentApi.retryStage(id, stageId));

  // Each decision that carries a note resolves to whether the server accepted
  // it, so the note's draft is cleared only once it has; `apply` has already
  // said why when it did not.
  const decideUpdate = (updateId: string, decision: UpdateDecisionInput["decision"], note: string) =>
    apply(
      deploymentApi.decideUpdate(id, updateId, {
        decision,
        by: reviewer,
        note: note.trim() || undefined,
      }),
    ).then(Boolean);

  const approve = () =>
    void apply(
      deploymentApi.submitDecision(id, {
        kind: "approved",
        by: reviewer,
        goAhead: snapshot.data?.releaseTarget === "cloud" ? goAhead : undefined,
      }),
    ).then(
      (next) => {
        if (!next) return;
        setGoAhead(false);
        setStage("release");
        addToast({
          type: "success",
          title: `Deploy version ${next.deployVersion} approved`,
          message: `The release to the ${next.releaseTarget} target has started.`,
        });
      },
    );

  /** Rejects when the change was not accepted, so the note keeps its text. */
  const requestChanges = async (note: string) => {
    const next = await apply(deploymentApi.submitDecision(id, { kind: "changes", by: reviewer, note }));
    if (!next) throw new Error("The change request was not accepted.");
    addToast({ type: "info", title: "Changes requested", message: note });
  };

  // Resolves when the server has answered, so the button that asked stays busy.
  const releaseAgain = (deploymentId: string) =>
    apply(deploymentApi.releaseAgain(id, deploymentId)).then((next) => {
      if (next) {
        addToast({
          type: "info",
          title: "Releasing again",
          message: "The same approved version, after the guards were checked again.",
        });
      }
    });

  const decideRollback = (
    deploymentId: string,
    decision: RollbackDecisionInput["decision"],
    note: string,
  ) =>
    apply(
      deploymentApi.decideRollback(id, deploymentId, {
        decision,
        by: reviewer,
        note: note.trim() || undefined,
      }),
    ).then((next) => {
      if (next && decision === "approved") {
        addToast({
          type: "info",
          title: "Rollback started",
          message: "It reports restored only when the verified release's fingerprint is served again.",
        });
      }
      return Boolean(next);
    });

  const watch = () =>
    void apply(deploymentApi.openMonitoringWindow(id, WINDOW)).then((next) => {
      if (!next) return;
      addToast({
        type: "info",
        title: "Watching the serving release",
        message: `${WINDOW.rounds} rounds, every ${WINDOW.interval} s. The report appears when the window closes.`,
      });
    });

  const decideFeedback = (
    itemId: string,
    decision: FeedbackDecisionInput["decision"],
    note: string,
  ) =>
    apply(
      deploymentApi.decideFeedback(id, itemId, {
        decision,
        by: reviewer,
        note: note.trim() || undefined,
      }),
    ).then(Boolean);

  /** Send suggestions to requirements as one change; the page confirms first. */
  const sendFeedback = (itemIds: string[]) =>
    apply(deploymentApi.sendFeedback(id, itemIds, { by: reviewer })).then((next) => {
      if (next) {
        addToast({
          type: "success",
          title: "Sent to requirements",
          message: "Requirements and Design is running again with the change.",
        });
      }
      return Boolean(next);
    });

  // Resolves to whether the server took it, so a run asked for after it starts
  // only once it has.
  const chooseTarget = (target: ReleaseTarget) => {
    setChoosingTarget(target);
    return apply(deploymentApi.chooseTarget(id, target, reviewer))
      .then(Boolean)
      .finally(() => setChoosingTarget(null));
  };

  const chooseScope = (packages: string[]) =>
    apply(deploymentApi.chooseScope(id, packages, reviewer)).then(Boolean);

  /** Every attempt on the ledger, beyond the newest ten the snapshot carries. */
  const loadLedger = () =>
    deploymentApi.listLedger(id, LEDGER_LIMIT).catch((error: unknown) => {
      addToast({ type: "error", title: "The history could not be read", message: messageOf(error) });
      return null;
    });

  const choosePolicy = (autoDeployLow: boolean) =>
    void apply(deploymentApi.choosePolicy(id, { autoDeployLow, by: reviewer }));

  const openChat = () => {
    setConversationOpen(true);
    setConversationSheetOpen(true);
    setChatFocusSignal((one) => one + 1);
  };

  // The newest full run stopped before it finished, and nothing runs now.
  const phaseGenerating = Object.values(snapshot.data?.stages ?? {}).some(
    (one) => one.status === "generating",
  );
  const stopped = stoppedRun(snapshot.data?.run, phaseGenerating);
  // Status settles when the run does, and when a release does: a verified
  // release is what makes the project complete.
  useProjectFollowsItsRun(
    id,
    snapshot.data
      ? phaseGenerating ||
          snapshot.data.deployments.some((one) => one.state === "pending" || one.state === "running")
      : undefined,
  );
  const continueRun = () =>
    stopped ? apply(deploymentApi.continueRun(id, stopped.id)) : undefined;

  return {
    project,
    projectId: id,
    snapshot: snapshot.data,
    stopped,
    continueRun,
    loadFailed: snapshot.isError,
    /** A later read failed and the page shows the last answer, read at `lastReadAt`. */
    stale: readState(snapshot) === "stale",
    lastReadAt: snapshot.dataUpdatedAt,
    view,
    isDark,
    stage,
    setStage,
    targets,
    pending,
    goAhead,
    setGoAhead,
    watching: Boolean(snapshot.data?.watching),
    conversation,
    conversationOpen,
    setConversationOpen,
    conversationSheetOpen,
    setConversationSheetOpen,
    chatFocusSignal,
    openChat,
    run,
    retryStage,
    decideUpdate,
    approve,
    requestChanges,
    decideRollback,
    releaseAgain,
    watch,
    decideFeedback,
    sendFeedback,
    chooseTarget,
    shownTarget: choosingTarget ?? snapshot.data?.releaseTarget,
    chooseScope,
    loadLedger,
    choosePolicy,
    // Returned, so Try again stays busy while the phase is read again.
    retryLoad: () => snapshot.refetch(),
    openTesting: () => navigate(`/projects/${id}/testing`),
    openRequirement: () => navigate(`/projects/${id}/requirements`),
  };
}
