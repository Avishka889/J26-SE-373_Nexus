import { getProjectsSnapshot } from "@/entities/project";
import { isLive } from "@/lib/env";
import { http } from "@/lib/http";
import { TEST_STAGE_IDS, type TestStageId } from "@/types/project";
import type {
  ActorInput,
  FindingDecisionInput,
  FailingTestDecisionInput,
  HealDecisionInput,
  ProposalDecisionInput,
  TestDecisionInput,
  TestFile,
  TestSnapshot,
  TestTarget,
  TestingApi,
} from "./types";
import { getTestingSnapshot } from "../fixtures/legacyDemo";
import { mutateTesting, readTesting } from "../fixtures/testingDb";

/**
 * Testing and Security (C3) API seam.
 *
 * Fixtures answer until the feature is flipped live and the orchestrator
 * answers after; components cannot tell which, because both sides return the
 * same `TestSnapshot`.
 *
 * This replaces a client that called seven routes the orchestrator does not
 * have, against a vocabulary of its own invention. The demo worked and the
 * live path could never have, which is the failure mode a seam is supposed to
 * prevent rather than hide: whichever side answers, the shape is the one the
 * schema generates.
 *
 * Side effects live here rather than in the UI, so the real service reproduces
 * them exactly. Which decisions cost a run and which are overlays is a rule
 * about the phase, not a detail of either backend.
 */

const FIXTURE_DELAY_MS = 140;
/** How long each stage appears to take. Enough to watch, short enough to demo. */
const STAGE_MS = 700;

function sleep(ms: number) {
  return new Promise<void>((resolve) => window.setTimeout(resolve, ms));
}

function codeIsApproved(projectId: string): boolean {
  // From the project's own status rather than from the code feature: a feature
  // may not import another feature, and the status is the fact both phases
  // already agree on.
  const status = getProjectsSnapshot().find((one) => one.id === projectId)?.status;
  return status === "testing" || status === "deploy" || status === "complete";
}

