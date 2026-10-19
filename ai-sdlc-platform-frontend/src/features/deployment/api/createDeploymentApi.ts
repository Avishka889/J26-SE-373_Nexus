import { isLive } from "@/lib/env";
import { http } from "@/lib/http";
import { DEPLOY_STAGE_IDS, type DeployStageId } from "@/types/project";
import type {
  DeployDecisionInput,
  DeployFile,
  DeploySnapshot,
  DeploymentApi,
  DeploymentStepView,
  DeploymentView,
  FeedbackDecisionInput,
  MonitoringWindowInput,
  PolicyInput,
  ReleaseTarget,
  ReleaseTargetOption,
  RiskLevel,
  RollbackDecisionInput,
  UpdateDecisionInput,
  VerifiedRelease,
} from "./types";
import { reviewedStages, wireTime } from "../fixtures/buildDeploySnapshot";
import { DEMO_SERVING } from "../fixtures/deploymentData";
import { mutateDeployment, readDeployment } from "../fixtures/deployDb";
import { decisionViews, releaseBlockers, updateDecisionRefusal } from "../fixtures/rules";

/**
 * Deployment (C4) API seam.
 *
 * Fixtures answer until the feature is flipped live and the orchestrator
 * answers after; components cannot tell which, because both sides return the
 * same `DeploySnapshot` and refuse the same things in the same words.
 *
 * The fixture side is a small simulation of the orchestrator, not a script:
 * a run walks the seven analysis stages to the review, an approval releases
 * the candidate step by step, a rollback happens only when a person approves
 * one (FR20), and a monitoring window reports on what serves now. Its refusals
 * are the routes' own, from `fixtures/rules.ts`.
 */

const FIXTURE_DELAY_MS = 140;
/** How long each stage or step appears to take. Enough to watch, short enough to demo. */
const STEP_MS = 600;
/** A bounded monitoring window, compressed: the real one is rounds times the interval. */
const WINDOW_MS = 2400;

/** The stages a run produces, in order: everything before the review. */
const ANALYSIS = DEPLOY_STAGE_IDS.slice(0, DEPLOY_STAGE_IDS.indexOf("deployment-review"));

function sleep(ms: number) {
  return new Promise<void>((resolve) => window.setTimeout(resolve, ms));
}

function refuse(message: string): never {
  throw new Error(message);
}

/** The design version a sent change opens: one past the demo's 2 and every one sent since. */
function nextDesignVersion(draft: DeploySnapshot): number {
  const sent = draft.feedbackDecisions
    .filter((one) => one.decision === "sent")
    .map((one) => one.designVersion);
  return 3 + new Set(sent).size;
}

function newId(): string {
  return crypto.randomUUID();
}

/** Deployments the fixture's monitor is watching now, so a second window is refused. */
const watching = new Set<string>();

function reviewWaits(snapshot: DeploySnapshot): boolean {
  const review = snapshot.stages["deployment-review"];
  return (
    snapshot.deployVersion > 0 &&
    review.status === "complete" &&
    review.generatedFromVersion === snapshot.deployVersion &&
    snapshot.gate.decision === null
  );
}

function measuring(snapshot: DeploySnapshot): boolean {
  return ANALYSIS.some((id) => snapshot.stages[id].status === "generating");
}

/** The artefacts a run rewrote, labelled with the version it ran at. */
function relabel(draft: DeploySnapshot, version: number) {
  for (const artefact of [
    draft.updates,
    draft.changelog,
    draft.impact,
    draft.risk,
    draft.pipeline,
    draft.candidate,
    draft.rollback,
  ]) {
    if (artefact) artefact.version = version;
  }
  // A run plans for the target chosen when it runs, as the orchestrator's does.
  if (draft.plan) {
    draft.plan.deployVersion = version;
    draft.plan.target = draft.releaseTarget;
  }
}

