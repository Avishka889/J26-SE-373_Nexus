import { scrollMotion } from "@/shared/utils/motion";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { isLive } from "@/lib/env";
import { testingKeys } from "@/lib/query";
import { useSessionStore } from "@/store/session";
import { useUiStore } from "@/store/ui";
import {
  projectsApi,
  refreshProject,
  useProject,
  useProjectFollowsItsRun,
} from "@/entities/project";
import { useSettings } from "@/entities/settings";
import { useEditorTabs, useStageInUrl } from "@/shared/hooks";
import { TEST_STAGE_IDS } from "@/types/project";
import type { TestTarget } from "../api/types";
import type { InboxFilter } from "../components/steps/StepHealing";
import { buildTestingConversation } from "../model/conversation";
import { railSteps } from "../model/rail";
import { testExplorerFrom } from "../model/files";
import { DECISION_CHAIN, SEVERITY_ORDER } from "../model/process";
import {
  approvalNote,
  buildView,
  counted,
  fileName,
  reverifiedToast,
  stepOrder,
  type StepId,
} from "../model/view";
import { testingApi } from "../api";
import { getTestingSnapshot } from "../fixtures/legacyDemo";
import { readState, stoppedRun } from "@/shared/ui/phase";

const DEFAULT_FILE =
  "backend/src/test/java/com/payflow/payments/PaymentControllerTest.java";

/**
 * The Testing and Security workspace's state.
 *
 * Everything the page renders derives from one `TestSnapshot`, which the
 * fixtures and the orchestrator both return. What used to live here as React
 * state, who approved which repair and which fix is being proven, now lives on
 * the server as overlays with an author and a time, and every mutation answers
 * with the whole snapshot. So an action is: call, write the answer into the
 * cache, done. No optimistic local copy to reconcile, and no way for the page
 * to show a decision the server did not record.
 *
 * What is left in `useState` is genuinely local: which step is open, which row
 * is selected, which file is in the viewer. None of it survives a reload and
 * none of it should.
 *
 * The file tree is the run's own when the phase is live: its paths come from
 * the test report and each open file's body from its own route, because the
 * snapshot deliberately carries no file bodies (it is polled every 1.2 seconds
 * while a run is in flight, and a run writes tens of files). Only the demo
 * reads the legacy fixtures, which a live page showed for months: Java test
 * files under "Backend tests run on JUnit", a detector table "measured on
 * 1,240 labelled files", and a last verified build that never existed.
 */