function createFixtureApi(): TestingApi {
  async function getTestFile(_projectId: string, path: string, version: number) {
    await sleep(FIXTURE_DELAY_MS);
    const content = getTestingSnapshot().testFileContents[path];
    if (content === undefined) throw new Error(`${path} is not one of the demo's test files.`);
    return { path, version, content };
  }

  async function walkStages(projectId: string) {
    // Each stage completes in turn, so a reader watching the stepper sees the
    // phase progress rather than a spinner that becomes a result.
    for (const id of TEST_STAGE_IDS) {
      await sleep(STAGE_MS);
      mutateTesting(projectId, (draft) => {
        draft.stages[id] = {
          ...draft.stages[id],
          status: "complete",
          generatedFromVersion: draft.testVersion,
        };
      });
    }
    // A finished run has measured whatever the code is at now. Without this a
    // fix applied here could never be re-verified, because nothing would ever
    // have tested the version carrying it.
    mutateTesting(projectId, (draft) => {
      draft.testedCodeVersion = draft.codeVersion;
      draft.codeMovedOn = false;
    });
  }

  return {
    getTestFile,

    async getTesting(projectId) {
      await sleep(FIXTURE_DELAY_MS);
      return readTesting(projectId);
    },

    async listTargets(_projectId) {
      await sleep(FIXTURE_DELAY_MS);
      // The same two the component checks in, so the demo offers what a live
      // deployment offers rather than a shorter list of its own.
      return [
        {
          id: "generated",
          label: "The generated application",
          stack: "node",
          detail: "The repository this project's code phase produced.",
        },
        {
          id: "sample:java-sample",
          label: "Java sample",
          stack: "java",
          detail: "A checked in sample with seeded weaknesses.",
        },
      ];
    },

    async chooseTarget(projectId, target, _by) {
      await sleep(FIXTURE_DELAY_MS);
      return mutateTesting(projectId, (draft) => {
        draft.target = target;
      });
    },

    async run(projectId) {
      await sleep(FIXTURE_DELAY_MS);
      if (!codeIsApproved(projectId)) {
        throw new Error(
          "This project's code has not been approved, so testing it would measure a build " +
            "nobody agreed to ship.",
        );
      }
      const started = mutateTesting(projectId, (draft) => {
        draft.testVersion = draft.testVersion || 1;
        draft.stages["test-generation"] = {
          ...draft.stages["test-generation"],
          status: "generating",
        };
      });
      void walkStages(projectId);
      return started;
    },

    // The demo's runs never stop, so there is never a stopped run to go on with.
    async continueRun() {
      throw new Error("The demo never stops a run, so there is nothing to continue.");
    },

    async retryStage(projectId, stageId) {
      await sleep(FIXTURE_DELAY_MS);
      return mutateTesting(projectId, (draft) => {
        draft.stages[stageId] = { ...draft.stages[stageId], status: "generating", error: null };
      });
    },

    async decideFinding(projectId, findingId, decision) {
      await sleep(FIXTURE_DELAY_MS);
      requireNote(decision.decision === "dismissed", decision.note, "security finding");
      return mutateTesting(projectId, (draft) => {
        const finding = draft.validation?.findings.find((one) => one.id === findingId);
        if (finding) finding.status = decision.decision === "accepted" ? "open" : "dismissed";
        if (draft.validation) {
          draft.validation.openFindings = draft.validation.findings.filter(
            (one) => one.status === "open",
          ).length;
          draft.openFindings = draft.validation.openFindings;
        }
      });
    },

    async decideProposal(projectId, proposalId, decision) {
      await sleep(FIXTURE_DELAY_MS);
      requireNote(decision.decision === "dismissed", decision.note, "proposed fix");
      return mutateTesting(projectId, (draft) => {
        const proposal = draft.remediation?.proposals.find((one) => one.id === proposalId);
        if (proposal) {
          proposal.state = decision.decision === "accepted" ? "accepted" : "dismissed";
          proposal.decidedBy = decision.by;
          proposal.decisionNote = decision.note ?? "";
          proposal.awaitingDecision = false;
        }
        if (draft.remediation) {
          draft.remediation.awaitingDecision = draft.remediation.proposals.filter(
            (one) => one.state === "proposed",
          ).length;
          draft.awaitingDecision = draft.remediation.awaitingDecision;
        }
      });
    },

    async applyProposal(projectId, proposalId, actor) {
      await sleep(FIXTURE_DELAY_MS);
      return mutateTesting(projectId, (draft) => {
        const proposal = draft.remediation?.proposals.find((one) => one.id === proposalId);
        if (!proposal) throw new Error("No such proposed fix.");
        if (proposal.state !== "accepted") {
          throw new Error(
            "This fix has not been accepted. A patch reaches the code because a person " +
              "decided it should, not because it was proposed.",
          );
        }
        // An ordinary new code version, which is what the server makes of it,
        // and which leaves the tests describing a version that has moved on.
        const next = draft.codeVersion + 1;
        proposal.state = "applied";
        proposal.appliedCodeVersion = next;
        proposal.decidedBy = actor.by;
        draft.codeVersion = next;
        draft.codeMovedOn = draft.testedCodeVersion > 0 && next > draft.testedCodeVersion;
      });
    },

    async reverifyProposal(projectId, proposalId, _actor) {
      await sleep(FIXTURE_DELAY_MS);
      return mutateTesting(projectId, (draft) => {
        const proposal = draft.remediation?.proposals.find((one) => one.id === proposalId);
        if (!proposal?.appliedCodeVersion) {
          throw new Error(
            "This fix has not been applied, so there is no second version to compare against.",
          );
        }
        if (draft.testedCodeVersion !== proposal.appliedCodeVersion) {
          throw new Error(
            `Nothing has tested code version ${proposal.appliedCodeVersion} yet, which is the ` +
              "version carrying this fix. Start a testing run, then re-verify.",
          );
        }
        // The arithmetic the server gets from two stored reports. The guard
        // that matters lives on the contract, where `worsened` is computed
        // from the two snapshots rather than asserted.
        const passed = draft.tests?.passed ?? 0;
        const failed = draft.tests?.failed ?? 0;
        const mutationScore = draft.tests?.mutation?.score ?? null;
        proposal.reverification = {
          before: {
            openFindings: draft.openFindings + 1,
            testsPassed: passed,
            testsFailed: failed,
            mutationScore,
          },
          after: {
            openFindings: draft.openFindings,
            testsPassed: passed,
            testsFailed: failed,
            mutationScore,
          },
          beforeRunId: "",
          afterRunId: "",
          findingId: proposal.findingId,
          stillRaisedAs: [],
          findingsClosed: 1,
          testsBroken: 0,
          worsened: false,
          findingClosed: true,
          verified: true,
        };
        proposal.state = "verified";
      });
    },

    async decideHeal(projectId, _testId, _decision) {
      await sleep(FIXTURE_DELAY_MS);
      // An overlay on the server, so the heal report itself does not move.
      return readTesting(projectId);
    },

    async decideTest(projectId, testId, decision) {
      await sleep(FIXTURE_DELAY_MS);
      if (decision.decision !== "restored" && !decision.note?.trim()) {
        throw new Error(
          "Quarantining a test, or asking for it to be written again, needs a note saying why.",
        );
      }
      // The server's record of it, newest per test; the file edit is the server's.
      return mutateTesting(projectId, (draft) => {
        draft.healDecisions = [
          ...(draft.healDecisions ?? []).filter((one) => one.testId !== testId),
          {
            testId,
            decision: decision.decision,
            by: decision.by,
            at: new Date().toISOString(),
            note: decision.note ?? "",
          },
        ];
      });
    },

    async submitDecision(projectId, decision) {
      await sleep(FIXTURE_DELAY_MS);
      if (decision.kind === "changes" && !decision.note?.trim()) {
        throw new Error("Requesting changes needs a note saying what to change.");
      }
      return mutateTesting(projectId, (draft) => {
        draft.gate = {
          decision: {
            kind: decision.kind,
            by: decision.by,
            at: new Date().toISOString(),
            version: draft.testVersion,
            note: decision.note ?? "",
          },
          history: draft.gate.history,
        };
      });
    },
  };
}