function createFixtureApi(): DeploymentApi {
  /** Each analysis stage completes in turn, then the review is reached. */
  async function walk(projectId: string, version: number) {
    const reviewed = reviewedStages(version);
    for (const id of ANALYSIS) {
      await sleep(STEP_MS);
      mutateDeployment(projectId, (draft) => {
        draft.stages[id] = { ...reviewed[id], generatedAt: wireTime() };
        // As the server counts it: the newest version anything was written at,
        // so the version moves when the first stage writes its report, and the
        // decision on the version before becomes history then, not sooner.
        draft.deployVersion = version;
        if (draft.gate.decision && draft.gate.decision.version !== version) {
          draft.gate = { decision: null, history: [...draft.gate.history, draft.gate.decision] };
        }
      });
    }
    await sleep(STEP_MS);
    mutateDeployment(projectId, (draft, decisions) => {
      relabel(draft, version);
      draft.deployedCodeVersion = draft.codeVersion;
      draft.stages["deployment-review"] = {
        ...reviewed["deployment-review"],
        generatedAt: wireTime(),
      };
      draft.decisions = decisionViews(
          draft.risk?.assessments ?? [],
          decisions,
          draft.candidate?.included ?? [],
        );
    });
  }

  /** One deployment's steps, walked in order, then its ending. */
  async function carryOut(
    projectId: string,
    deploymentId: string,
    finish: (draft: DeploySnapshot, done: DeploymentView) => void,
  ) {
    const count =
      readDeployment(projectId).deployments.find((one) => one.id === deploymentId)?.steps.length ??
      0;
    for (let index = 0; index < count; index += 1) {
      await sleep(STEP_MS);
      mutateDeployment(projectId, (draft) => {
        const deployment = draft.deployments.find((one) => one.id === deploymentId);
        if (!deployment) return;
        const step = deployment.steps[index];
        step.state = "succeeded";
        step.attempt = 1;
        step.startedAt = step.startedAt ?? wireTime();
        step.finishedAt = wireTime();
        const upcoming = deployment.steps[index + 1];
        if (upcoming) {
          upcoming.state = "running";
          upcoming.startedAt = wireTime();
        }
      });
    }
    mutateDeployment(projectId, (draft) => {
      const deployment = draft.deployments.find((one) => one.id === deploymentId);
      if (!deployment) return;
      deployment.state = "succeeded";
      deployment.verified = true;
      deployment.finishedAt = wireTime();
      finish(draft, deployment);
    });
  }

  function verifiedFrom(deployment: DeploymentView, basis: VerifiedRelease): VerifiedRelease {
    return {
      ...basis,
      deploymentId: deployment.id,
      deployVersion: deployment.deployVersion,
      candidateHash: deployment.candidateHash,
      target: deployment.target,
      url: deployment.url,
      verifiedAt: wireTime(),
    };
  }

  type PlannedStep = Pick<DeploymentStepView, "stepId" | "label" | "provider" | "movesTraffic">;

  function steps(planned: PlannedStep[]): DeploymentStepView[] {
    return planned.map(({ stepId, label, provider, movesTraffic }, seq) => ({
      seq,
      stepId,
      label,
      provider,
      state: seq === 0 ? "running" : "pending",
      movesTraffic,
      attempt: 0,
      command: "",
      logTail: "",
      error: "",
      startedAt: seq === 0 ? wireTime() : null,
      finishedAt: null,
    }));
  }

  return {
    async getDeployment(projectId) {
      await sleep(FIXTURE_DELAY_MS);
      return readDeployment(projectId);
    },

    async getFile(projectId, path, version) {
      await sleep(FIXTURE_DELAY_MS);
      const file = readDeployment(projectId).pipeline?.files.find((one) => one.path === path);
      if (!file) refuse(`${path} was not generated`);
      const mark = path.endsWith(".json") ? "//" : "#";
      return {
        path,
        version,
        stage: "pipeline-generation",
        // The demo has no real file bodies and does not pretend to: it says so
        // where a body would be, rather than showing an invented workflow that
        // would read as generated output.
        content:
          [
            `${mark} ${path}`,
            `${mark} ${file.purpose}, from the ${file.templateId} template, ${file.bytes} bytes.`,
            file.secretsReferenced.length > 0
              ? `${mark} Names these secrets, never their values: ${file.secretsReferenced.join(", ")}.`
              : "",
            `${mark} The demo carries this file's name and checks, not its body.`,
            `${mark} A live project shows the file generated for it here.`,
          ]
            .filter(Boolean)
            .join("\n") + "\n",
      };
    },

    async chooseScope(projectId, packages, _by) {
      await sleep(FIXTURE_DELAY_MS);
      return mutateDeployment(projectId, (draft) => {
        draft.scopePackages = [...packages];
      });
    },

    async listLedger(projectId, limit) {
      await sleep(FIXTURE_DELAY_MS);
      return readDeployment(projectId).deployments.slice(0, limit);
    },

    async listTargets(_projectId) {
      await sleep(FIXTURE_DELAY_MS);
      // What a default orchestrator offers: cloud releases are off until the
      // owner turns them on, and the route says so rather than hiding them.
      return [
        { id: "local", label: "This machine, in containers", usable: true, reason: "" },
        {
          id: "cloud",
          label: "Vercel and Render, through GitHub Actions",
          usable: false,
          reason: "cloud releases are turned off on this orchestrator",
        },
      ];
    },

    async chooseTarget(projectId, target: ReleaseTarget, _by) {
      await sleep(FIXTURE_DELAY_MS);
      if (measuring(readDeployment(projectId))) {
        refuse("a deployment run is analysing; change this once it reaches its gate");
      }
      return mutateDeployment(projectId, (draft) => {
        draft.releaseTarget = target;
      });
    },

    async choosePolicy(projectId, policy: PolicyInput) {
      await sleep(FIXTURE_DELAY_MS);
      return mutateDeployment(projectId, (draft) => {
        draft.autoDeployLow = policy.autoDeployLow;
      });
    },

    async run(projectId) {
      await sleep(FIXTURE_DELAY_MS);
      const current = readDeployment(projectId);
      if (current.approvedTestVersion === 0) {
        refuse(
          "the test review has not approved anything on this project, so there is nothing " +
            "this phase may deploy",
        );
      }
      if (reviewWaits(current)) {
        refuse("a deployment review is waiting on this project; decide it before starting another run");
      }
      if (measuring(current)) refuse("a deployment run is already in flight on this project");
      const version = current.deployVersion + 1;
      const started = mutateDeployment(projectId, (draft) => {
        for (const id of ANALYSIS) {
          draft.stages[id] = { ...draft.stages[id], status: "generating", error: null };
        }
      });
      void walk(projectId, version);
      return started;
    },

    // The demo's runs never stop, so there is never a stopped run to go on with.
    async continueRun() {
      throw new Error("The demo never stops a run, so there is nothing to continue.");
    },

    async retryStage(projectId, stageId: DeployStageId) {
      await sleep(FIXTURE_DELAY_MS);
      if (!ANALYSIS.includes(stageId)) {
        refuse(`${stageId} is not a stage a run produces; there is nothing to re-run here`);
      }
      const current = readDeployment(projectId);
      if (current.deployVersion === 0) {
        refuse("nothing has been analysed yet, so there is no stage to retry");
      }
      if (current.gate.decision?.kind === "approved") {
        refuse(
          `deploy version ${current.deployVersion} was approved, so its stages are settled. ` +
            "Start a new run to analyse again.",
        );
      }
      const retried = mutateDeployment(projectId, (draft) => {
        draft.stages[stageId] = { ...draft.stages[stageId], status: "generating", error: null };
      });
      void sleep(STEP_MS).then(() =>
        mutateDeployment(projectId, (draft) => {
          draft.stages[stageId] = {
            ...reviewedStages(draft.deployVersion)[stageId],
            generatedAt: wireTime(),
          };
        }),
      );
      return retried;
    },

    async decideUpdate(projectId, updateId, decision: UpdateDecisionInput) {
      await sleep(FIXTURE_DELAY_MS);
      const current = readDeployment(projectId);
      if (!current.risk) {
        refuse("there is no risk assessment at the current deploy version to decide on");
      }
      const assessment = current.risk.assessments.find((one) => one.updateId === updateId);
      if (!assessment) refuse(`update ${updateId} was not found`);
      const level = assessment.arbitration.final as RiskLevel;
      const note = (decision.note ?? "").trim();
      const refusal = updateDecisionRefusal(level, decision.decision, note);
      if (refusal) refuse(refusal);
      return mutateDeployment(projectId, (draft, decisions) => {
        decisions[updateId] = {
          decision: decision.decision,
          by: decision.by,
          at: wireTime(),
          note,
          levelAtDecision: level,
        };
        draft.decisions = decisionViews(
          draft.risk?.assessments ?? [],
          decisions,
          draft.candidate?.included ?? [],
        );
      });
    },

    async submitDecision(projectId, decision: DeployDecisionInput) {
      await sleep(FIXTURE_DELAY_MS);
      const current = readDeployment(projectId);
      if (!reviewWaits(current)) refuse("there is no deployment decision waiting on this project");
      const note = (decision.note ?? "").trim();
      if (decision.kind === "changes" && !note) {
        refuse("requesting changes needs a note saying what to change");
      }
      if (decision.kind === "approved") {
        const blockers = releaseBlockers(current, {
          goAhead: Boolean(decision.goAhead),
          cloudEnabled: false,
          connected: new Set(["github", "vercel"]),
        });
        if (blockers.length > 0) {
          refuse(
            "the release guards refuse this approval: " +
              blockers.map((one) => one.message).join("; "),
          );
        }
      }
      const version = current.deployVersion;
      const at = wireTime();
      mutateDeployment(projectId, (draft) => {
        draft.gate = {
          decision: { kind: decision.kind, by: decision.by, at, note: note || null, version },
          history: draft.gate.history,
        };
        draft.thread.push({
          id: newId(),
          kind: "system",
          stageId: "deployment-review",
          author: decision.by,
          content:
            decision.kind === "approved"
              ? `Approved deploy version ${version}.`
              : `Requested changes: ${note}`,
          at,
          producedVersion: null,
        });
      });

      if (decision.kind === "changes") {
        const next = version + 1;
        const regenerating = mutateDeployment(projectId, (draft) => {
          for (const id of ANALYSIS) {
            draft.stages[id] = { ...draft.stages[id], status: "generating", error: null };
          }
        });
        void walk(projectId, next);
        return regenerating;
      }

      // Approved: the release starts on the candidate the review saw.
      const deploymentId = newId();
      const releasing = mutateDeployment(projectId, (draft) => {
        const plan = draft.plan;
        draft.deployments.unshift({
          id: deploymentId,
          kind: "release",
          target: draft.releaseTarget,
          state: "running",
          candidateHash: draft.candidate?.candidateHash ?? DEMO_SERVING.candidateHash,
          deployVersion: version,
          verified: false,
          cause: "",
          faultInjected: "",
          requestedBy: decision.by,
          authorisedBy: decision.by,
          restores: null,
          url: DEMO_SERVING.url,
          createdAt: wireTime(),
          finishedAt: null,
          steps: steps(
            (plan?.steps ?? []).map((one) => ({
              stepId: one.id,
              label: one.label,
              provider: one.provider,
              movesTraffic: one.movesTraffic,
            })),
          ),
        });
        draft.thread.push({
          id: newId(),
          kind: "system",
          stageId: "release",
          author: "platform",
          content: `Releasing deploy version ${version} to the ${draft.releaseTarget} target.`,
          at: wireTime(),
          producedVersion: null,
        });
      });
      void carryOut(projectId, deploymentId, (draft, done) => {
        draft.currentRelease = verifiedFrom(done, {
          ...DEMO_SERVING,
          lockfileSha256: draft.candidate?.lockfileSha256 ?? null,
          imageDigest: draft.candidate?.imageDigest ?? null,
        });
      });
      return releasing;
    },

    // The demo's releases are never undone, so there is none to release again.
    async releaseAgain() {
      refuse("The demo never undoes a release, so there is nothing to release again.");
    },

    async decideRollback(projectId, deploymentId, decision: RollbackDecisionInput) {
      await sleep(FIXTURE_DELAY_MS);
      const current = readDeployment(projectId);
      const release = current.deployments.find((one) => one.id === deploymentId);
      if (!release) refuse(`deployment ${deploymentId} was not found`);
      const note = (decision.note ?? "").trim();
      if (decision.decision === "rejected") {
        if (!note) refuse("declining a rollback needs a note saying why");
        return mutateDeployment(projectId, (draft) => {
          // The question is closed, as on the server: a verified release serves on,
          // and one that was never verified failed.
          const declined = draft.deployments.find((one) => one.id === deploymentId);
          if (declined?.state === "awaiting-rollback-approval") {
            declined.state = declined.verified ? "succeeded" : "failed";
          }
          draft.thread.push({
            id: newId(),
            kind: "system",
            stageId: "release",
            author: decision.by,
            content: `Declined rolling back deploy version ${release.deployVersion}: ${note}`,
            at: wireTime(),
            producedVersion: null,
          });
        });
      }
      if (release.kind !== "release") refuse("the rollback cannot start: only a release can be rolled back");
      if (release.state !== "awaiting-rollback-approval" && release.state !== "succeeded") {
        refuse(`the rollback cannot start: a release that is ${release.state} has nothing to roll back`);
      }
      // Every release in this demo restores to the release that served before
      // the one that went down, which its rollback plan names.
      const target = DEMO_SERVING;
      const rollbackId = newId();
      const started = mutateDeployment(projectId, (draft) => {
        draft.deployments.unshift({
          id: rollbackId,
          kind: "rollback",
          target: release.target,
          state: "running",
          candidateHash: target.candidateHash,
          deployVersion: target.deployVersion,
          verified: false,
          cause: "",
          faultInjected: "",
          requestedBy: decision.by,
          authorisedBy: decision.by,
          restores: target.deploymentId,
          url: target.url,
          createdAt: wireTime(),
          finishedAt: null,
          steps: steps([
            {
              stepId: "restore",
              label: "Start the verified release's image by digest on the release port",
              provider: "local-docker",
              movesTraffic: true,
            },
            {
              stepId: "verify",
              label: "Check the release port serves the verified release's fingerprint, health and smoke",
              provider: null,
              movesTraffic: false,
            },
          ]),
        });
        draft.thread.push({
          id: newId(),
          kind: "system",
          stageId: "release",
          author: decision.by,
          content:
            `Rolling back deploy version ${release.deployVersion} to deploy version ` +
            `${target.deployVersion}, candidate ${target.candidateHash.slice(0, 12)}.`,
          at: wireTime(),
          producedVersion: null,
        });
      });
      void carryOut(projectId, rollbackId, (draft, done) => {
        const rolledBack = draft.deployments.find((one) => one.id === deploymentId);
        if (rolledBack) rolledBack.state = "rolled-back";
        draft.currentRelease = verifiedFrom(done, target);
      });
      return started;
    },

    async openMonitoringWindow(projectId, window: MonitoringWindowInput = {}) {
      await sleep(FIXTURE_DELAY_MS);
      const current = readDeployment(projectId);
      const newest = current.deployments.find(
        (one) => one.target === current.releaseTarget && one.state !== "failed",
      );
      if (!newest || newest.state !== "succeeded" || !newest.verified || !newest.url) {
        refuse(
          `nothing verified serves this project on the ${current.releaseTarget} target to watch: ` +
            "no release has been verified, or the newest one is still running or waits on a " +
            "rollback decision",
        );
      }
      if (watching.has(newest.id)) {
        refuse(`deploy version ${newest.deployVersion} is being watched already`);
      }
      watching.add(newest.id);
      const opening = mutateDeployment(projectId, (draft) => {
        draft.watching = newest.id;
      });
      const rounds = window.rounds ?? 10;
      const interval = window.interval ?? 30;
      const opened = wireTime();
      void sleep(WINDOW_MS).then(() => {
        watching.delete(newest.id);
        mutateDeployment(projectId, (draft) => {
          draft.watching = null;
          const closed = wireTime();
          draft.monitoring = {
            version: newest.deployVersion,
            generatedAt: closed,
            deploymentId: newest.id,
            target: newest.target,
            urls: [newest.url ?? ""],
            source: `orchestrator HTTP probes every ${interval} s from this host`,
            windowStart: opened,
            windowEnd: closed,
            probeIntervalSeconds: interval,
            ruleId: "health-rule/1",
            thresholds: draft.monitoring?.thresholds ?? {
              degradedP95Ms: 2000,
              coldStartIdleSeconds: 900,
              coldStartFirstMs: 90000,
              minSamples: 3,
            },
            probes: [
              { probe: "GET /release.json", samples: rounds, ok: rounds, p50Ms: 39, p95Ms: 58, lastError: "" },
              { probe: "GET /", samples: rounds, ok: rounds, p50Ms: 36, p95Ms: 52, lastError: "" },
            ],
            states: [
              {
                state: "healthy",
                start: opened,
                end: closed,
                samples: rounds,
                evidence: "every probe answered, the fingerprint matched, p95 under 2000 ms",
              },
            ],
            currentState: "healthy",
            expectedCandidateHash: newest.candidateHash,
            fingerprintMatches: true,
            events: [],
            idleSeconds: null,
            idleFrom: null,
          };
          draft.feedback = {
            reportId: `feedback-${projectId}-v${newest.deployVersion}`,
            projectId,
            generatedAt: closed,
            deployVersion: newest.deployVersion,
            sourceReports: [`monitoring-report@${newest.deployVersion}`],
            items: [],
          };
        });
      });
      return opening;
    },

    async decideFeedback(projectId, itemId, decision: FeedbackDecisionInput) {
      await sleep(FIXTURE_DELAY_MS);
      const current = readDeployment(projectId);
      const report = current.feedback;
      if (!report) refuse("there is no feedback from production to decide on");
      const item = report.items.find((one) => one.id === itemId);
      if (!item) refuse(`feedback item ${itemId} was not found`);
      const earlier = current.feedbackDecisions.find((one) => one.itemId === itemId);
      if (earlier) {
        refuse(
          `this suggestion was ${earlier.decision} already` +
            (earlier.designVersion ? `, as design version ${earlier.designVersion}` : ""),
        );
      }
      const note = (decision.note ?? "").trim();
      if (decision.decision === "dismissed" && !note) {
        refuse("dismissing a suggestion needs a note saying why");
      }
      return mutateDeployment(projectId, (draft) => {
        // A change note opens the next design version; the demo's designs are at 2.
        const designVersion = decision.decision === "sent" ? nextDesignVersion(draft) : null;
        draft.feedbackDecisions.push({
          itemId,
          decision: decision.decision,
          by: decision.by,
          at: wireTime(),
          note: note || null,
          deployVersion: report.deployVersion ?? draft.deployVersion,
          designVersion,
        });
        draft.thread.push({
          id: newId(),
          kind: "system",
          stageId: "monitoring",
          author: "platform",
          content:
            decision.decision === "sent"
              ? `${decision.by} sent a suggestion to requirements as design version ` +
                `${designVersion}: ${item.suggestedRequirement}`
              : `${decision.by} dismissed a suggestion: ${note}`,
          at: wireTime(),
          producedVersion: null,
        });
      });
    },

    async sendFeedback(projectId, itemIds, actor) {
      await sleep(FIXTURE_DELAY_MS);
      const current = readDeployment(projectId);
      const report = current.feedback;
      if (!report) refuse("there is no feedback from production to decide on");
      const items = itemIds.map((itemId) => {
        const item = report.items.find((one) => one.id === itemId);
        if (!item) refuse(`feedback item ${itemId} was not found`);
        const earlier = current.feedbackDecisions.find((one) => one.itemId === itemId);
        if (earlier) {
          refuse(
            `this suggestion was ${earlier.decision} already` +
              (earlier.designVersion ? `, as design version ${earlier.designVersion}` : ""),
          );
        }
        return item;
      });
      return mutateDeployment(projectId, (draft) => {
        // One change note for all of them: one design version, one run.
        const designVersion = nextDesignVersion(draft);
        for (const item of items) {
          draft.feedbackDecisions.push({
            itemId: item.id,
            decision: "sent",
            by: actor.by,
            at: wireTime(),
            note: null,
            deployVersion: report.deployVersion ?? draft.deployVersion,
            designVersion,
          });
        }
        draft.thread.push({
          id: newId(),
          kind: "system",
          stageId: "monitoring",
          author: "platform",
          content:
            `${actor.by} sent ${items.length === 1 ? "a suggestion" : `${items.length} suggestions`} ` +
            `to requirements as design version ${designVersion}: ` +
            items.map((item) => item.suggestedRequirement).join("; "),
          at: wireTime(),
          producedVersion: null,
        });
      });
    },
  };
}

