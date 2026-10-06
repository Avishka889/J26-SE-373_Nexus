// One derivation for the whole phase, from the snapshot the server returns.
//
// Every count on the page comes from here, so the stepper, the review summary
// and the decision bar cannot disagree. Four rules shape it:
//
//   1. The level is the report's. Nothing here computes a risk level; it reads
//      the arbitration the rule recorded and lays the decisions beside it.
//   2. A decision belongs to a version. The gate decision shown is the one that
//      covers the current deploy version, and a new version asks again.
//   3. Release and monitoring are read from the ledger and the monitoring
//      report. The orchestrator carries them out after the gate and never
//      writes their stage rows, so a stage row would say "pending" forever.
//   4. What was not measured is not shown as measured. A monitoring window over
//      a release that has since been replaced says so, rather than reporting
//      its state as the state of what serves now.

import type { ConsoleLine, TranscriptStep } from "@/shared/ui/console";
import { transcriptOf } from "@/shared/ui/console";
import type { StepStatus } from "@/shared/ui/chevronStatus";
import type { StageChromeState } from "@/shared/ui/stage";
import { DEPLOY_STAGE_IDS, type DeployStageId } from "@/types/project";
import type {
  Blocker,
  ChangelogClaim,
  DeploySnapshot,
  DeploymentView,
  FeedbackDecisionView,
  FeedbackItem,
  GateDecision,
  MonitoringReport,
  ReleaseCandidate,
  RiskLevel,
  UpdateAssessment,
  UpdateDecisionView,
  VerifiedRelease,
} from "../api/types";
import { DEPLOY_STAGE_META } from "./stages";

/**
 * Whether this release keeps its records in its database: staging ran it
 * against one, which it does only for code that reads MONGODB_URL. Code
 * generated before that keeps its records in memory whatever it is given.
 */
export function keptInTheDatabase(candidate: ReleaseCandidate): boolean {
  return candidate.steps.some((step) => step.name === "database" && step.outcome === "passed");
}

export type StepState = "done" | "attention" | "waiting" | "running" | "pending";

export type SignalName = "semver" | "changelog" | "usage";

export const SIGNAL_LABEL: Record<SignalName, string> = {
  semver: "SemVer",
  changelog: "Changelog",
  usage: "Code usage",
};

export type VoteView = {
  signal: SignalName;
  label: string;
  level: RiskLevel | null;
  rationale: string;
  /** Why the signal did not vote, when it did not. */
  abstained: string;
};

export type UsageView = {
  importsPackage: boolean;
  references: number;
  changedSymbols: number;
  apiDiff: string;
  apiDiffReason: string;
};

export type UpdateView = {
  updateId: string;
  key: string;
  package: string;
  ecosystem: "npm" | "maven";
  from: string;
  to: string;
  /** The version change, which the SemVer vote is derived from. */
  change: string;
  manifestPath: string;
  level: RiskLevel;
  decidedBy: string[];
  advisory: string;
  disagreement: boolean;
  votes: VoteView[];
  /** The verified release note claims the changelog vote cites, as the notes say them. */
  quotes: ChangelogClaim[];
  files: string[];
  components: string[];
  usage: UsageView | null;
  strategy: string;
  manualReview: boolean;
  rollbackRequired: boolean;
  explanation: string;
  explanationSource: "model" | "rule" | "none";
  /** Why the explanation is the rule's, when it is. */
  explanationNote: string;
  decision: UpdateDecisionView | null;
  included: boolean;
  /** Why the candidate left this update out, in its words; null when it carries it. */
  leftOut: string | null;
  rollback: { status: string; reason: string } | null;
};

export type StepView = { state: StepState; hint: string; count?: number };

