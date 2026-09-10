import { DESIGN_STAGE_IDS, type DesignStageId } from "@/types/project";
import type {
  ConsistencyFinding,
  DesignSnapshot,
  DesignThreadMessage,
  StageState,
  WireframeCoverageRow,
} from "../api/types";
import type { DesignPosture, ProjectDesignSeed, SeedQuestion } from "@/entities/design-seed";

/**
 * Turn one project's content into the snapshot the UI reads.
 *
 * Everything a reader could catch out is computed here rather than written down:
 * the stage summaries count the real artifacts, the coverage table is derived
 * from which flows name which stories, and the gate decision exists only where
 * the project's own progress says a decision must already have been taken.
 */

/** The demo clock. Fixed, so fixture output does not change between runs. */
const SEEDED_AT = new Date(Date.UTC(2026, 7, 6, 9, 40));

export function demoStamp(minutesAfterSeed: number): string {
  const at = new Date(SEEDED_AT);
  at.setUTCMinutes(at.getUTCMinutes() + minutesAfterSeed);
  return at.toISOString().slice(0, 16).replace("T", " ");
}

/** Minutes after the seed moment each stage finished, in canonical order. */
const STAGE_MINUTES: Record<DesignStageId, number> = {
  requirements: 0,
  "domain-model": 2,
  "architecture-graph": 4,
  "architecture-recommendation": 6,
  "uml-diagrams": 9,
  wireframes: 12,
  "sprint-plan": 14,
  "design-review": 15,
};

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/**
 * What a stage says when it finishes, counted from the artifacts it produced.
 *
 * Derived rather than authored: a hand written summary is the first thing to go
 * stale, and "12 requirements" over a list of five is exactly the kind of quiet
 * lie the phase exists to avoid.
 */
export function stageSummary(stageId: DesignStageId, snapshot: DesignSnapshot): string {
  const openQuestions = snapshot.questions.filter((q) => !q.answer).length;

  switch (stageId) {
    case "requirements": {
      const parts = [
        plural(snapshot.requirements.length, "requirement"),
        plural(snapshot.assumptions.filter((a) => !a.dismissed).length, "assumption"),
      ];
      if (openQuestions > 0) parts.push(`${plural(openQuestions, "open question")}`);
      return `Requirements analysed: ${parts.join(", ")}`;
    }
    case "domain-model": {
      const actors = snapshot.graph.nodes.filter((n) => n.actorKind === "primary").length;
      const external = snapshot.graph.nodes.filter(
        (n) => n.actorKind === "external_system",
      ).length;
      const entities = snapshot.graph.nodes.filter((n) => n.kind === "entity").length;
      return `Domain model ready: ${plural(entities, "entity", "entities")}, ${plural(actors, "actor")}, ${plural(external, "external system")}`;
    }
    case "architecture-graph": {
      const constraints = snapshot.graph.nodes.filter((n) => n.kind === "constraint").length;
      const unconfirmed = snapshot.graph.nodes.filter((n) => n.unconfirmed).length;
      const base = `Architecture graph ready: ${plural(snapshot.graph.nodes.length, "node")}, ${plural(snapshot.graph.edges.length, "edge")}, ${plural(constraints, "rule")} attached`;
      return unconfirmed > 0 ? `${base}, ${unconfirmed} needing a closer look` : base;
    }
    case "architecture-recommendation": {
      // Absent when the stage never produced anything. The seeds always populate
      // it, so this is the shape of the real payload showing through rather than
      // a case the demo hits.
      if (!snapshot.architecture) return "No deployment shapes were scored";
      const shapes = snapshot.architecture.candidates.length;
      const winner = snapshot.architecture.candidates.find(
        (c) => c.id === snapshot.architecture?.recommendedCandidateId,
      );
      return `${plural(shapes, "deployment shape")} scored, ${winner?.name ?? "none"} recommended`;
    }
    case "uml-diagrams": {
      const traced = snapshot.uml.useCases.filter((u) => u.storyId).length;
      return `${plural(snapshot.uml.diagrams.length, "diagram")} generated, ${traced} traced to stories`;
    }
    case "wireframes": {
      const covered = snapshot.wireframes.coverage.filter((c) => c.covered).length;
      return `${plural(snapshot.wireframes.flows.length, "flow")} generated covering ${covered} of ${snapshot.wireframes.coverage.length} stories`;
    }
    case "sprint-plan":
      if (!snapshot.sprint) return "No sprint plan was written";
      return `${snapshot.sprint.sprintName} proposed: ${plural(snapshot.sprint.proposed.length, "story", "stories")}, ${snapshot.sprint.estimatedPoints} points estimated`;
    case "design-review":
      return snapshot.gate.decision
        ? `Design approved at version ${snapshot.gate.decision.version}`
        : "Everything generated and waiting on your decision";
  }
}

/** "As a Delivery Driver, ..." and "As an operator, ...". */
const ROLE = /^\s*As\s+(?:an?|the)\s+([^,]+),/i;

/** Roles that name software rather than a person. */
const NOT_A_PERSON = new Set(["system", "platform", "service"]);

