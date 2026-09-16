import { isLive } from "@/lib/env";
import { http } from "@/lib/http";
import { getProjectsSnapshot } from "@/entities/project";
import { BLANK_SEED, DESIGN_SEEDS } from "@/entities/design-seed";
import { CODE_STAGE_IDS, type CodeStageId } from "@/types/project";
import type {
  CodeApi,
  CodeDecisionInput,
  CodeFile,
  CodeSnapshot,
  PreviewState,
} from "./types";
import { buildCodeSnapshot } from "../fixtures/buildCodeSnapshot";
import { mutateCode, readCode } from "../fixtures/codeDb";

/**
 * Code Generation (C2) API seam.
 *
 * Fixtures answer until the feature is flipped live and the orchestrator
 * answers after; components cannot tell which, because both sides return the
 * same `CodeSnapshot`. Side effects live in here rather than in the UI, so the
 * real service reproduces them exactly: which changes cost a regeneration and
 * which do not is a rule about the phase, not a detail of either backend.
 */

const FIXTURE_DELAY_MS = 140;
/** How long each stage appears to take. Enough to watch, short enough to demo. */
const STAGE_MS = 900;

function sleep(ms: number) {
  return new Promise<void>((resolve) => window.setTimeout(resolve, ms));
}

function seedFor(projectId: string) {
  return DESIGN_SEEDS[projectId] ?? BLANK_SEED;
}

function designIsApproved(projectId: string): boolean {
  // From the project's own status rather than from the design feature: a
  // feature may not import another feature, and the status is the fact both
  // phases already agree on.
  const status = getProjectsSnapshot().find((p) => p.id === projectId)?.status;
  return status === "code" || status === "testing" || status === "deploy" || status === "complete";
}

/**
 * Walk the stages one at a time, then fill in what the run produced.
 *
 * The artefacts arrive together because the fixture has no model to wait for,
 * but the stages still complete in order, and a stage that has not completed
 * shows its pending panel rather than the content sitting behind it. That is
 * what keeps the demo honest: what the reader can see is exactly what the
 * stages claim.
 */
function runGeneration(projectId: string, version: number, arm: "rule" | "llm" | "merged") {
  const finished = buildCodeSnapshot(projectId, seedFor(projectId), "awaiting", 1);

  CODE_STAGE_IDS.forEach((id, index) => {
    window.setTimeout(
      () => {
        mutateCode(projectId, (draft) => {
          if (draft.codeVersion !== version) return; // superseded by a later run
          draft.stages[id] = {
            ...finished.stages[id],
            generatedFromVersion: version,
          };
          const next = CODE_STAGE_IDS[index + 1];
          if (next) draft.stages[next].status = "generating";

          if (id === "sprint-scope") draft.scope = applyScope(draft, finished.scope);
          if (id === "tech-stack") draft.techStack = keepSelection(draft, finished.techStack);
          if (id === "api-contract") {
            draft.contract = finished.contract
              ? { ...finished.contract, version, chosen: arm }
              : null;
            draft.diff = version > 1 ? emptyDiff(version) : null;
          }
          if (id === "contract-agreement") draft.agreement = finished.agreement;
          if (id === "build") draft.repository = finished.repository;
          if (id === "code-review") {
            draft.codeVersion = version;
            draft.generatedFromDesignVersion = draft.designVersion;
          }
        });
      },
      STAGE_MS * (index + 1),
    );
  });
}

/** Keep the reader's in and out decisions across a regeneration. */
function applyScope(draft: CodeSnapshot, fresh: CodeSnapshot["scope"]): CodeSnapshot["scope"] {
  if (!fresh) return null;
  const decided = new Map((draft.scope?.stories ?? []).map((story) => [story.id, story]));
  return {
    ...fresh,
    stories: fresh.stories.map((story) => {
      const before = decided.get(story.id);
      return before && before.decidedBy !== "system default"
        ? { ...story, inScope: before.inScope, decidedBy: before.decidedBy }
        : story;
    }),
  };
}

