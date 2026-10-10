import { isLive } from "@/lib/env";
import { getProjectsSnapshot, projectsApi } from "@/entities/project";
import { http } from "@/lib/http";
import { DESIGN_STAGE_IDS, type DesignStageId } from "@/types/project";
import type { DesignSnapshot, GateDecisionInput, RequirementsApi } from "./types";
import {
  appendThread,
  mutateDesign,
  readDesign,
  recomputeCoverage,
  stageSummary,
  demoStamp,
} from "../fixtures/designDb";
import { deriveSeedFromInput } from "../fixtures/deriveFromInput";
import { DESIGN_SEEDS } from "@/entities/design-seed";
import type { ProjectDesignSeed } from "@/entities/design-seed";

/**
 * Requirements and Design (C1) API seam.
 *
 * Fixtures answer today and the orchestrator answers later; components cannot
 * tell which, because both sides return the same `DesignSnapshot`. Side effects
 * live in here rather than in the UI, so the real service can reproduce them
 * exactly.
 */

const FIXTURE_DELAY_MS = 140;

function sleep(ms: number) {
  return new Promise<void>((resolve) => window.setTimeout(resolve, ms));
}

/**
 * The demo has no clock of its own, and the wall clock would make fixture output
 * differ every run. Timestamps advance from the seeded moment instead, and that
 * moment comes from the builder so a live edit never reads as older than the
 * artifacts it is editing.
 */
let minutesElapsed = 20;
function stamp(): string {
  minutesElapsed += 7;
  return demoStamp(minutesElapsed);
}

/**
 * The artifacts that are regenerated when the requirements change.
 *
 * Design Review is not one of them. It is a view over the other stages plus the
 * decision, not an artifact of its own, so putting it in a generating state
 * would hide the very decision a person had just recorded.
 */
const regeneratedStages: DesignStageId[] = DESIGN_STAGE_IDS.filter(
  (id) => id !== "requirements" && id !== "design-review",
);

/** How long each stage appears to take. Enough to watch, short enough to demo. */
const STAGE_MS = 1400;

function projectName(projectId: string): string {
  return getProjectsSnapshot().find((p) => p.id === projectId)?.name ?? "App";
}

/**
 * Put a derived design into the snapshot without touching stage state.
 *
 * The artifacts arrive all at once because the fixture has no model to wait for,
 * but the stages still complete one at a time, and a stage that has not completed
 * shows its pending panel rather than the content sitting behind it. That keeps
 * the run honest: what the reader can see is exactly what the stages claim.
 */
function fillFromSeed(draft: DesignSnapshot, seed: ProjectDesignSeed) {
  draft.appName = seed.appName;
  draft.requirements = structuredClone(seed.requirements);
  draft.assumptions = structuredClone(seed.assumptions);
  draft.questions = structuredClone(seed.questions).map(({ presetAnswer: _preset, ...rest }) => rest);
  draft.graph = { nodes: structuredClone(seed.nodes), edges: structuredClone(seed.edges), changedNodeIds: [] };
  draft.architecture = structuredClone(seed.architecture);
  draft.uml = { useCases: structuredClone(seed.useCases), diagrams: structuredClone(seed.diagrams) };
  draft.wireframes = { flows: structuredClone(seed.flows), coverage: [] };
  draft.sprint = structuredClone(seed.sprint);
  recomputeCoverage(draft);
}

/**
 * Run the design generation, one stage at a time.
 *
 * This is the only thing that advances the design during a run, which is what
 * makes the snapshot the single source of truth for status. It replaces a client
 * side timer that walked `reqPhase` through eight stages with no backend
 * involvement: that timer could not agree with the artifact it was describing, so
 * a new project showed eight green chevrons, "Ready for review", the decision bar
 * and a "Generating Architecture Graph" pill at the same moment.
 *
 * The project record is written twice, at the two transitions that really happen,
 * rather than eight times on a ladder.
 */