export type ReleaseView = {
  /** Newest first, failures and their cause included (FR16): the newest ten. */
  history: DeploymentView[];
  /** How many attempts the ledger holds, of which `history` is the newest. */
  historyTotal: number;
  /** A release or rollback still being carried out. */
  active: DeploymentView | null;
  /** A release that went wrong after it moved traffic, waiting on a person (FR20). */
  awaitingRollback: DeploymentView | null;
  /** What happened to it, as a clause: a verified release monitoring found down, or a
   * release that failed after it may have moved production. */
  awaitingWhat: string;
  /** The deploy version approving its rollback restores, or null when nothing can be. */
  restoresTo: number | null;
  /** Why nothing can be restored, in its rollback plan's words when the plan says. */
  cannotRestore: string;
  /** What a restore does to the data, in the release's own rollback plan's words. */
  dataNote: string;
  /** Where a cloud release's API answers: its Render service, once the platform made it. */
  cloudApi: string | null;
  serving: VerifiedRelease | null;
  /** The deployment the serving release came from. */
  servingDeployment: DeploymentView | null;
};

export type MonitoringView = {
  report: MonitoringReport | null;
  /** The deployment the last window watched. */
  watched: DeploymentView | null;
  /** The deployment a window watches now, whose report is still to come. */
  watchingNow: DeploymentView | null;
  /** Whether the last window watched the release that serves now. */
  watchesServing: boolean;
  /** Whether a window can be opened: something verified serves, and no window watches it now. */
  canWatch: boolean;
  /** Why a window cannot be opened, in the route's words. */
  cannotWatch: string;
};

export type FeedbackView = {
  deployVersion: number | null;
  items: (FeedbackItem & { decision: FeedbackDecisionView | null })[];
  undecided: number;
};

export type DeploymentPageView = {
  /** Whose phase this is: drafts of decision notes are kept per project. */
  projectId: string;
  version: number;
  progress: number;
  /** An analysis run is in flight. */
  running: boolean;
  /** A release or rollback is being carried out. */
  releasing: boolean;
  empty: "not-approved" | "not-run" | null;
  decisionPending: boolean;
  /**
   * The review waiting is of an analysis of code that newer tested code
   * replaced: its approval is refused (G4), requesting changes there is
   * refused, and analysing again closes it.
   */
  reviewMovedPast: boolean;
  /**
   * The newest code version when the approved tests measured older code, or
   * zero. It waits for its own tests; until then the phase analyses and
   * releases the tested code, which newer code does not hold back.
   */
  codeAwaitingTests: number;
  /** The decision that covers the current deploy version, when there is one. */
  decided: GateDecision | null;
  blocking: Blocker[];
  levels: Record<RiskLevel, number>;
  updates: UpdateView[];
  needDecision: number;
  stages: Record<DeployStageId, StageChromeState>;
  chevrons: Record<DeployStageId, StepStatus>;
  steps: Record<DeployStageId, StepView>;
  release: ReleaseView;
  monitoring: MonitoringView;
  feedback: FeedbackView;
  stagingTranscript: ConsoleLine[];
  releaseTranscript: ConsoleLine[];
};

const ORDER: Record<RiskLevel, number> = { low: 0, medium: 1, high: 2 };

const capitalised = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

const plural = (count: number, one: string, many = `${one}s`) =>
  `${count} ${count === 1 ? one : many}`;