export function useTestingPage() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const theme = useUiStore((s) => s.theme);
  const addToast = useUiStore((s) => s.addToast);
  const setActiveProjectId = useSessionStore((s) => s.setActiveProjectId);
  const settings = useSettings();
  const isDark = theme === "dark";

  // The route wins over the session's active project, as the code and
  // deployment phases learned: preferring the session showed whichever project
  // was visited last under this one's address.
  const project = useProject(projectId);
  useEffect(() => {
    if (project) setActiveProjectId(project.id);
  }, [project, setActiveProjectId]);
  const id = project?.id ?? projectId ?? "";
  const reviewer = settings.profile.name;
  const queryClient = useQueryClient();

  const snapshot = useQuery({
    queryKey: testingKeys.snapshot(id),
    queryFn: () => testingApi.getTesting(id),
    enabled: Boolean(id),
    // While a stage is working the stepper is the thing a reader watches, so
    // the phase is polled at the cadence the other two use.
    refetchInterval: (query) =>
      Object.values(query.state.data?.stages ?? {}).some(
        (one) => one.status === "generating",
      )
        ? 1200
        : false,
  });

  /** Write a mutation's answer straight into the cache: it is the whole phase. */
  const apply = useCallback(
    async (
      call: Promise<Awaited<ReturnType<typeof testingApi.getTesting>>>,
    ) => {
      try {
        const next = await call;
        queryClient.setQueryData(testingKeys.snapshot(id), next);
        // The project's status and progress move with what this phase decides,
        // and the header and the lists read them.
        void refreshProject(id).catch(() => {
          // A stale badge is the badge that was already on screen.
        });
        return next;
      } catch (error) {
        addToast({
          type: "error",
          title: "That did not go through",
          message:
            error instanceof Error
              ? error.message
              : "The server refused the change.",
        });
        return null;
      }
    },
    [addToast, id, queryClient],
  );

  // The demo's data, which a live page never shows; see the docstring.
  const live = isLive("testing");
  // Not even built for a live page, which reads nothing from it.
  const demo = useMemo(() => (live ? null : getTestingSnapshot()), [live]);

  const conversationOpen = useUiStore((one) => one.conversationOpen);
  const setConversationOpen = useUiStore((one) => one.setConversationOpen);
  const conversationSheetOpen = useUiStore((one) => one.conversationSheetOpen);
  const setConversationSheetOpen = useUiStore(
    (one) => one.setConversationSheetOpen,
  );
  const [chatFocusSignal, setChatFocusSignal] = useState(0);

  const [step, setStep] = useState<StepId>("test-run");
  useStageInUrl(step, setStep, TEST_STAGE_IDS);
  const [inboxFilter, setInboxFilter] = useState<InboxFilter>("attention");
  const [selectedFailure, setSelectedFailure] = useState<string>("");
  const [expandedFinding, setExpandedFinding] = useState<string | null>(null);

  const { tabs, activePath, openFile, closeTab, setActivePath } = useEditorTabs(
    live ? "" : DEFAULT_FILE,
  );
  const [highlight, setHighlight] = useState<
    { path: string; line: number; label?: string } | undefined
  >(undefined);
  const viewerRef = useRef<HTMLDivElement | null>(null);

  const view = useMemo(
    () => (snapshot.data ? buildView({ data: snapshot.data, reviewer }) : null),
    [snapshot.data, reviewer],
  );

  // The run's own test files. Tabs are derived rather than synced, as the code
  // and deployment explorers do: a run without the open file must not leave
  // the editor on a path it does not have.
  const explorer = useMemo(
    () => (live && snapshot.data ? testExplorerFrom(snapshot.data) : null),
    [live, snapshot.data],
  );
  const known = useMemo(
    () => new Set((explorer?.files ?? []).map((one) => one.path)),
    [explorer],
  );
  const openTabs = tabs.filter((tab) => known.has(tab.path));
  const explorerTabs = !explorer
    ? tabs
    : openTabs.length > 0
      ? openTabs
      : explorer.first
        ? [{ path: explorer.first }]
        : [];
  const explorerPath = !explorer
    ? activePath
    : known.has(activePath)
      ? activePath
      : explorer.first;
  const testedVersion = snapshot.data?.testedCodeVersion ?? 0;
  const bodies = useQueries({
    queries: (explorer ? explorerTabs : []).map((tab) => ({
      queryKey: testingKeys.file(id, tab.path, testedVersion),
      queryFn: () => testingApi.getTestFile(id, tab.path, testedVersion),
      enabled: Boolean(id && tab.path && testedVersion),
      staleTime: Infinity,
    })),
  });
  const liveContents: Record<string, string> = {};
  if (explorer) {
    explorerTabs.forEach((tab, index) => {
      const query = bodies[index];
      if (query?.data) liveContents[tab.path] = query.data.content;
      else if (query?.isError)
        liveContents[tab.path] =
          `// ${tab.path}\n// This file could not be read from code version ${testedVersion}.\n`;
    });
  }
  const testsCaption = !explorer
    ? "Backend tests run on JUnit, frontend tests on Vitest. Each test sits where the code it protects sits."
    : explorer.runners.length === 0
      ? "No test has run yet."
      : explorer.runners.length === 1
        ? `Every test runs on ${explorer.runners[0]}, beside the code it protects.`
        : `Tests run on ${explorer.runners.join(" and ")}, each beside the code it protects.`;

  /**
   * Which of the demo states the page is in.
   *
   * Derived from the snapshot rather than from a URL parameter. The four demo
   * modes existed to show states the fixtures could not otherwise reach; the
   * snapshot reaches all of them honestly, because a project that has not been
   * tested really does have an empty phase and a run in flight really is
   * running.
   */
  const effective: "live" | "running" | "empty" | "error" = !snapshot.data
    ? snapshot.isError
      ? "error"
      : "empty"
    : snapshot.data.testVersion === 0
      ? "empty"
      : view?.streaming
        ? "running"
        : "live";

  const running = effective === "running";
  // The newest full run stopped before it finished, and nothing runs now.
  const phaseGenerating = Object.values(snapshot.data?.stages ?? {}).some(
    (one) => one.status === "generating",
  );
  const stopped = stoppedRun(snapshot.data?.run, phaseGenerating);
  // Status and progress settle when the run does, with no decision to say so.
  useProjectFollowsItsRun(id, snapshot.data ? phaseGenerating : undefined);
  const continueRun = () =>
    stopped ? apply(testingApi.continueRun(id, stopped.id)) : undefined;

  /* ------------------------------------------------------------- actions */

  // What this phase is pointed at, and what else it could be. Fetched once
  // rather than polled: the list is a fact about the deployment, not about the
  // project, and it does not change while somebody is looking at a page.
  const [targets, setTargets] = useState<TestTarget[]>([]);
  useEffect(() => {
    let live = true;
    void testingApi
      .listTargets(id)
      .then((found) => {
        if (live) setTargets(found);
      })
      .catch(() => {
        // A list that will not load leaves the selector hidden rather than
        // showing one option and implying there are no others.
        if (live) setTargets([]);
      });
    return () => {
      live = false;
    };
  }, [id]);

  const chooseTarget = (target: string) => {
    void apply(testingApi.chooseTarget(id, target, reviewer)).then((next) => {
      if (!next) return;
      const chosen = targets.find((one) => one.id === target);
      addToast({
        type: "success",
        title: "Measuring " + (chosen?.label ?? target),
        message: "The next run works on this repository.",
      });
    });
  };

  // Resolves when the server has answered, so the button that asked stays busy.
  const startRerun = () =>
    apply(testingApi.run(id)).then((next) => {
      if (next) {
        setStep("test-run");
        addToast({
          type: "info",
          title: "Testing started",
          message: "Generation, run, quality, healing, scan and remediation.",
        });
      }
    });

  const openFileAt = (path: string, line: number, label: string) => {
    openFile(path);
    setHighlight({ path, line, label });
    window.requestAnimationFrame(() =>
      viewerRef.current?.scrollIntoView({ behavior: scrollMotion(), block: "start" }),
    );
  };

  const openFailure = (failureId: string) => {
    setSelectedFailure(failureId);
    const failure = view?.failures.find((one) => one.id === failureId);
    if (failure) openFileAt(failure.file, failure.line, failure.reason);
  };

  // Each resolves when the server has answered, so the button stays busy until then.
  const approveRepair = (testId: string) =>
    apply(
      testingApi.decideHeal(id, testId, { decision: "kept", by: reviewer }),
    );

  const rejectRepair = (testId: string) =>
    apply(
      testingApi.decideHeal(id, testId, {
        decision: "reverted",
        by: reviewer,
        note: "Reverted from the healing inbox.",
      }),
    );

  // Resolves when the server has answered, so the control stays busy until then.
  const decideTest = (
    testId: string,
    decision: "quarantined" | "restored" | "rewrite",
    note?: string,
  ) => apply(testingApi.decideTest(id, testId, { decision, by: reviewer, note }));

  // Resolves whether the fix reached the code, so the button stays busy for
  // both calls and a second click cannot send them again.
  const applyFix = async (findingId: string) => {
    const proposal = snapshot.data?.remediation?.proposals.find(
      (one) => one.findingId === findingId,
    );
    if (!proposal) {
      addToast({
        type: "error",
        title: "No fix to apply",
        message: "No patch was proposed for this finding.",
      });
      return false;
    }
    // Two calls, because they are two acts: accepting is a decision and applying
    // writes source. The server keeps them apart for the same reason, and
    // refuses to apply a fix nobody accepted.
    const accepted = await apply(
      testingApi.decideProposal(id, proposal.id, {
        decision: "accepted",
        by: reviewer,
      }),
    );
    if (!accepted) return false;
    const next = await apply(
      testingApi.applyProposal(id, proposal.id, { by: reviewer }),
    );
    if (!next) return false;
    const version = next.remediation?.proposals.find(
      (one) => one.id === proposal.id,
    )?.appliedCodeVersion;
    addToast({
      type: "success",
      title: "Fix applied",
      message: version
        ? `Code version ${version} carries it. Run the tests again to re-verify.`
        : "Run the tests again to re-verify it.",
    });
    return true;
  };

  /**
   * Ask whether an applied fix worked.
   *
   * Only ever after a run has measured the patched version: the answer is a
   * subtraction over two runs, and the server says so rather than inventing one
   * when the second has not happened.
   */
  const reverifyFix = (findingId: string) => {
    const proposal = snapshot.data?.remediation?.proposals.find(
      (one) => one.findingId === findingId,
    );
    if (!proposal) return undefined;
    return apply(
      testingApi.reverifyProposal(id, proposal.id, { by: reviewer }),
    ).then((next) => {
      const result = next?.remediation?.proposals.find(
        (one) => one.id === proposal.id,
      )?.reverification;
      if (!result) return;
      addToast(reverifiedToast(result));
    });
  };

  // The note is the reader's reason. It was a fixed sentence, which put
  // "Dismissed from the security step." in the audit log as the reason a
  // weakness did not apply, and the server requires a reason for exactly that.
  const dismissFinding = async (findingId: string, reason: string) =>
    (await apply(
      testingApi.decideFinding(id, findingId, {
        decision: "dismissed",
        by: reviewer,
        note: reason,
      }),
    )) !== null;

  // Accepting is agreeing the weakness is real; with a reason, it is taking its
  // risk knowingly, and the release gate lets a Critical or High one ship only so
  // (G8, review item C3-8).
  const acceptFinding = async (findingId: string, reason: string) =>
    (await apply(
      testingApi.decideFinding(id, findingId, {
        decision: "accepted",
        by: reviewer,
        note: reason,
      }),
    )) !== null;

  /** Re-run the stage that produces the proofs, rather than the whole phase. */
  const retryProofs = () => apply(testingApi.retryStage(id, "remediation"));

  /**
   * Re-run one stage, from the chrome's own failure guard.
   *
   * The chrome offers this on any stage that failed, which is what the other
   * two phases do. A whole run would rewrite four artefacts the reader has
   * already read in order to fix the one they asked about, and in this phase
   * one of those is a mutation pass that takes minutes.
   */
  const retryStageById = (stageId: StepId) =>
    apply(testingApi.retryStage(id, stageId));

  const approvePhase = (reason?: string) => {
    const open = view?.findingCounts.toResolve ?? 0;
    setRequestPending(true);
    return apply(
      testingApi.submitDecision(id, {
        kind: "approved",
        by: reviewer,
        // The reviewer's reason for approving with something outstanding, and
        // the count of what was open, so the record has both.
        note: [reason, view ? approvalNote(view) : undefined].filter(Boolean).join(" ") || undefined,
      }),
    ).then((next) => {
      // Refused, and already said so: rejecting keeps the reviewer's note open.
      if (!next) throw new Error("The approval was refused.");
      if (project) {
        // The server's rule, which a live project reports on its own: three
        // phases finished, and deployment wherever it already was.
        const deployment = project.phaseProgress?.deployment ?? 0;
        void projectsApi.update(project.id, {
          status: "deploy",
          progress: Math.round((300 + deployment) / 4),
          phaseProgress: { design: 100, code: 100, testing: 100, deployment },
        });
      }
      addToast({
        type: "success",
        title: "Testing approved",
        message:
          open > 0 ? `${counted(open, "finding", "findings")} left open` : "Deployment can start",
      });
      setStep("test-review");
    })
      .finally(() => setRequestPending(false));
  };

  /**
   * True while a decision is in flight, so the composer and the bar can say so.
   *
   * A local flag rather than a mutation object, because this phase calls the
   * API directly and writes the answer into the cache. Without it a second
   * click sends the decision twice and the second answer is a refusal.
   */
  const [requestPending, setRequestPending] = useState(false);

  /**
   * Resolves once the server accepted the change request and rejects when it
   * did not, so the note or the composer keeps the text until then. `apply`
   * has already said why it failed.
   */
  const requestChanges = async (note: string) => {
    setRequestPending(true);
    try {
      const next = await apply(
        testingApi.submitDecision(id, { kind: "changes", by: reviewer, note }),
      );
      if (!next) throw new Error("The change request was not accepted.");
      addToast({ type: "info", title: "Changes requested", message: note });
    } finally {
      setRequestPending(false);
    }
  };

  /**
   * Rolling back is a code phase action.
   *
   * A remediation is applied by C2 as a new code version, so undoing one means
   * going back to the version before it. C3 proposes and re-verifies; it does
   * not write source, and a button here that appeared to would be claiming
   * something this component cannot do.
   */
  const rollback = () => {
    addToast({
      type: "info",
      title: "Rollback happens in Code Generation",
      message: "An applied fix is a code version, so it is reverted there.",
    });
    navigate(`/projects/${id}/code`);
  };

  const selectFile = (path: string) => {
    openFile(path);
    setHighlight(undefined);
  };

  const goToFromSummary = (target: StepId) => setStep(target);

  const openCode = () => navigate(`/projects/${id}/code`);
  // From the project's status, as the testing api reads it: a feature does not
  // import another, and the status is the fact both phases agree on.
  const codeApproved =
    project?.status === "testing" ||
    project?.status === "deploy" ||
    project?.status === "released" ||
    project?.status === "complete";
  // Returned, so Try again stays busy while the phase is read again.
  const retryLoad = () => snapshot.refetch();
  const openDeployment = () => navigate(`/projects/${id}/deployment`);
  // On this phase's entries: the review links there instead of copying them.
  const openActivity = () => navigate(`/projects/${id}/traceability?filter=testing`);

  /**
   * The chevrons, with each stage's real state rather than its position.
   *
   * The stepper has two modes and the difference matters here. Without an
   * explicit status it guesses from position against a progress id, and this
   * phase passes a DOM id for its progress bar rather than a stage id, so every
   * chevron resolved to `future` and the whole rail was unclickable the moment
   * the phase moved onto the shared chrome.
   *
   * A skipped stage counts as settled. It will not run, it has something to
   * say about why, and a reader who cannot open it cannot read the reason.
   */
  const stepperSteps = useMemo(
    () =>
      // Whether each stage ran, and what it left for a person (`railSteps`).
      railSteps(stepOrder, snapshot.data?.stages, view),
    [snapshot.data, view],
  );

  /**
   * The transcript, and the one control that opens it.
   *
   * Rebuilt from the snapshot rather than held, so a refusal written to the
   * thread while the reader is looking appears without anything having to
   * remember to add it.
   */
  const conversation = useMemo(
    () =>
      snapshot.data
        ? buildTestingConversation({
            snapshot: snapshot.data,
            onOpenStage: setStep,
          })
        : [],
    [snapshot.data],
  );

  const openChat = () => {
    setConversationOpen(true);
    setConversationSheetOpen(true);
    setChatFocusSignal((one) => one + 1);
  };

  const progressId = `testing-progress-${id}`;

  return {
    project,
    projectId: id,
    snapshot: snapshot.data,
    isDark,
    effective,
    severityOrder: demo?.severityOrder ?? SEVERITY_ORDER,
    decisionChain: demo?.decisionChain ?? DECISION_CHAIN,
    testingRun: demo?.run ?? null,
    view,
    running,
    stopped,
    continueRun,
    step,
    setStep,
    stepperSteps,
    progressId,
    inboxFilter,
    setInboxFilter,
    selectedFailure,
    setSelectedFailure,
    expandedFinding,
    setExpandedFinding,
    tabs: explorerTabs,
    activePath: explorerPath,
    testFiles: explorer ? explorer.files : (demo?.testFiles ?? []),
    testFileMeta: explorer ? explorer.meta : (demo?.testFileMeta ?? {}),
    testFileContents: explorer ? liveContents : (demo?.testFileContents ?? {}),
    testsCaption,
    // Numbers nobody measured never reach a live page. The demo's detector table
    // and its last verified build are the demo's own.
    detectorComparison: demo?.detectorComparison ?? null,
    loadError:
      snapshot.error instanceof Error ? snapshot.error.message : undefined,
    /** A later read failed and the page shows the last answer, read at `lastReadAt`. */
    stale: readState(snapshot) === "stale",
    lastReadAt: snapshot.dataUpdatedAt,
    highlight,
    viewerRef,
    startRerun,
    targets,
    chooseTarget,
    openFileAt,
    openFailure,
    approveRepair,
    rejectRepair,
    decideTest,
    applyFix,
    acceptFinding,
    dismissFinding,
    retryProofs,
    retryStageById,
    conversation,
    conversationOpen,
    setConversationOpen,
    conversationSheetOpen,
    setConversationSheetOpen,
    chatFocusSignal,
    openChat,
    reverifyFix,
    approvePhase,
    requestChanges,
    requestPending,
    rollback,
    selectFile,
    selectTab: setActivePath,
    closeTab,
    goToFromSummary,
    openCode,
    codeApproved,
    retryLoad,
    openDeployment,
    openActivity,
    fileName,
  };
}