function runGeneration(projectId: string) {
  DESIGN_STAGE_IDS.forEach((id, index) => {
    window.setTimeout(
      () => {
        mutateDesign(projectId, (draft) => {
          // A run that has been superseded leaves this stage alone: the snapshot
          // it belongs to is gone.
          if (draft.stages[id].status === "complete") return;
          const at = stamp();
          draft.stages[id].status = "complete";
          draft.stages[id].generatedFromVersion = draft.requirementsVersion;
          draft.stages[id].generatedAt = at;
          draft.stages[id].summary = stageSummary(id, draft);
          appendThread(
            draft,
            { kind: "stage_summary", stageId: id, author: "Design agent", content: draft.stages[id].summary ?? "" },
            at,
          );

          const next = DESIGN_STAGE_IDS[index + 1];
          if (next) draft.stages[next].status = "generating";
          recomputeCoverage(draft);
        });

        // The server's rule, as the live list reports it: the design's stages
        // carry 80 of its 100, and the design is a quarter of the whole.
        const design = Math.round(((index + 1) / DESIGN_STAGE_IDS.length) * 80);
        void projectsApi.update(projectId, {
          ...(index === DESIGN_STAGE_IDS.length - 1
            ? { reqPhase: "design-review" as const, status: "design" as const }
            : {}),
          progress: Math.round(design / 4),
          phaseProgress: { design, code: 0, testing: 0, deployment: 0 },
        });
      },
      STAGE_MS * (index + 1),
    );
  });
}