function updateViews(snapshot: DeploySnapshot): UpdateView[] {
  const assessments = snapshot.risk?.assessments ?? [];
  const claims = new Map(
    (snapshot.changelog?.perUpdate ?? []).flatMap((analysis) =>
      analysis.claims.map((claim) => [claim.id, claim] as const),
    ),
  );
  const impacts = new Map((snapshot.impact?.perUpdate ?? []).map((one) => [one.updateId, one]));
  const updates = new Map((snapshot.updates?.updates ?? []).map((one) => [one.id, one]));
  const decisions = new Map(snapshot.decisions.map((one) => [one.updateId, one]));
  const rollbacks = new Map((snapshot.rollback?.updates ?? []).map((one) => [one.updateId, one]));
  const included = new Set(snapshot.candidate?.included ?? []);
  const leftOut = new Map((snapshot.candidate?.excluded ?? []).map((one) => [one.updateId, one.detail]));
  const changed = new Map<string, number>();
  for (const symbol of snapshot.impact?.changedSymbols ?? []) {
    changed.set(symbol.updateId, (changed.get(symbol.updateId) ?? 0) + 1);
  }

  const view = (assessment: UpdateAssessment): UpdateView => {
    const votes = assessment.votes.map((vote) => ({
      signal: vote.signal as SignalName,
      label: SIGNAL_LABEL[vote.signal as SignalName],
      level: vote.level as RiskLevel | null,
      rationale: vote.rationale,
      abstained: vote.abstainedReason,
    }));
    const cited = assessment.votes.find((vote) => vote.signal === "changelog")?.evidenceIds ?? [];
    const impact = impacts.get(assessment.updateId);
    const rollback = rollbacks.get(assessment.updateId);
    return {
      updateId: assessment.updateId,
      key: assessment.key,
      package: assessment.package,
      ecosystem: assessment.ecosystem,
      from: assessment.fromVersion,
      to: assessment.toVersion,
      change: assessment.change,
      manifestPath: updates.get(assessment.updateId)?.manifestPath ?? "",
      level: assessment.arbitration.final as RiskLevel,
      decidedBy: assessment.arbitration.decidedBy.map((one) => SIGNAL_LABEL[one as SignalName]),
      advisory: assessment.arbitration.advisory,
      disagreement: assessment.disagreement,
      votes,
      quotes: cited.flatMap((id) => {
        const claim = claims.get(id);
        return claim ? [claim] : [];
      }),
      files: assessment.affectedFiles,
      components: assessment.affectedComponents,
      usage: impact
        ? {
            importsPackage: impact.importsPackage,
            references: impact.references.length,
            changedSymbols: changed.get(assessment.updateId) ?? 0,
            apiDiff: impact.apiDiff,
            apiDiffReason: impact.apiDiffReason,
          }
        : null,
      strategy: assessment.strategy.deploy,
      manualReview: assessment.strategy.manualReviewRequired,
      rollbackRequired: assessment.strategy.rollbackRequired,
      explanation: assessment.explanation,
      explanationSource: assessment.explanationSource,
      explanationNote: assessment.explanationRefusal || assessment.explanationUnavailable,
      decision: decisions.get(assessment.updateId) ?? null,
      included: included.has(assessment.updateId),
      leftOut: leftOut.get(assessment.updateId) ?? null,
      rollback: rollback ? { status: rollback.status, reason: rollback.reason } : null,
    };
  };

  // The most cautious first, because that is the order a reviewer works in.
  return assessments
    .map(view)
    .sort((a, b) => ORDER[b.level] - ORDER[a.level] || a.package.localeCompare(b.package));
}

function releaseView(snapshot: DeploySnapshot): ReleaseView {
  const history = snapshot.deployments;
  const serving = snapshot.currentRelease;
  const awaiting = history.find((one) => one.state === "awaiting-rollback-approval") ?? null;
  // The plan the release's own run prepared, as the rollback route reads it; for an
  // older release it is not in the snapshot, and only a verified release on the same
  // target can be what it restores.
  const plan =
    awaiting && snapshot.rollback?.version === awaiting.deployVersion ? snapshot.rollback : null;
  const sameTarget =
    awaiting && serving && serving.target === awaiting.target && serving.deploymentId !== awaiting.id
      ? serving.deployVersion
      : null;
  const restoresTo = plan
    ? plan.restorable
      ? (plan.restoreTarget?.deployVersion ?? null)
      : null
    : sameTarget;
  return {
    history,
    historyTotal: Math.max(snapshot.deploymentsTotal, history.length),
    active: history.find((one) => one.state === "pending" || one.state === "running") ?? null,
    awaitingRollback: awaiting,
    awaitingWhat: awaiting?.verified
      ? "is down"
      : "failed after production traffic may have moved",
    restoresTo,
    cannotRestore:
      restoresTo !== null
        ? ""
        : plan?.unrestorableReason ||
          `no verified release on the ${awaiting?.target ?? "same"} target is on record`,
    dataNote: plan?.dataNote ?? "",
    cloudApi: snapshot.cloud?.render.origin ?? null,
    serving,
    servingDeployment: serving
      ? (history.find((one) => one.id === serving.deploymentId) ?? null)
      : null,
  };
}