/**
 * Whether it makes sense to expect a screen for this story.
 *
 * Only three things say no: a story written from nobody's point of view, one
 * whose role is software, and one performed by another system the design names
 * as external. Everything else is somebody's story and is scored.
 *
 * Deliberately conservative. Requiring the role to match a `primary` actor
 * exactly excused real stories: a design whose actors are "Clinician" and
 * "Administrator" has stories about a doctor and a compliance officer, and all
 * of them vanished from coverage. A near miss in wording is not evidence that
 * nobody performs the story.
 *
 * Mirrors `orchestrator/checks/coverage.py`, which is the authority; this exists
 * because the fixtures compute the same join and would otherwise show a
 * different number from the backend for the same design.
 */
function needsScreen(story: { title: string }, snapshot: DesignSnapshot): boolean {
  const role = ROLE.exec(story.title)?.[1]?.trim().toLowerCase();
  // No role at all: it is not written as anyone's story.
  if (!role) return false;
  if (NOT_A_PERSON.has(role) || role.endsWith(" system")) return false;

  const external = new Set(
    snapshot.graph.nodes
      .filter((node) => node.kind === "actor" && node.actorKind === "external_system")
      .map((node) => node.label.trim().toLowerCase()),
  );
  return !external.has(role);
}

/** Which stories a screen covers, which have none, and which want none. */
export function buildCoverage(snapshot: DesignSnapshot): WireframeCoverageRow[] {
  if (!snapshot.sprint) return [];
  const stories = [...snapshot.sprint.proposed, ...snapshot.sprint.backlog];
  return stories.map((story) => {
    const screenIds = snapshot.wireframes.flows
      .filter((flow) => flow.coversStoryIds.includes(story.id))
      .flatMap((flow) => flow.screens.map((screen) => `${flow.id}/${screen.id}`));
    return {
      storyId: story.id,
      storyTitle: story.title,
      screenIds,
      covered: screenIds.length > 0,
      needsScreen: needsScreen(story, snapshot),
    };
  });
}

/**
 * The cross artefact findings a fixture can honestly produce.
 *
 * One of the backend's six, and deliberately only one. "This story has no
 * screen" is a read of the coverage rows that were just computed, so deriving it
 * here duplicates no logic: both sides read the same join. The other five
 * compare artefacts for disagreements the seeds cannot have, because the seeds
 * are hand authored to be coherent and there is no regeneration to make one of
 * them stale. Reimplementing them in TypeScript would be writing a second copy
 * of the rules to drift against the first.
 */
export function buildConsistency(snapshot: DesignSnapshot): ConsistencyFinding[] {
  return snapshot.wireframes.coverage
    .filter((row) => !row.covered && row.needsScreen)
    .map((row) => ({
      ruleId: "story-has-a-screen",
      severity: "warning" as const,
      reason: `${row.storyId} "${row.storyTitle}" has no screen in any journey, so there is nothing showing how a user would do it.`,
      traces: [],
      stageId: "wireframes" as const,
    }));
}

/**
 * Called after any change that could alter which stories have a screen.
 *
 * Recomputes the findings as well as the table, and not as a convenience: a
 * finding left behind after the thing it described was fixed is the same stale
 * derived state the rule it came from exists to catch.
 */
export function recomputeCoverage(draft: DesignSnapshot) {
  draft.wireframes.coverage = buildCoverage(draft);
  draft.consistency = buildConsistency(draft);
}

function emptyStages(): Record<DesignStageId, StageState> {
  const stages = {} as Record<DesignStageId, StageState>;
  for (const id of DESIGN_STAGE_IDS) {
    stages[id] = {
      id,
      status: "pending",
      generatedFromVersion: 0,
      generatedAt: null,
      summary: null,
      error: null,
      modelUse: null,
    };
  }
  return stages;
}