function keepSelection(
  draft: CodeSnapshot,
  fresh: CodeSnapshot["techStack"],
): CodeSnapshot["techStack"] {
  if (!fresh) return null;
  const before = draft.techStack;
  if (!before || before.selectedBy === "system default") return fresh;
  return { ...fresh, selectedId: before.selectedId, selectedBy: before.selectedBy };
}

function emptyDiff(version: number): CodeSnapshot["diff"] {
  return { fromVersion: version - 1, toVersion: version, added: [], removed: [], changed: [] };
}

function startRun(projectId: string, arm?: "rule" | "llm" | "merged"): CodeSnapshot {
  const snapshot = readCode(projectId);
  const version = snapshot.codeVersion + 1;
  const chosen = arm ?? snapshot.contract?.chosen ?? "rule";
  const next = mutateCode(projectId, (draft) => {
    draft.codeVersion = version;
    for (const id of CODE_STAGE_IDS) {
      if (id === "code-review") continue;
      draft.stages[id] = { ...draft.stages[id], status: "generating", error: null };
    }
    draft.stages["code-review"] = {
      ...draft.stages["code-review"],
      status: "pending",
      error: null,
    };
    draft.gate = { decision: null, history: draft.gate.decision ? [...draft.gate.history, draft.gate.decision] : draft.gate.history };
  });
  runGeneration(projectId, version, chosen);
  return next;
}