function monitoringView(snapshot: DeploySnapshot, release: ReleaseView): MonitoringView {
  const report = snapshot.monitoring;
  // The route watches only what serves now: the newest deployment on the
  // chosen target that did not fail outright, and only once it is verified.
  const newest = snapshot.deployments.find(
    (one) => one.target === snapshot.releaseTarget && one.state !== "failed",
  );
  // A window runs in the orchestrator, opened on release or on request, and the
  // server refuses a second one while it does.
  const watchingNow = snapshot.watching
    ? (snapshot.deployments.find((one) => one.id === snapshot.watching) ?? null)
    : null;
  const serves = Boolean(newest && newest.state === "succeeded" && newest.verified && newest.url);
  const canWatch = serves && !snapshot.watching;
  return {
    report,
    watched: report
      ? (snapshot.deployments.find((one) => one.id === report.deploymentId) ?? null)
      : null,
    watchingNow,
    watchesServing: Boolean(report && release.serving?.deploymentId === report.deploymentId),
    canWatch,
    cannotWatch: canWatch
      ? ""
      : serves
        ? `${watchingNow ? `Deploy version ${watchingNow.deployVersion}` : "The serving release"} ` +
          "is being watched now, and its report replaces the one below when the window closes."
        : `Nothing verified serves this project on the ${snapshot.releaseTarget} target to watch: ` +
          "no release has been verified, or the newest one is still running or waits on a " +
          "rollback decision.",
  };
}

function feedbackView(snapshot: DeploySnapshot): FeedbackView {
  const decided = new Map(snapshot.feedbackDecisions.map((one) => [one.itemId, one]));
  const items = (snapshot.feedback?.items ?? []).map((item) => ({
    ...item,
    decision: decided.get(item.id) ?? null,
  }));
  return {
    deployVersion: snapshot.feedback?.deployVersion ?? null,
    items,
    undecided: items.filter((one) => one.decision === null).length,
  };
}

/** A deployment's steps in the console's shape, only those that have finished. */
export function deploymentTranscript(deployment: DeploymentView | null): ConsoleLine[] {
  if (!deployment) return [];
  const outcome: Record<string, string> = {
    succeeded: "passed",
    failed: "failed",
    compensated: "compensated",
    skipped: "not-run",
  };
  const finished: TranscriptStep[] = deployment.steps
    .filter((step) => step.state in outcome)
    .map((step) => ({
      name: step.label,
      command: step.command || step.label,
      outcome: outcome[step.state],
      logTail: step.error ? `${step.logTail}\n${step.error}`.trim() : step.logTail,
    }));
  return transcriptOf(finished);
}

function stageStates(
  snapshot: DeploySnapshot,
  release: ReleaseView,
  monitoring: MonitoringView,
): Record<DeployStageId, StageChromeState> {
  const states = Object.fromEntries(
    DEPLOY_STAGE_IDS.map((id) => [id, snapshot.stages[id] as StageChromeState]),
  ) as Record<DeployStageId, StageChromeState>;
  // Rule 3. A stage that has something to show is complete at the current
  // version, so the chrome renders it rather than a "not run yet" guard, and
  // never calls a release history outdated for being older than the analysis.
  const shown = (has: boolean): StageChromeState => ({
    status: has ? "complete" : "pending",
    generatedFromVersion: has ? snapshot.deployVersion : 0,
  });
  states.release =
    release.history.length === 0 && snapshot.stages.release.status === "generating"
      ? // Approved, and the run is writing the release down: it shows as working,
        // not as a stage that never ran, for the moment before the ledger has it.
        { status: "generating", generatedFromVersion: snapshot.deployVersion }
      : shown(release.history.length > 0);
  states.monitoring = shown(Boolean(monitoring.report || release.serving));
  return states;
}

