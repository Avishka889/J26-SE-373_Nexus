import { DEPLOY_STAGE_IDS, type DeployStageId, type ProjectStatus } from "@/types/project";
import type {
  DeploySnapshot,
  DeployStages,
  DeployThreadMessage,
  GateDecision,
} from "../api/types";
import {
  DEMO_CANDIDATE,
  DEMO_CHANGELOG,
  DEMO_FEEDBACK,
  DEMO_IMPACT,
  DEMO_LEDGER,
  DEMO_MONITORING,
  DEMO_PIPELINE,
  DEMO_PLAN,
  DEMO_RISK,
  DEMO_ROLLBACK,
  DEMO_SERVING,
  DEMO_UPDATES,
} from "./deploymentData";
import { decisionViews, releaseBlockers } from "./rules";

/**
 * A whole deployment phase, built for one project at one posture.
 *
 * Contract shaped: every report is one the orchestrator would return, made by
 * the product's own code (see `deploymentData.ts`), and everything that
 * changes while a person uses the page (stages, decisions, the gate, the
 * ledger, the thread) is assembled here in the read model's shape.
 *
 * The story is deliberately not a clean one. Deploy version 1 serves; deploy
 * version 2 went down minutes after release in a controlled failure and waits
 * on a person's rollback decision (FR20); deploy version 3 is analysed and
 * waiting at review with one High, two Medium and three Low updates, and the
 * High one is a minor release that SemVer alone would have called Medium.
 */

/** How far through the deployment phase a project is. */
export type DeployPosture = "blocked" | "awaiting";

/** The wire's time format, which the page renders as it comes. */
export function wireTime(at: Date = new Date()): string {
  return at.toISOString().slice(0, 16).replace("T", " ");
}

/**
 * The posture a project's own status implies.
 *
 * Derived rather than written beside each project, as the testing fixtures
 * derive theirs: a project cannot deploy what its test review never approved,
 * so a project before Deploy has an empty phase that says why.
 */
export function deployPostureFor(status: ProjectStatus): DeployPosture {
  return status === "deploy" || status === "complete" ? "awaiting" : "blocked";
}

function stage(
  id: DeployStageId,
  status: DeployStages[DeployStageId]["status"],
  version: number,
  summary: string | null = null,
): DeployStages[DeployStageId] {
  return {
    id,
    status,
    generatedFromVersion: status === "pending" ? 0 : version,
    generatedAt: status === "pending" ? null : DEMO_RISK.generatedAt,
    summary,
    error: null,
    modelUse: null,
  };
}

/** Every stage pending: nothing has run on this project yet. */
export function pendingStages(): DeployStages {
  return Object.fromEntries(DEPLOY_STAGE_IDS.map((id) => [id, stage(id, "pending", 0)])) as DeployStages;
}

/**
 * The seven analysis stages finished and the review reached.
 *
 * The summaries are the service's own sentences over this data. Release and
 * monitoring are never written by a run: the orchestrator carries them out
 * after the gate, so their rows stay pending and the page reads the ledger.
 */