function createFixtureApi(): CodeApi {
  return {
    async getCode(projectId) {
      await sleep(FIXTURE_DELAY_MS);
      return readCode(projectId);
    },

    async getArchive() {
      await sleep(FIXTURE_DELAY_MS);
      // The demo's file bodies are placeholders, and an archive of them would
      // read as generated code.
      throw new Error("The demo keeps no generated files to download.");
    },

    async pushVersion(projectId, version) {
      await sleep(FIXTURE_DELAY_MS);
      const snapshot = readCode(projectId);
      const repository = snapshot.repository;
      if (!repository) throw new Error(`code version ${version} has no generated code to push`);
      if (repository.repository) {
        throw new Error(`code version ${version} is on ${repository.repository.url} already`);
      }
      return mutateCode(projectId, (draft) => {
        draft.repository!.notPushedReason = null;
        draft.repository!.repository = {
          provider: "github",
          owner: "demo",
          name: projectId,
          defaultBranch: "main",
          commitSha: "0".repeat(40),
          url: `https://github.com/demo/${projectId}`,
          branch: `code/v${version}`,
        };
      });
    },

    async getOpenApi(projectId, version) {
      await sleep(FIXTURE_DELAY_MS);
      const contract = readCode(projectId).contract?.contract;
      if (!contract) throw new Error("this project has no API contract yet");
      // The demo's endpoints as paths and operations: the server translates
      // the stored contract in full, and the demo says only what it has.
      const paths: Record<string, Record<string, unknown>> = {};
      for (const endpoint of contract.endpoints) {
        paths[endpoint.path] = {
          ...paths[endpoint.path],
          [endpoint.method.toLowerCase()]: { operationId: endpoint.id, summary: endpoint.summary },
        };
      }
      return {
        openapi: "3.1.0",
        info: { title: projectId, version: `${version}.0.0` },
        paths,
      };
    },

    async getFile(projectId, path, version) {
      await sleep(FIXTURE_DELAY_MS);
      const snapshot = readCode(projectId);
      const row = snapshot.repository?.manifest.find((entry) => entry.path === path);
      if (!row) throw new Error(`${path} was not generated`);
      return {
        path,
        version: version ?? snapshot.codeVersion,
        // The demo has no real file bodies and does not pretend to: it says so
        // where a body would be, rather than showing invented source that
        // would read as generated output.
        content:
          `// ${path}\n` +
          `// ${row.summary}\n` +
          `// Written by the ${row.generator} generator from the ${row.arm} arm.\n` +
          (row.implements.length
            ? `// Implements: ${row.implements.join(", ")}\n`
            : "") +
          "//\n// The demo does not carry file bodies. Generate with the live\n" +
          "// backend to read what was actually written.\n",
      } satisfies CodeFile;
    },

    async generate(projectId) {
      await sleep(FIXTURE_DELAY_MS);
      if (!designIsApproved(projectId)) {
        throw new Error(
          "this project's design has not been approved, so there is nothing settled to generate code from",
        );
      }
      return startRun(projectId);
    },

    async setStoryScope(projectId, storyId, inScope, by) {
      await sleep(FIXTURE_DELAY_MS);
      mutateCode(projectId, (draft) => {
        if (!draft.scope) return;
        draft.scope.stories = draft.scope.stories.map((story) =>
          story.id === storyId ? { ...story, inScope, decidedBy: by } : story,
        );
      });
      return startRun(projectId);
    },

    async planNextSprint(projectId, by) {
      await sleep(FIXTURE_DELAY_MS);
      // The server's rule, on what the fixture snapshot previews: nothing to
      // plan is refused rather than run.
      let planned = 0;
      mutateCode(projectId, (draft) => {
        const next = draft.nextSprint;
        if (!draft.scope || !next || next.stories.length === 0) return;
        const taken = new Set(next.stories.map((story) => story.id));
        planned = taken.size;
        draft.scope.stories = draft.scope.stories.map((story) =>
          taken.has(story.id)
            ? { ...story, inScope: true, sprint: next.number, decidedBy: by }
            : story,
        );
        draft.nextSprint = null;
      });
      if (!planned) {
        throw new Error("there is no next sprint to plan from this project's sprint plan");
      }
      return startRun(projectId);
    },

    async selectStack(projectId, stackId, by) {
      await sleep(FIXTURE_DELAY_MS);
      // No run: nothing downstream reads the choice, so regenerating would
      // spend a run to produce identical code.
      return mutateCode(projectId, (draft) => {
        if (!draft.techStack) return;
        if (!draft.techStack.candidates.some((candidate) => candidate.id === stackId)) return;
        draft.techStack.selectedId = stackId;
        draft.techStack.selectedBy = by;
      });
    },

    async chooseArm(projectId, arm, by) {
      await sleep(FIXTURE_DELAY_MS);
      mutateCode(projectId, (draft) => {
        draft.thread = [
          ...draft.thread,
          {
            id: `code-thread-arm-${draft.codeVersion + 1}`,
            kind: "user_note",
            stageId: "api-contract",
            author: by,
            content: `Generating from the ${arm} arm.`,
            at: new Date().toISOString(),
            producedVersion: draft.codeVersion + 1,
          },
        ];
      });
      return startRun(projectId, arm);
    },

    // The demo's runs never stop, so there is never a stopped run to go on with.
    async continueRun() {
      throw new Error("The demo never stops a run, so there is nothing to continue.");
    },

    async retryStage(projectId, stageId) {
      await sleep(FIXTURE_DELAY_MS);
      const finished = buildCodeSnapshot(projectId, seedFor(projectId), "awaiting", 1);
      const next = mutateCode(projectId, (draft) => {
        draft.stages[stageId] = { ...draft.stages[stageId], status: "generating", error: null };
      });
      window.setTimeout(() => {
        mutateCode(projectId, (draft) => {
          draft.stages[stageId] = {
            ...finished.stages[stageId],
            generatedFromVersion: draft.codeVersion,
          };
        });
      }, STAGE_MS);
      return next;
    },

    async submitDecision(projectId, decision) {
      await sleep(FIXTURE_DELAY_MS);
      if (decision.kind === "changes" && !decision.note?.trim()) {
        throw new Error("requesting changes needs a note saying what to change");
      }
      const recorded = mutateCode(projectId, (draft) => {
        draft.gate = {
          decision: {
            kind: decision.kind,
            at: new Date().toISOString(),
            by: decision.by,
            version: draft.codeVersion,
            note: decision.note ?? null,
          },
          history: draft.gate.history,
        };
        draft.thread = [
          ...draft.thread,
          {
            id: `code-thread-decision-${draft.codeVersion}`,
            kind: "system",
            stageId: "code-review",
            author: decision.by,
            content:
              decision.kind === "approved"
                ? "Approved the code. Testing and Security can start."
                : `Requested changes: ${decision.note}`,
            at: new Date().toISOString(),
            producedVersion: null,
          },
        ];
      });
      return decision.kind === "changes" ? startRun(projectId) : recorded;
    },

    // The fixtures have no processes to run, and saying so is the honest
    // answer: a fake "running" state with a link to nothing would be the one
    // thing a preview must never be.
    async getPreview() {
      await sleep(FIXTURE_DELAY_MS);
      return {
        status: "unavailable",
        reason:
          "previews run the generated app on the server, so they need the live backend rather than these fixtures",
      } satisfies PreviewState;
    },
    async startPreview() {
      throw new Error(
        "previews need the live backend: there is no generated code on disk in fixtures mode",
      );
    },
    async stopPreview() {
      /* nothing is running */
    },
  };
}

