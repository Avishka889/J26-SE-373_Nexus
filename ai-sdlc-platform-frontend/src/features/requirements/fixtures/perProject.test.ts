import { beforeEach, describe, expect, it } from "vitest";
import { DESIGN_STAGE_IDS } from "@/types/project";
import { MOCK_PROJECTS } from "@/entities/project/fixtures";
import { readDesign, recomputeCoverage, resetDesignDb, seedDesignSnapshot, writeDesign } from "./designDb";
import { DESIGN_SEEDS, postureFor } from "@/entities/design-seed";

/**
 * Every project gets its own design, and its gate agrees with its own progress.
 *
 * Before this, one snapshot served every project: a commerce platform showed a
 * payment KYC threshold, and a project already in Testing showed an undecided
 * design gate above two unanswered questions. Both are contradictions of the
 * product's core mechanic, and neither was catchable by a type.
 */

beforeEach(resetDesignDb);

const projectIds = Object.keys(DESIGN_SEEDS);

describe("each project has its own content", () => {
  it("covers every fixture project", () => {
    for (const project of MOCK_PROJECTS) {
      expect(DESIGN_SEEDS[project.id], `no design seed for ${project.name}`).toBeTruthy();
    }
  });

  it("gives no two projects the same requirements", () => {
    const seen = new Map<string, string>();
    for (const id of projectIds) {
      const fingerprint = readDesign(id)
        .requirements.map((r) => r.text)
        .join("|");
      const clash = seen.get(fingerprint);
      expect(clash, `${id} and ${clash} show identical requirements`).toBeUndefined();
      seen.set(fingerprint, id);
    }
  });

  it("names each project's own domain and not another's", () => {
    const text = (id: string) =>
      readDesign(id)
        .requirements.map((r) => r.text)
        .join(" ")
        .toLowerCase();

    expect(text("p1")).toContain("payment");
    expect(text("p3")).toContain("cart");
    expect(text("p2")).toContain("patient");
    expect(text("p4")).toContain("notification");

    // The leak that started this: commerce, records and notifications have no
    // business carrying a payment verification threshold.
    for (const id of ["p2", "p3", "p4"]) {
      expect(text(id)).not.toContain("identity verification");
    }
  });

  it("records a stack only for projects that reached Code Generation", () => {
    for (const project of MOCK_PROJECTS) {
      const reachedCodeGen = postureFor(project.status) === "approved";
      if (reachedCodeGen) continue;
      // The header renders these chips. A project still in Design showing
      // "React, Express, Redis, AWS" claims a decision that belongs to the next
      // phase and has not been taken.
      expect(project.techStack, `${project.name} is in ${project.status}`).toHaveLength(0);
    }
  });

  it("never names a technology on a graph node, in any project", () => {
    for (const id of projectIds) {
      for (const node of readDesign(id).graph.nodes) {
        expect(node).not.toHaveProperty("tech");
      }
    }
  });
});

describe("the gate agrees with the project's own progress", () => {
  it("shows a recorded decision for every project past the design phase", () => {
    for (const project of MOCK_PROJECTS.filter((p) => postureFor(p.status) === "approved")) {
      const snapshot = readDesign(project.id);
      expect(snapshot.gate.decision, `${project.name} is in ${project.status}`).toMatchObject({
        kind: "approved",
        version: 1,
      });
      expect(snapshot.gate.decision?.by).toBeTruthy();
      expect(snapshot.gate.decision?.at).toBeTruthy();
      expect(snapshot.gate.history).toHaveLength(1);

      // It could not have been approved with either of these outstanding: the
      // decision bar refuses both.
      expect(snapshot.questions.filter((q) => !q.answer)).toHaveLength(0);
      expect(snapshot.architecture!.selectedCandidateId).toBeTruthy();
    }
  });

  it("leaves exactly one project waiting on a decision", () => {
    const awaiting = MOCK_PROJECTS.filter((p) => postureFor(p.status) === "awaiting");
    expect(awaiting).toHaveLength(1);
    const snapshot = readDesign(awaiting[0].id);
    expect(snapshot.gate.decision).toBeNull();
    expect(snapshot.questions.some((q) => !q.answer)).toBe(true);
  });

  it("starts a project with no content of its own completely empty", () => {
    const snapshot = seedDesignSnapshot("brand-new");
    expect(snapshot.requirementsVersion).toBe(0);
    expect(snapshot.requirements).toHaveLength(0);
    expect(snapshot.gate.decision).toBeNull();
    expect(snapshot.thread).toHaveLength(0);
    for (const id of DESIGN_STAGE_IDS) {
      expect(snapshot.stages[id].status).toBe("pending");
      expect(snapshot.stages[id].generatedFromVersion).toBe(0);
    }
  });
});