function createFixtureApi(): RequirementsApi {
  const api: RequirementsApi = {
    async applyAnswers(projectId) {
      const answered = readDesign(projectId).questions.filter((question) => question.answer);
      const note =
        "Answers to the design's questions:\n" +
        answered.map((question) => `- ${question.question} ${question.answer}`).join("\n");
      return api.submitChange(projectId, note, "You");
    },

    async getDesign(projectId) {
      await sleep(FIXTURE_DELAY_MS);
      return readDesign(projectId);
    },

    // The demo's runs never pause on their questions, so there is nothing to
    // continue from.
    async continueFromQuestions(projectId) {
      await sleep(FIXTURE_DELAY_MS);
      return readDesign(projectId);
    },

    async startDesignRun(projectId, text, files = []) {
      await sleep(FIXTURE_DELAY_MS);

      // Content for a project the demo has no authored design for. Read from the
      // input, with low confidence and stated assumptions, so a completed stage
      // holds something a reader can check instead of nothing.
      const derived = DESIGN_SEEDS[projectId]
        ? null
        : deriveSeedFromInput(projectName(projectId), text);

      const started = mutateDesign(projectId, (draft) => {
        draft.requirementsVersion = 1;
        if (derived) fillFromSeed(draft, derived);
        // Only the first stage is generating. The rest stay pending, because
        // claiming a wireframe is being generated before the requirements have
        // been read would be the same lie in a smaller font.
        draft.stages.requirements.status = "generating";
        appendThread(
          draft,
          { kind: "user_note", stageId: null, author: "You", content: text },
          stamp(),
        );
      });

      // The stack is proposed and chosen in Code Generation, so this never
      // touches techStack.
      await projectsApi.update(projectId, {
        requirementText: text,
        files,
        reqPhase: "requirements",
        status: "analyzing",
        // Nothing has been generated yet.
        progress: 0,
        phaseProgress: { design: 0, code: 0, testing: 0, deployment: 0 },
      });

      runGeneration(projectId);
      return started;
    },

    async startOver(projectId) {
      await sleep(FIXTURE_DELAY_MS);
      // The server's start over: every stage again, one at a time.
      const started = mutateDesign(projectId, (draft) => {
        for (const id of DESIGN_STAGE_IDS) {
          draft.stages[id].status = "pending";
          draft.stages[id].error = null;
        }
        draft.stages.requirements.status = "generating";
      });
      runGeneration(projectId);
      return started;
    },

    async editRequirement(projectId, requirementId, text) {
      await sleep(FIXTURE_DELAY_MS);
      return mutateDesign(projectId, (draft) => {
        const found = draft.requirements.find((r) => r.id === requirementId);
        if (!found) return;
        found.text = text;
        // Marked as corrected, not regenerated. Only a change note rebuilds the
        // design, and the UI says so where the edit happens.
        found.adjusted = true;
      });
    },

    async editAssumption(projectId, assumptionId, text) {
      await sleep(FIXTURE_DELAY_MS);
      return mutateDesign(projectId, (draft) => {
        const found = draft.assumptions.find((a) => a.id === assumptionId);
        if (!found) return;
        found.text = text;
        found.edited = true;
      });
    },

    async dismissAssumption(projectId, assumptionId, dismissed) {
      await sleep(FIXTURE_DELAY_MS);
      return mutateDesign(projectId, (draft) => {
        const found = draft.assumptions.find((a) => a.id === assumptionId);
        if (found) found.dismissed = dismissed;
      });
    },

    async answerQuestion(projectId, questionId, answer) {
      await sleep(FIXTURE_DELAY_MS);
      return mutateDesign(projectId, (draft) => {
        const found = draft.questions.find((q) => q.id === questionId);
        if (!found) return;
        const at = stamp();
        found.answer = answer;
        found.answeredAt = at;
        // The answer belongs in the thread as well: that is where the
        // conversation about these requirements lives.
        appendThread(
          draft,
          {
            kind: "answer",
            stageId: "requirements",
            author: "You",
            content: `${found.question}\n${answer}`,
          },
          at,
        );
      });
    },

    async selectArchitecture(projectId, candidateId, by) {
      await sleep(FIXTURE_DELAY_MS);
      return mutateDesign(projectId, (draft) => {
        // Nothing to select when nothing was scored.
        if (!draft.architecture?.candidates.some((c) => c.id === candidateId)) return;
        draft.architecture.selectedCandidateId = candidateId;
        draft.architecture.selectedAt = stamp();
        draft.architecture.selectedBy = by;
      });
    },

    async renameGraphNode(projectId, nodeId, label) {
      await sleep(FIXTURE_DELAY_MS);
      return mutateDesign(projectId, (draft) => {
        const node = draft.graph.nodes.find((n) => n.id === nodeId);
        if (!node) return;
        node.label = label;
        node.changedInVersion = draft.requirementsVersion;
        if (!draft.graph.changedNodeIds.includes(nodeId)) {
          draft.graph.changedNodeIds = [...draft.graph.changedNodeIds, nodeId];
        }
        // Nothing else to update: the domain model and the diagrams are
        // projections over this graph, so they follow on their own.
      });
    },

    async requestWireframeRefinement(projectId, flowId, note) {
      await sleep(FIXTURE_DELAY_MS);
      return mutateDesign(projectId, (draft) => {
        const flow = draft.wireframes.flows.find((f) => f.id === flowId);
        if (!flow) return;
        flow.pendingRefinement = true;
        flow.refinementNote = note;
        appendThread(
          draft,
          {
            kind: "user_note",
            stageId: "wireframes",
            author: "You",
            content: `Refinement for ${flow.name}: ${note}`,
          },
          stamp(),
        );
      });
    },

    async submitChange(projectId, note, by) {
      await sleep(FIXTURE_DELAY_MS);
      const next = mutateDesign(projectId, (draft) => {
        const at = stamp();
        draft.requirementsVersion += 1;
        appendThread(
          draft,
          {
            kind: "user_note",
            stageId: "requirements",
            author: by,
            content: note,
            producedVersion: draft.requirementsVersion,
          },
          at,
        );

        // Which stages a wording change really affects is not knowable without a
        // dependency graph the service does not have, so everything downstream
        // of Requirements Analysis regenerates. Outdated stays a computed
        // comparison of versions rather than a stored flag.
        draft.stages.requirements.generatedFromVersion = draft.requirementsVersion;
        draft.stages.requirements.generatedAt = at;
        // The review reads the others live, so it moves to the new version with
        // them rather than being marked stale against itself.
        draft.stages["design-review"].generatedFromVersion = draft.requirementsVersion;
        draft.stages["design-review"].generatedAt = at;
        for (const id of regeneratedStages) {
          draft.stages[id].status = "generating";
          draft.stages[id].error = null;
        }
        // A decision covers the version it was given for, and nothing later.
        if (draft.gate.decision) {
          draft.gate.history = [...draft.gate.history, draft.gate.decision];
          draft.gate.decision = null;
        }
      });

      // The regeneration lands stage by stage, the way a real run would.
      regeneratedStages.forEach((id, i) => {
        window.setTimeout(
          () => {
            mutateDesign(projectId, (draft) => {
              const at = stamp();
              draft.stages[id].status = "complete";
              draft.stages[id].generatedFromVersion = draft.requirementsVersion;
              draft.stages[id].generatedAt = at;
              draft.stages[id].summary = stageSummary(id, draft);
              appendThread(
                draft,
                {
                  kind: "stage_summary",
                  stageId: id,
                  author: "Design agent",
                  content: stageSummary(id, draft),
                },
                at,
              );
            });
          },
          700 * (i + 1),
        );
      });

      return next;
    },

    // The demo's runs never stop, so there is never a stopped run to go on with.
    async continueRun() {
      throw new Error("The demo never stops a run, so there is nothing to continue.");
    },

    async retryStage(projectId, stageId) {
      await sleep(FIXTURE_DELAY_MS);
      const next = mutateDesign(projectId, (draft) => {
        draft.stages[stageId].status = "generating";
        draft.stages[stageId].error = null;
      });
      window.setTimeout(() => {
        mutateDesign(projectId, (draft) => {
          const at = stamp();
          draft.stages[stageId].status = "complete";
          draft.stages[stageId].generatedFromVersion = draft.requirementsVersion;
          draft.stages[stageId].generatedAt = at;
          draft.stages[stageId].summary = stageSummary(stageId, draft);
        });
      }, 1200);
      return next;
    },

    async submitGateDecision(projectId, decision: GateDecisionInput) {
      await sleep(FIXTURE_DELAY_MS);
      return mutateDesign(projectId, (draft) => {
        const at = stamp();
        draft.gate.decision = {
          kind: decision.kind,
          at,
          by: decision.by,
          version: draft.requirementsVersion,
          note: decision.note ?? null,
        };
        appendThread(
          draft,
          {
            kind: "system",
            stageId: "design-review",
            author: decision.by,
            content:
              decision.kind === "approved"
                ? "Approved the design. Code Generation can start."
                : `Requested changes: ${decision.note ?? ""}`,
          },
          at,
        );

        if (decision.kind === "changes") {
          // Sending it back rebuilds the design. The review itself stays
          // readable, so the note that was just written does not vanish behind
          // a progress panel.
          for (const id of regeneratedStages) {
            draft.stages[id].status = "generating";
            draft.stages[id].error = null;
          }
        }
        recomputeCoverage(draft);
      });
    },
  };
  return api;
}