export function reviewedStages(version: number): DeployStages {
  const levels = DEMO_RISK.byLevel;
  const assessed = DEMO_RISK.assessments.length;
  const read = DEMO_CHANGELOG.perUpdate;
  const voted = read.filter((one) => one.vote.level !== null).length;
  const files = DEMO_PIPELINE.files;
  const used = DEMO_IMPACT.perUpdate.filter((one) => one.references.length > 0).length;
  const layout = DEMO_PIPELINE.stack.layout?.kind ?? "unknown";
  return {
    "dependency-updates": stage(
      "dependency-updates",
      "complete",
      version,
      `${DEMO_UPDATES.updates.length} updates found, ${DEMO_UPDATES.rejected.length} could not ` +
        `be analysed, ${DEMO_UPDATES.upToDate.length} already up to date`,
    ),
    "changelog-analysis": stage(
      "changelog-analysis",
      "complete",
      version,
      `${read.length} updates read: ${DEMO_CHANGELOG.claimsVerified} claims verified, ` +
        `${DEMO_CHANGELOG.claimsRefused} refused; ${voted} voted and ${read.length - voted} abstained`,
    ),
    "impact-analysis": stage(
      "impact-analysis",
      "complete",
      version,
      `${used} of ${assessed} updates used by the code, in ${DEMO_IMPACT.affectedFiles.length} files; ` +
        `${DEMO_IMPACT.affectedComponents.length} components reached, ` +
        `${DEMO_IMPACT.unmappedFiles.length} files unmapped`,
    ),
    "risk-assessment": stage(
      "risk-assessment",
      "complete",
      version,
      `${assessed} updates assessed: ${levels.high} High, ${levels.medium} Medium, ` +
        `${levels.low} Low; ${DEMO_RISK.disagreements} where the signals disagree`,
    ),
    "pipeline-generation": stage(
      "pipeline-generation",
      "complete",
      version,
      `${files.length} files for the ${layout} MERN layout, ` +
        `${files.filter((one) => one.valid).length} valid on first generation; ` +
        `${DEMO_CANDIDATE.included.length} of ${DEMO_CANDIDATE.included.length} included ` +
        "updates in the lockfile",
    ),
    "staging-verification": stage(
      "staging-verification",
      "complete",
      version,
      `verified: ${DEMO_CANDIDATE.image} serves candidate ` +
        `${DEMO_CANDIDATE.candidateHash.slice(0, 12)}, ${DEMO_CANDIDATE.smoke.length} smoke ` +
        "requests answered",
    ),
    "rollback-planning": stage(
      "rollback-planning",
      "complete",
      version,
      `restorable to deploy version ${DEMO_ROLLBACK.restoreTarget?.deployVersion}, candidate ` +
        `${DEMO_ROLLBACK.restoreTarget?.candidateHash.slice(0, 12)}`,
    ),
    "deployment-review": stage(
      "deployment-review",
      "complete",
      version,
      "Everything generated so far is waiting on your decision",
    ),
    release: stage("release", "pending", version),
    monitoring: stage("monitoring", "pending", version),
  };
}

const REVIEWER = "Alex Chen";

function message(
  id: string,
  at: string,
  content: string,
  stageId: DeployStageId,
  author = "platform",
): DeployThreadMessage {
  return { id, kind: "system", stageId, author, content, at, producedVersion: null };
}

/** What the platform and the reviewer said, oldest first, in the orchestrator's words. */
function history(): DeployThreadMessage[] {
  const [second, first] = DEMO_LEDGER;
  return [
    message("t1", first.createdAt, "Approved deploy version 1.", "deployment-review", REVIEWER),
    message("t2", first.createdAt, "Releasing deploy version 1 to the local target.", "release"),
    message("t3", second.createdAt, "Approved deploy version 2.", "deployment-review", REVIEWER),
    message("t4", second.createdAt, "Releasing deploy version 2 to the local target.", "release"),
    message(
      "t5",
      DEMO_MONITORING.generatedAt,
      `Monitoring found deploy version 2 down: ${DEMO_MONITORING.states.at(-1)?.evidence}. ` +
        "A rollback waits for your decision.",
      "monitoring",
    ),
    message(
      "t6",
      DEMO_FEEDBACK.generatedAt,
      `Deploy version 2's window suggests ${DEMO_FEEDBACK.items.length} requirement change(s). ` +
        "Nothing is sent to requirements until you send it.",
      "monitoring",
    ),
  ];
}

function earlierDecisions(): GateDecision[] {
  const [second, first] = DEMO_LEDGER;
  return [
    { kind: "approved", by: REVIEWER, at: first.createdAt, note: null, version: 1 },
    { kind: "approved", by: REVIEWER, at: second.createdAt, note: null, version: 2 },
  ];
}

/**
 * Recompute what the read model derives: the decisions owed, what blocks a
 * release, and the computed fields the wire type carries.
 *
 * Called after every change, so a fixture mutation cannot leave a stale count
 * or a guard that no longer holds on screen.
 */