function chevron(state: StageChromeState): StepStatus {
  if (state.status === "generating") return "generating";
  if (state.status === "failed") return "failed";
  if (state.status === "complete" || state.status === "skipped") return "complete";
  return "future";
}

function stepViews(
  snapshot: DeploySnapshot,
  view: {
    running: boolean;
    decisionPending: boolean;
    decided: GateDecision | null;
    needDecision: number;
    release: ReleaseView;
    monitoring: MonitoringView;
    feedback: FeedbackView;
  },
): Record<DeployStageId, StepView> {
  const status = (id: DeployStageId) => snapshot.stages[id].status;
  const notYet = (id: DeployStageId): StepView | null => {
    if (status(id) === "generating") return { state: "running", hint: "working" };
    if (status(id) === "failed") return { state: "attention", hint: "failed" };
    if (status(id) === "skipped") {
      return { state: "pending", hint: snapshot.stages[id].summary || "does not apply here" };
    }
    if (status(id) === "pending") return { state: "pending", hint: "not run yet" };
    return null;
  };
  const updates = snapshot.updates;
  const changelog = snapshot.changelog;
  const impact = snapshot.impact;
  const risk = snapshot.risk;
  const pipeline = snapshot.pipeline;
  const candidate = snapshot.candidate;
  const rollback = snapshot.rollback;
  const { release, monitoring, feedback } = view;
  const newest = release.history[0] ?? null;

  const releaseStep = (): StepView => {
    if (release.active) {
      return { state: "running", hint: `${release.active.kind} of deploy version ${release.active.deployVersion}` };
    }
    if (release.awaitingRollback) {
      return {
        state: "attention",
        hint: `deploy version ${release.awaitingRollback.deployVersion} ${release.awaitingWhat}, a rollback waits on you`,
      };
    }
    if (release.serving) {
      return { state: "done", hint: `deploy version ${release.serving.deployVersion} serves` };
    }
    if (newest) return { state: "attention", hint: `${newest.kind} ${newest.state}` };
    return { state: "pending", hint: "nothing released yet" };
  };

  const monitoringStep = (): StepView => {
    const report = monitoring.report;
    if (!report) {
      return release.serving
        ? { state: "waiting", hint: "not watched yet" }
        : { state: "pending", hint: "nothing serves yet" };
    }
    if (!monitoring.watchesServing) {
      return { state: "waiting", hint: "the serving release has not been watched" };
    }
    const hint = `last window ${report.currentState}`;
    const settled = report.currentState === "healthy" && feedback.undecided === 0;
    return settled
      ? { state: "done", hint }
      : { state: "attention", hint, count: feedback.undecided || undefined };
  };

  return {
    "dependency-updates":
      notYet("dependency-updates") ?? {
        // A rejection is FR3's recorded outcome, such as the project's own
        // workspace package, and not something for the reader to fix.
        state: "done",
        hint:
          `${plural(updates?.updates.length ?? 0, "update")}` +
          (updates?.rejected.length ? `, ${updates.rejected.length} could not be assessed` : ""),
      },
    "changelog-analysis":
      notYet("changelog-analysis") ?? {
        state: "done",
        hint:
          `${plural(changelog?.claimsVerified ?? 0, "claim")} verified, ` +
          `${changelog?.claimsRefused ?? 0} refused`,
      },
    "impact-analysis":
      notYet("impact-analysis") ?? {
        state: "done",
        hint: impact?.affectedFiles.length
          ? `${plural(impact.affectedFiles.length, "file")}, ${plural(impact.affectedComponents.length, "component")}`
          : "no file uses a changed symbol",
      },
    "risk-assessment":
      notYet("risk-assessment") ?? {
        state: risk && risk.byLevel.high > 0 ? "attention" : "done",
        count: risk?.byLevel.high || undefined,
        hint: `${risk?.byLevel.high ?? 0} High, ${risk?.byLevel.medium ?? 0} Medium, ${risk?.byLevel.low ?? 0} Low`,
      },
    "pipeline-generation":
      notYet("pipeline-generation") ??
      (pipeline && !pipeline.stack.supported
        ? { state: "attention", hint: `not supported: ${pipeline.stack.reason}` }
        : {
            state: pipeline?.valid ? "done" : "attention",
            hint: `${pipeline?.files.filter((one) => one.valid).length ?? 0} of ${plural(pipeline?.files.length ?? 0, "file")} valid`,
          }),
    "staging-verification":
      notYet("staging-verification") ??
      (candidate?.verified
        ? { state: "done", hint: "candidate verified" }
        : { state: "attention", hint: candidate ? "candidate not verified" : "no candidate built" }),
    "rollback-planning":
      notYet("rollback-planning") ??
      (rollback?.restorable
        ? { state: "done", hint: `restores deploy version ${rollback.restoreTarget?.deployVersion}` }
        : // Attention only when an update in this release needed the restore:
          // a first release has nothing earlier to return to, and counting
          // that as attention kept a finished project at 80%.
          rollback?.updates.some((one) => one.status === "unavailable")
          ? { state: "attention", hint: "cannot restore" }
          : { state: "done", hint: "nothing to restore" }),
    "deployment-review": view.decided
      ? {
          state: "done",
          hint: view.decided.kind === "approved" ? "approved" : "changes requested",
        }
      : view.running
        ? { state: "pending", hint: "waits for the run" }
        : view.decisionPending
          ? { state: "waiting", count: view.needDecision || undefined, hint: "waiting on you" }
          : { state: "pending", hint: "not reached" },
    release: releaseStep(),
    monitoring: monitoringStep(),
  };
}