function base(projectId: string) {
  return `/projects/${projectId}/code`;
}

function createHttpApi(): CodeApi {
  return {
    getCode: (projectId) => http.get<CodeSnapshot>(base(projectId)),
    getOpenApi: (projectId, version) =>
      http.get<Record<string, unknown>>(`${base(projectId)}/openapi?version=${version}`),
    getArchive: (projectId, version) =>
      http.get<Blob>(`${base(projectId)}/archive?version=${version}`, { as: "blob" }),
    pushVersion: (projectId, version) =>
      http.post<CodeSnapshot>(`${base(projectId)}/push`, { version }),
    getFile: (projectId, path, version) =>
      http.get<CodeFile>(
        `${base(projectId)}/files/${path}${version ? `?version=${version}` : ""}`,
      ),
    generate: (projectId, supersede = false) =>
      http.post<CodeSnapshot>(`${base(projectId)}/generate`, { supersede }),
    setStoryScope: (projectId, storyId, inScope, by, supersede = false) =>
      http.post<CodeSnapshot>(`${base(projectId)}/scope/${storyId}`, { inScope, by, supersede }),
    planNextSprint: (projectId, by, supersede = false) =>
      http.post<CodeSnapshot>(`${base(projectId)}/sprints/next`, { by, supersede }),
    selectStack: (projectId, stackId, by) =>
      http.post<CodeSnapshot>(`${base(projectId)}/stack/select`, { stackId, by }),
    chooseArm: (projectId, arm, by, supersede = false) =>
      http.post<CodeSnapshot>(`${base(projectId)}/arm`, { arm, by, supersede }),
    continueRun: async (projectId, runId) => {
      await http.post(`/runs/${runId}/continue`);
      return http.get<CodeSnapshot>(base(projectId));
    },
    retryStage: (projectId, stageId: CodeStageId) =>
      http.post<CodeSnapshot>(`${base(projectId)}/stages/${stageId}/retry`, {}),
    submitDecision: (projectId, decision: CodeDecisionInput) =>
      http.post<CodeSnapshot>(`${base(projectId)}/decision`, decision),
    getPreview: (projectId) => http.get<PreviewState>(`${base(projectId)}/preview`),
    startPreview: (projectId) => http.post<PreviewState>(`${base(projectId)}/preview`, {}),
    stopPreview: (projectId) => http.delete<void>(`${base(projectId)}/preview`),
  };
}

export function createCodeApi(): CodeApi {
  return isLive("code-generation") ? createHttpApi() : createFixtureApi();
}

export const codeApi: CodeApi = createCodeApi();