function createHttpApi(): RequirementsApi {
  const base = (projectId: string) => `/projects/${projectId}/design`;
  return {
    getDesign: (projectId) => http.get<DesignSnapshot>(base(projectId)),
    // The orchestrator treats requirement text going from empty to non empty as
    // the start signal, so there is no run endpoint to call: patch the project
    // and read the design back.
    startDesignRun: async (projectId, text, files = []) => {
      // The files only when some were attached here: sending an empty list
      // replaced the ones the project was created with.
      await http.patch(`/projects/${projectId}`, {
        requirementText: text,
        ...(files.length > 0 ? { files } : {}),
      });
      return http.get<DesignSnapshot>(base(projectId));
    },
    startOver: async (projectId) => {
      await http.post("/runs", { projectId, component: "c1" });
      return http.get<DesignSnapshot>(base(projectId));
    },
    editRequirement: (projectId, requirementId, text) =>
      http.patch<DesignSnapshot>(`${base(projectId)}/requirements/${requirementId}`, { text }),
    editAssumption: (projectId, assumptionId, text) =>
      http.patch<DesignSnapshot>(`${base(projectId)}/assumptions/${assumptionId}`, { text }),
    dismissAssumption: (projectId, assumptionId, dismissed) =>
      http.patch<DesignSnapshot>(`${base(projectId)}/assumptions/${assumptionId}`, { dismissed }),
    answerQuestion: (projectId, questionId, answer) =>
      http.post<DesignSnapshot>(`${base(projectId)}/questions/${questionId}/answer`, { answer }),
    applyAnswers: (projectId) => http.post<DesignSnapshot>(`${base(projectId)}/answers/apply`, {}),
    continueFromQuestions: (projectId, kind) =>
      http.post<DesignSnapshot>(`${base(projectId)}/questions/continue`, { kind }),
    selectArchitecture: (projectId, candidateId, by) =>
      http.post<DesignSnapshot>(`${base(projectId)}/architecture/select`, { candidateId, by }),
    renameGraphNode: (projectId, nodeId, label) =>
      http.patch<DesignSnapshot>(`${base(projectId)}/graph/nodes/${nodeId}`, { label }),
    requestWireframeRefinement: (projectId, flowId, note) =>
      http.post<DesignSnapshot>(`${base(projectId)}/wireframes/${flowId}/refine`, { note }),
    submitChange: (projectId, note, by) =>
      http.post<DesignSnapshot>(`${base(projectId)}/changes`, { note, by }),
    continueRun: async (projectId, runId) => {
      await http.post(`/runs/${runId}/continue`);
      return http.get<DesignSnapshot>(base(projectId));
    },
    retryStage: (projectId, stageId) =>
      http.post<DesignSnapshot>(`${base(projectId)}/stages/${stageId}/retry`, {}),
    submitGateDecision: (projectId, decision) =>
      http.post<DesignSnapshot>(`${base(projectId)}/decision`, decision),
  };
}

export function createRequirementsApi(): RequirementsApi {
  return isLive("requirements") ? createHttpApi() : createFixtureApi();
}

export const requirementsApi: RequirementsApi = createRequirementsApi();