export function withDerived(snapshot: DeploySnapshot): DeploySnapshot {
  const review = snapshot.stages["deployment-review"];
  const waiting =
    snapshot.deployVersion > 0 &&
    review.status === "complete" &&
    review.generatedFromVersion === snapshot.deployVersion &&
    snapshot.gate.decision === null;
  const next = {
    ...snapshot,
    codeMovedOn:
      snapshot.deployedCodeVersion > 0 && snapshot.codeVersion > snapshot.deployedCodeVersion,
    awaitingDecision: snapshot.decisions.filter((one) => one.needsDecision).length,
    rollbackPending: snapshot.deployments.some(
      (one) => one.state === "awaiting-rollback-approval",
    ),
    liveState: snapshot.monitoring?.currentState ?? "unknown",
  };
  return {
    ...next,
    blocking: waiting
      ? releaseBlockers(next, {
          goAhead: false,
          cloudEnabled: false,
          connected: new Set(["github", "vercel"]),
        })
      : [],
  };
}

/** Testing has not approved anything yet, so there is nothing this phase may deploy. */
function blocked(projectId: string, status: ProjectStatus): DeploySnapshot {
  const tested = status === "testing";
  const coded = tested || status === "code";
  return withDerived({
    projectId,
    deployVersion: 0,
    testVersion: tested ? 1 : 0,
    approvedTestVersion: 0,
    approvedTestedCodeVersion: 0,
    codeVersion: coded ? 1 : 0,
    deployedCodeVersion: 0,
    analysedTestVersion: 0,
    target: "generated",
    scopePackages: [],
    releaseTarget: "local",
    autoDeployLow: false,
    stages: pendingStages(),
    updates: null,
    changelog: null,
    impact: null,
    risk: null,
    pipeline: null,
    plan: null,
    candidate: null,
    rollback: null,
    monitoring: null,
    feedback: null,
    decisions: [],
    feedbackDecisions: [],
    deployments: [],
    deploymentsTotal: 0,
    currentRelease: null,
    watching: null,
    cloud: null,
    blocking: [],
    run: null,
    gate: { decision: null, history: [] },
    thread: [],
    codeMovedOn: false,
    awaitingDecision: 0,
    rollbackPending: false,
    liveState: "unknown",
  });
}

/** Deploy version 3 analysed and waiting at review, with the history behind it. */
function awaiting(projectId: string): DeploySnapshot {
  const version = DEMO_RISK.version;
  return withDerived({
    projectId,
    deployVersion: version,
    testVersion: DEMO_UPDATES.testVersion,
    approvedTestVersion: DEMO_UPDATES.testVersion,
    approvedTestedCodeVersion: DEMO_UPDATES.codeVersion,
    codeVersion: DEMO_UPDATES.codeVersion,
    deployedCodeVersion: DEMO_UPDATES.codeVersion,
    analysedTestVersion: 0,
    target: "generated",
    scopePackages: [],
    releaseTarget: "local",
    autoDeployLow: false,
    stages: reviewedStages(version),
    updates: DEMO_UPDATES,
    changelog: DEMO_CHANGELOG,
    impact: DEMO_IMPACT,
    risk: DEMO_RISK,
    pipeline: DEMO_PIPELINE,
    plan: DEMO_PLAN,
    candidate: DEMO_CANDIDATE,
    rollback: DEMO_ROLLBACK,
    monitoring: DEMO_MONITORING,
    feedback: DEMO_FEEDBACK,
    decisions: decisionViews(DEMO_RISK.assessments, {}, DEMO_CANDIDATE.included),
    feedbackDecisions: [],
    deployments: DEMO_LEDGER,
    deploymentsTotal: DEMO_LEDGER.length,
    currentRelease: DEMO_SERVING,
    watching: null,
    cloud: null,
    blocking: [],
    run: null,
    gate: { decision: null, history: earlierDecisions() },
    thread: history(),
    codeMovedOn: false,
    awaitingDecision: 0,
    rollbackPending: false,
    liveState: "unknown",
  });
}

export function buildDeploySnapshot(
  projectId: string,
  status: ProjectStatus,
): DeploySnapshot {
  // A fresh copy every time, because the fixture store mutates what it holds.
  return structuredClone(
    deployPostureFor(status) === "awaiting" ? awaiting(projectId) : blocked(projectId, status),
  );
}