export function buildView(snapshot: DeploySnapshot): DeploymentPageView {
  const analysis = DEPLOY_STAGE_IDS.slice(0, DEPLOY_STAGE_IDS.indexOf("deployment-review"));
  const running = analysis.some((id) => snapshot.stages[id].status === "generating");
  const review = snapshot.stages["deployment-review"];
  const reached =
    review.status === "complete" && review.generatedFromVersion === snapshot.deployVersion;
  // Rule 2: GateState.decision is the decision recorded against this version.
  const decided = snapshot.gate.decision ?? null;
  const decisionPending = !running && snapshot.deployVersion > 0 && reached && decided === null;
  const release = releaseView(snapshot);
  const monitoring = monitoringView(snapshot, release);
  const feedback = feedbackView(snapshot);
  const updates = updateViews(snapshot);
  const needDecision = snapshot.decisions.filter((one) => one.needsDecision).length;
  const stages = stageStates(snapshot, release, monitoring);
  const chevrons = Object.fromEntries(
    DEPLOY_STAGE_IDS.map((id) => [id, chevron(stages[id])]),
  ) as Record<DeployStageId, StepStatus>;
  // What serves is down and waiting on a person: the rail says so in red,
  // because that is the most urgent thing on the page.
  if (release.awaitingRollback) chevrons.release = "failed";
  if (monitoring.watchesServing && monitoring.report?.currentState === "down") {
    chevrons.monitoring = "failed";
  }
  if (release.active) chevrons.release = "generating";

  const steps = stepViews(snapshot, {
    running,
    decisionPending,
    decided,
    needDecision,
    release,
    monitoring,
    feedback,
  });
  const settled = Object.values(steps).filter((one) => one.state === "done").length;

  return {
    projectId: snapshot.projectId,
    version: snapshot.deployVersion,
    progress: Math.round((settled / DEPLOY_STAGE_IDS.length) * 100),
    running,
    releasing: release.active !== null,
    // The server's deploy version counts what was written, so a first run is at
    // zero until its first report lands; it is running, not empty.
    empty:
      snapshot.approvedTestVersion === 0
        ? "not-approved"
        : snapshot.deployVersion === 0 && !running && snapshot.deployments.length === 0
          ? "not-run"
          : null,
    decisionPending,
    reviewMovedPast: decisionPending && snapshot.codeMovedOn,
    codeAwaitingTests:
      snapshot.approvedTestedCodeVersion > 0 &&
      snapshot.codeVersion > snapshot.approvedTestedCodeVersion
        ? snapshot.codeVersion
        : 0,
    decided,
    blocking: snapshot.blocking,
    levels: {
      high: snapshot.risk?.byLevel.high ?? 0,
      medium: snapshot.risk?.byLevel.medium ?? 0,
      low: snapshot.risk?.byLevel.low ?? 0,
    },
    updates,
    needDecision,
    stages,
    chevrons,
    steps,
    release,
    monitoring,
    feedback,
    stagingTranscript: transcriptOf(snapshot.candidate?.steps ?? []),
    releaseTranscript: deploymentTranscript(release.active ?? release.history[0] ?? null),
  };
}