describe("every project's artifacts hold together", () => {
  it("traces every artifact element back to a real requirement", () => {
    for (const id of projectIds) {
      const snapshot = readDesign(id);
      const known = new Set(snapshot.requirements.map((r) => r.id));
      const used = [
        ...snapshot.graph.nodes.flatMap((n) => n.traces),
        ...snapshot.graph.edges.flatMap((e) => e.traces),
        ...snapshot.graph.nodes.flatMap((n) => n.unconfirmed?.traces ?? []),
        ...snapshot.uml.diagrams.flatMap((d) => d.traces),
        ...snapshot.uml.useCases.flatMap((u) => u.traces),
        ...snapshot.wireframes.flows.flatMap((f) => f.traces),
        ...[...snapshot.sprint!.proposed, ...snapshot.sprint!.backlog].flatMap((s) => s.traces),
        ...snapshot.assumptions.flatMap((a) => a.traces),
        ...snapshot.questions.flatMap((q) => q.traces),
      ];
      expect(used.length).toBeGreaterThan(0);
      for (const trace of used) {
        expect(known.has(trace), `${id} traces to ${trace}, which does not exist`).toBe(true);
      }
    }
  });

  it("points every graph edge and constraint at nodes that exist", () => {
    for (const id of projectIds) {
      const snapshot = readDesign(id);
      const nodeIds = new Set(snapshot.graph.nodes.map((n) => n.id));
      for (const edge of snapshot.graph.edges) {
        expect(nodeIds.has(edge.source), `${id}: edge ${edge.id} source`).toBe(true);
        expect(nodeIds.has(edge.target), `${id}: edge ${edge.id} target`).toBe(true);
        expect(edge.source).not.toBe(edge.target);
      }
      for (const node of snapshot.graph.nodes.filter((n) => n.kind === "constraint")) {
        expect(node.appliesTo.length, `${id}: ${node.label} constrains nothing`).toBeGreaterThan(0);
        for (const target of node.appliesTo) expect(nodeIds.has(target)).toBe(true);
      }
    }
  });

  it("says which requirement an unconfirmed node came from", () => {
    for (const id of projectIds) {
      for (const node of readDesign(id).graph.nodes) {
        if (!node.unconfirmed) continue;
        expect(node.unconfirmed.ruleId).toBeTruthy();
        expect(node.unconfirmed.reason.length).toBeGreaterThan(20);
        // Without this the badge has nowhere to send the reader, which is the
        // whole reason it replaced a bare boolean.
        expect(node.unconfirmed.traces.length).toBeGreaterThan(0);
      }
    }
  });

  it("keeps every sequence step between participants the graph knows", () => {
    for (const id of projectIds) {
      const snapshot = readDesign(id);
      const nodeIds = new Set(snapshot.graph.nodes.map((n) => n.id));
      for (const useCase of snapshot.uml.useCases) {
        for (const step of useCase.steps) {
          expect(nodeIds.has(step.fromId), `${id}: ${useCase.id} from ${step.fromId}`).toBe(true);
          expect(nodeIds.has(step.toId), `${id}: ${useCase.id} to ${step.toId}`).toBe(true);
        }
      }
    }
  });

  it("counts the real artifacts in every stage summary", () => {
    for (const id of projectIds) {
      const snapshot = readDesign(id);
      expect(snapshot.stages.requirements.summary).toContain(
        `${snapshot.requirements.length} requirement`,
      );
      expect(snapshot.stages["architecture-graph"].summary).toContain(
        `${snapshot.graph.nodes.length} node`,
      );
      expect(snapshot.stages["sprint-plan"].summary).toContain(
        `${snapshot.sprint!.estimatedPoints} points`,
      );
    }
  });

  it("estimates points that add up to the proposed stories", () => {
    for (const id of projectIds) {
      const snapshot = readDesign(id);
      const total = snapshot.sprint!.proposed.reduce((sum, story) => sum + story.points, 0);
      expect(snapshot.sprint!.estimatedPoints, `${id} sprint total`).toBe(total);
    }
  });

  it("gives every story acceptance criteria, since test generation reads them", () => {
    for (const id of projectIds) {
      const snapshot = readDesign(id);
      for (const story of [...snapshot.sprint!.proposed, ...snapshot.sprint!.backlog]) {
        expect(story.acceptance.length, `${id}: ${story.id}`).toBeGreaterThan(0);
      }
    }
  });

  it("reports wireframe coverage honestly, gaps included", () => {
    for (const id of projectIds) {
      const snapshot = readDesign(id);
      const stories = [...snapshot.sprint!.proposed, ...snapshot.sprint!.backlog];
      expect(snapshot.wireframes.coverage).toHaveLength(stories.length);
      // A demo where everything is covered proves nothing about the strip.
      expect(snapshot.wireframes.coverage.some((row) => !row.covered)).toBe(true);
    }
  });

  it("stamps everything with a recent date the UI can render raw", () => {
    for (const id of projectIds) {
      const snapshot = readDesign(id);
      const stamps = [
        ...snapshot.thread.map((m) => m.at),
        ...Object.values(snapshot.stages).map((s) => s.generatedAt ?? ""),
        snapshot.gate.decision?.at ?? "",
      ].filter(Boolean);
      expect(stamps.length).toBeGreaterThan(0);
      for (const stamp of stamps) {
        // The thread read 2025 while the app showed a 2026 project.
        expect(stamp, `${id} shows ${stamp}`).not.toMatch(/^2025-/);
        // Rendered raw, so an ISO T in one is a visible bug.
        expect(stamp).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/);
      }
    }
  });

  it("writes no em or en dash into any project's content", () => {
    for (const id of projectIds) {
      const serialised = JSON.stringify(readDesign(id));
      expect(serialised, `${id} contains an em dash`).not.toContain("—");
      expect(serialised, `${id} contains an en dash`).not.toContain("–");
    }
  });
});