export function buildSnapshot(
  projectId: string,
  seed: ProjectDesignSeed,
  posture: DesignPosture,
  /** What the reader typed, which opens the transcript. */
  requirementText = "",
): DesignSnapshot {
  const generated = posture !== "empty";
  const approved = posture === "approved";

  // A project cannot have been approved with questions still open or with no
  // architecture chosen, because the decision bar refuses both. So an approved
  // posture answers its questions and records the selection, rather than showing
  // an approved gate above two unanswered questions.
  const questions = structuredClone(seed.questions).map((question) =>
    approved && !question.answer
      ? {
          ...question,
          answer: question.presetAnswer ?? "Answered during the design review.",
          answeredAt: demoStamp(STAGE_MINUTES["design-review"] - 1),
        }
      : question,
  );

  const architecture = structuredClone(seed.architecture);
  if (architecture && approved && !architecture.selectedCandidateId) {
    architecture.selectedCandidateId = architecture.recommendedCandidateId;
    architecture.selectedAt = demoStamp(STAGE_MINUTES["architecture-recommendation"]);
    architecture.selectedBy = "A. Chen";
  }

  const snapshot: DesignSnapshot = {
    projectId,
    appName: seed.appName,
    requirementsVersion: generated ? 1 : 0,
    stages: emptyStages(),
    requirements: generated ? structuredClone(seed.requirements) : [],
    assumptions: generated ? structuredClone(seed.assumptions) : [],
    questions: generated ? questions.map(stripPreset) : [],
    graph: {
      nodes: generated ? structuredClone(seed.nodes) : [],
      edges: generated ? structuredClone(seed.edges) : [],
      changedNodeIds: [],
    },
    // Null before the stage has run, exactly as the server sends it. An empty
    // recommendation object was out of contract (candidates has a floor of
    // two) and the generated types refused it, which is the drift check
    // working.
    architecture: generated ? architecture : null,
    uml: {
      useCases: generated ? structuredClone(seed.useCases) : [],
      diagrams: generated ? structuredClone(seed.diagrams) : [],
    },
    wireframes: { flows: generated ? structuredClone(seed.flows) : [], coverage: [] },
    sprint: generated
      ? structuredClone(seed.sprint)
      : {
          sprintName: "Sprint 1",
          goal: "",
          velocityAssumption: { points: 0, basis: "" },
          estimatedPoints: 0,
          proposed: [],
          backlog: [],
        },
    run: null,
    gate: { decision: null, history: [] },
    thread: [],
    queuedChanges: [],
    // The demo's runs never pause on their questions.
    questionsPending: false,
    consistency: [],
  };

  snapshot.wireframes.coverage = buildCoverage(snapshot);
  snapshot.consistency = buildConsistency(snapshot);

  if (!generated) return snapshot;

  if (approved) {
    const decision = {
      kind: "approved" as const,
      at: demoStamp(STAGE_MINUTES["design-review"]),
      by: "A. Chen",
      version: 1,
      note: null,
    };
    snapshot.gate = { decision, history: [decision] };
  }

  for (const id of DESIGN_STAGE_IDS) {
    snapshot.stages[id] = {
      id,
      status: "complete",
      generatedFromVersion: 1,
      generatedAt: demoStamp(STAGE_MINUTES[id]),
      summary: stageSummary(id, snapshot),
      error: null,
      modelUse: null,
    };
  }

  snapshot.thread = buildThread(snapshot, approved, requirementText);
  return snapshot;
}

/**
 * The conversation as it actually happened, oldest first.
 *
 * The reader's own words come first, because that is what started this: the
 * panel is a transcript, and a transcript that begins with the machine talking
 * is not one.
 */
function buildThread(
  snapshot: DesignSnapshot,
  approved: boolean,
  requirementText: string,
): DesignThreadMessage[] {
  const thread: DesignThreadMessage[] = [];
  let seq = 0;
  const push = (
    message: Omit<DesignThreadMessage, "id" | "producedVersion" | "question"> &
      Partial<Pick<DesignThreadMessage, "producedVersion" | "question">>,
  ) => {
    seq += 1;
    thread.push({ producedVersion: null, question: null, ...message, id: `t-${seq}` });
  };

  // What the reader wrote, verbatim and first. The transcript is a record of a
  // conversation, and a conversation that opens with the machine talking is not
  // one: this is the message every summary below is a reply to.
  if (requirementText.trim()) {
    push({
      kind: "user_note",
      stageId: null,
      author: "You",
      content: requirementText.trim(),
      at: demoStamp(-1),
      producedVersion: 1,
    });
  }

  for (const id of DESIGN_STAGE_IDS) {
    if (id === "design-review" && !approved) continue;
    push({
      kind: "stage_summary",
      stageId: id,
      author: "Design agent",
      content: stageSummary(id, snapshot),
      at: demoStamp(STAGE_MINUTES[id]),
    });

    // An assumption is stated when it is made, so the reader can correct it
    // there rather than discovering it in a list later.
    if (id === "requirements") {
      for (const assumption of snapshot.assumptions.filter((a) => !a.dismissed)) {
        push({
          kind: "system",
          stageId: "requirements",
          author: "Design agent",
          content: `${assumption.text} Correct me if that is wrong.`,
          at: demoStamp(1),
        });
      }
      // An unanswered question is not pushed here: it comes from
      // `snapshot.questions` when the conversation is built, so answering it
      // clears it in the chat, the stage and the review at the same moment.
      // Answers that were given are real events and belong in the record.
      for (const question of snapshot.questions) {
        if (!question.answer) continue;
        push({
          kind: "answer",
          stageId: "requirements",
          author: "A. Chen",
          content: `${question.question}\n${question.answer}`,
          at: question.answeredAt ?? demoStamp(2),
        });
      }
    }
  }

  if (approved && snapshot.gate.decision) {
    push({
      kind: "system",
      stageId: "design-review",
      author: snapshot.gate.decision.by,
      content: "Approved the design. Code Generation can start.",
      at: snapshot.gate.decision.at,
    });
  }

  return thread;
}

/** `presetAnswer` is seed-only sugar and never reaches the contract. */
function stripPreset(question: SeedQuestion) {
  const { presetAnswer: _presetAnswer, ...rest } = question;
  return rest;
}