/**
 * The one release guard a person clears by deciding: a cloud release's go ahead.
 *
 * The server computes `blocking` without assuming the go ahead, so a cloud
 * release always lists it, and the decision itself carries it. Told apart by
 * the server's own sentence, which its tests pin and the fixtures repeat: the
 * guard shares its code (G5) with the switch and connection checks, which no
 * decision can clear.
 */
export const GO_AHEAD_BLOCKER =
  "a cloud release spends provider minutes, so the decision must carry the go ahead";

export function isGoAhead(blocker: Blocker): boolean {
  return blocker.code === "G5" && blocker.message === GO_AHEAD_BLOCKER;
}

/** Whether the release may be approved now, and in words why not. */
export function approval(
  view: DeploymentPageView,
  goAhead: boolean,
): { disabled: boolean; reason: string; asksForGoAhead: boolean } {
  const asksForGoAhead = view.blocking.some(isGoAhead);
  const remaining = view.blocking.filter((one) => !(isGoAhead(one) && goAhead));
  if (remaining.length === 0) return { disabled: false, reason: "", asksForGoAhead };
  const count = remaining.length;
  return {
    disabled: true,
    asksForGoAhead,
    reason:
      `${count} ${count === 1 ? "thing stops" : "things stop"} this release: ` +
      remaining.map((one) => one.message).join("; "),
  };
}

/** The stage a reader should land on: whatever needs them most. */
export function stageToOpen(view: DeploymentPageView): DeployStageId {
  if (view.release.awaitingRollback) return "release";
  if (view.decisionPending) return "deployment-review";
  if (view.releasing) return "release";
  if (view.running) {
    return (
      DEPLOY_STAGE_IDS.find((id) => view.stages[id].status === "generating") ??
      "dependency-updates"
    );
  }
  if (view.feedback.undecided > 0) return "monitoring";
  return view.version > 0 ? "risk-assessment" : "dependency-updates";
}

/** The first twelve characters of a hash or digest: enough to tell two apart on screen. */
export function shortHash(hash: string | null | undefined): string {
  return hash ? hash.replace(/^sha256:/, "").slice(0, 12) : "none";
}

export function levelLabel(level: string | null): string {
  return level ? capitalised(level) : "No vote";
}

export function stageLabel(id: DeployStageId): string {
  return DEPLOY_STAGE_META[id].label;
}

/**
 * What to do about a review that newer tested code replaced, as the page says
 * it: analyse again, on the code that has approved tests now.
 */
export function reviewMovedPastLine(snapshot: DeploySnapshot): string {
  const tested = snapshot.approvedTestedCodeVersion;
  return `This review is of an analysis of code version ${snapshot.deployedCodeVersion}, and code version ${tested} has approved tests now. Analyse the updates again to analyse version ${tested}: that closes this review.`;
}