function createHttpApi(): DeploymentApi {
  const base = (projectId: string) => `/projects/${projectId}/deployment`;

  return {
    getDeployment: (projectId) => http.get<DeploySnapshot>(base(projectId)),
    getFile: (projectId, path, version) =>
      http.get<DeployFile>(`${base(projectId)}/files/${path}?version=${version}`),
    listTargets: (projectId) => http.get<ReleaseTargetOption[]>(`${base(projectId)}/targets`),
    chooseScope: (projectId, packages, by) =>
      http.post<DeploySnapshot>(`${base(projectId)}/scope`, {
        target: "generated",
        packages: packages.length > 0 ? packages : null,
        by,
      }),
    listLedger: (projectId, limit) =>
      http.get<DeploymentView[]>(`${base(projectId)}/ledger?limit=${limit}`),
    chooseTarget: (projectId, target, by) =>
      http.post<DeploySnapshot>(`${base(projectId)}/target`, { target, by }),
    choosePolicy: (projectId, policy) =>
      http.post<DeploySnapshot>(`${base(projectId)}/policy`, policy),
    run: (projectId) => http.post<DeploySnapshot>(`${base(projectId)}/run`, {}),
    continueRun: async (projectId, runId) => {
      await http.post(`/runs/${runId}/continue`);
      return http.get<DeploySnapshot>(base(projectId));
    },
    retryStage: (projectId, stageId) =>
      http.post<DeploySnapshot>(`${base(projectId)}/stages/${stageId}/retry`, {}),
    decideUpdate: (projectId, updateId, decision) =>
      http.post<DeploySnapshot>(
        `${base(projectId)}/updates/${encodeURIComponent(updateId)}/decision`,
        decision,
      ),
    submitDecision: (projectId, decision) =>
      http.post<DeploySnapshot>(`${base(projectId)}/decision`, decision),
    decideRollback: (projectId, deploymentId, decision) =>
      http.post<DeploySnapshot>(
        `${base(projectId)}/deployments/${encodeURIComponent(deploymentId)}/rollback/decision`,
        decision,
      ),
    releaseAgain: (projectId, deploymentId) =>
      http.post<DeploySnapshot>(
        `${base(projectId)}/deployments/${encodeURIComponent(deploymentId)}/retry`,
      ),
    openMonitoringWindow: (projectId, window = {}) =>
      http.post<DeploySnapshot>(`${base(projectId)}/monitoring/window`, window),
    decideFeedback: (projectId, itemId, decision) =>
      http.post<DeploySnapshot>(
        `${base(projectId)}/feedback/${encodeURIComponent(itemId)}/decision`,
        decision,
      ),
    sendFeedback: (projectId, itemIds, actor) =>
      http.post<DeploySnapshot>(`${base(projectId)}/feedback/send`, { itemIds, ...actor }),
  };
}

export function createDeploymentApi(): DeploymentApi {
  return isLive("deployment") ? createHttpApi() : createFixtureApi();
}

export const deploymentApi: DeploymentApi = createDeploymentApi();