function requireNote(needed: boolean, note: string | undefined, what: string) {
  if (needed && !note?.trim()) {
    throw new Error(`Dismissing a ${what} needs a note saying why.`);
  }
}

function createHttpApi(): TestingApi {
  const base = (projectId: string) => `/projects/${projectId}/testing`;

  return {
    getTesting: (projectId) => http.get<TestSnapshot>(base(projectId)),
    getTestFile: (projectId, path, version) =>
      http.get<TestFile>(`/projects/${projectId}/code/files/${path}?version=${version}`),
    listTargets: (projectId) => http.get<TestTarget[]>(`${base(projectId)}/targets`),
    chooseTarget: (projectId, target: string, by: string) =>
      http.post<TestSnapshot>(`${base(projectId)}/target`, { target, by }),
    run: (projectId) => http.post<TestSnapshot>(`${base(projectId)}/run`, {}),
    continueRun: async (projectId, runId) => {
      await http.post(`/runs/${runId}/continue`);
      return http.get<TestSnapshot>(base(projectId));
    },
    retryStage: (projectId, stageId: TestStageId) =>
      http.post<TestSnapshot>(`${base(projectId)}/stages/${stageId}/retry`, {}),
    decideFinding: (projectId, findingId, decision: FindingDecisionInput) =>
      http.post<TestSnapshot>(
        `${base(projectId)}/findings/${encodeURIComponent(findingId)}/decision`,
        decision,
      ),
    decideProposal: (projectId, proposalId, decision: ProposalDecisionInput) =>
      http.post<TestSnapshot>(
        `${base(projectId)}/remediation/${encodeURIComponent(proposalId)}/decision`,
        decision,
      ),
    decideHeal: (projectId, testId, decision: HealDecisionInput) =>
      http.post<TestSnapshot>(
        `${base(projectId)}/heals/${encodeURIComponent(testId)}/decision`,
        decision,
      ),
    decideTest: (projectId, testId, decision: FailingTestDecisionInput) =>
      http.post<TestSnapshot>(
        `${base(projectId)}/tests/${encodeURIComponent(testId)}/decision`,
        decision,
      ),
    applyProposal: (projectId, proposalId, actor: ActorInput) =>
      http.post<TestSnapshot>(
        `${base(projectId)}/remediation/${encodeURIComponent(proposalId)}/apply`,
        actor,
      ),
    reverifyProposal: (projectId, proposalId, actor: ActorInput) =>
      http.post<TestSnapshot>(
        `${base(projectId)}/remediation/${encodeURIComponent(proposalId)}/reverify`,
        actor,
      ),
    submitDecision: (projectId, decision: TestDecisionInput) =>
      http.post<TestSnapshot>(`${base(projectId)}/decision`, decision),
  };
}

export function createTestingApi(): TestingApi {
  return isLive("testing") ? createHttpApi() : createFixtureApi();
}

export const testingApi: TestingApi = createTestingApi();