describe("cross artefact findings reach the gate", () => {
  it("every project surfaces the stories that have no screen", () => {
    // The panel that renders these is only worth having if the fixtures can
    // produce one. Before this test it was never checked, and a panel nothing
    // ever triggers is a panel nobody notices is broken.
    for (const projectId of projectIds) {
      const snapshot = readDesign(projectId);
      // Only stories somebody performs are scored. Work whose role is software
      // could never have a screen, so it is listed but not counted as a gap.
      const uncovered = snapshot.wireframes.coverage.filter((row) => !row.covered && row.needsScreen);
      expect(snapshot.consistency).toHaveLength(uncovered.length);
      expect(uncovered.length).toBeGreaterThan(0);
    }
  });

  it("a finding names the story and sends the reader to the wireframes", () => {
    const snapshot = readDesign(projectIds[0]);
    const finding = snapshot.consistency[0];
    const uncovered = snapshot.wireframes.coverage.find((row) => !row.covered);

    expect(finding.ruleId).toBe("story-has-a-screen");
    expect(finding.severity).toBe("warning");
    expect(finding.reason).toContain(uncovered!.storyId);
    expect(finding.stageId).toBe("wireframes");
  });

  it("a finding disappears once the story it names is covered", () => {
    // Derived state that survives the thing it described is the exact bug the
    // rule exists to catch, so the fixture must not have it either.
    const projectId = projectIds[0];
    const before = readDesign(projectId);
    const orphan = before.wireframes.coverage.find((row) => !row.covered)!;

    const draft = readDesign(projectId);
    draft.wireframes.flows[0].coversStoryIds = [
      ...draft.wireframes.flows[0].coversStoryIds,
      orphan.storyId,
    ];
    recomputeCoverage(draft);
    writeDesign(projectId, draft);

    const after = readDesign(projectId);
    expect(after.consistency.map((f) => f.reason).join(" ")).not.toContain(orphan.storyId);
    expect(after.consistency).toHaveLength(before.consistency.length - 1);
  });
});
