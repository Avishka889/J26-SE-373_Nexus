import { beforeEach, describe, expect, it, vi } from "vitest";
import { createRequirementsApi } from "../api/createRequirementsApi";
import { buildSnapshot, readDesign, resetDesignDb, writeDesign } from "./designDb";
import { nexuspaySeed } from "@/entities/design-seed/projects/nexuspay";

const api = createRequirementsApi();
const PROJECT = "p1";

/**
 * NexusPay's content with nobody having decided yet.
 *
 * Stated explicitly rather than read from the project, because p1 is in Testing
 * and its design gate is therefore already approved. These tests are about what
 * the mutations do to an undecided design, so they say which state they start
 * from instead of depending on where a fixture project happens to have got to.
 */
const undecided = () => buildSnapshot(PROJECT, nexuspaySeed, "awaiting");

beforeEach(() => {
  resetDesignDb();
  writeDesign(PROJECT, undecided());
  vi.useRealTimers();
});

describe("the seeded design artifact", () => {
  const snapshot = undecided();

  it("has every stage complete at version 1", () => {
    for (const stage of Object.values(snapshot.stages)) {
      expect(stage.status).toBe("complete");
      expect(stage.generatedFromVersion).toBe(1);
    }
    expect(snapshot.requirementsVersion).toBe(1);
  });

  it("starts with no gate decision and no architecture chosen", () => {
    expect(snapshot.gate.decision).toBeNull();
    expect(snapshot.architecture!.selectedCandidateId).toBeNull();
    // A recommendation is offered, but choosing is still the human's job.
    expect(snapshot.architecture!.recommendedCandidateId).toBeTruthy();
  });

  it("traces every requirement id used by an artifact back to a real requirement", () => {
    const ids = new Set(snapshot.requirements.map((r) => r.id));
    const used = [
      ...snapshot.graph.nodes.flatMap((n) => n.traces),
      ...snapshot.graph.edges.flatMap((e) => e.traces),
      ...snapshot.uml.diagrams.flatMap((d) => d.traces),
      ...snapshot.wireframes.flows.flatMap((f) => f.traces),
      ...[...snapshot.sprint!.proposed, ...snapshot.sprint!.backlog].flatMap((s) => s.traces),
      ...snapshot.assumptions.flatMap((a) => a.traces),
      ...snapshot.questions.flatMap((q) => q.traces),
    ];
    expect(used.length).toBeGreaterThan(0);
    for (const id of used) expect(ids.has(id)).toBe(true);
  });

  it("computes wireframe coverage, and names a story with no screen", () => {
    const uncovered = snapshot.wireframes.coverage.filter((row) => !row.covered);
    expect(snapshot.wireframes.coverage.length).toBeGreaterThan(0);
    // Notifications have no screen of their own, which is exactly what the
    // coverage strip is for: saying so rather than letting it pass unnoticed.
    expect(uncovered.map((r) => r.storyId)).toContain("US-105");
    // Everything else is covered, so the strip is not just noise.
    expect(uncovered).toHaveLength(1);
  });

  it("plans work without reporting progress on work that does not exist", () => {
    expect(snapshot.sprint!.estimatedPoints).toBeGreaterThan(0);
    expect(snapshot.sprint!.velocityAssumption.basis).toContain("assumed");
    expect(JSON.stringify(snapshot.sprint)).not.toContain("completed");
    expect(JSON.stringify(snapshot.sprint)).not.toContain("burndown");
  });

  it("gives every story acceptance criteria, since test generation reads them", () => {
    for (const story of [...snapshot.sprint!.proposed, ...snapshot.sprint!.backlog]) {
      expect(story.acceptance.length).toBeGreaterThan(0);
    }
  });
});

describe("mutations", () => {
  it("marks an edited requirement adjusted without regenerating anything", async () => {
    const before = readDesign(PROJECT);
    const after = await api.editRequirement(PROJECT, "R-1", "Customers can pay by card.");
    const edited = after.requirements.find((r) => r.id === "R-1");
    expect(edited?.text).toBe("Customers can pay by card.");
    expect(edited?.adjusted).toBe(true);
    // The version is untouched, so no stage becomes outdated.
    expect(after.requirementsVersion).toBe(before.requirementsVersion);
    expect(after.stages["domain-model"].status).toBe("complete");
  });

  it("posts an answered question into the thread", async () => {
    const after = await api.answerQuestion(PROJECT, "Q-1", "Hold it, do not refuse.");
    const question = after.questions.find((q) => q.id === "Q-1");
    expect(question?.answer).toBe("Hold it, do not refuse.");
    expect(question?.answeredAt).toBeTruthy();
    expect(after.thread.some((m) => m.kind === "answer" && m.content.includes("Hold it"))).toBe(true);
  });

  it("records exactly one architecture selection", async () => {
    const first = await api.selectArchitecture(PROJECT, "microservices", "A. Chen");
    expect(first.architecture!.selectedCandidateId).toBe("microservices");
    const second = await api.selectArchitecture(PROJECT, "modular-monolith", "A. Chen");
    expect(second.architecture!.selectedCandidateId).toBe("modular-monolith");
    expect(second.architecture!.selectedBy).toBe("A. Chen");
  });

  it("ignores a selection that is not a candidate", async () => {
    const after = await api.selectArchitecture(PROJECT, "not-a-shape", "A. Chen");
    expect(after.architecture!.selectedCandidateId).toBeNull();
  });

  it("renames a graph node and records which version changed it", async () => {
    const after = await api.renameGraphNode(PROJECT, "e2", "Settlement");
    const node = after.graph.nodes.find((n) => n.id === "e2");
    expect(node?.label).toBe("Settlement");
    expect(node?.changedInVersion).toBe(after.requirementsVersion);
    expect(after.graph.changedNodeIds).toContain("e2");
  });

  it("bumps the version on a change and sets every later stage generating", async () => {
    const after = await api.submitChange(PROJECT, "Add refunds", "A. Chen");
    expect(after.requirementsVersion).toBe(2);
    expect(after.stages.requirements.generatedFromVersion).toBe(2);
    for (const id of ["domain-model", "architecture-graph", "wireframes"] as const) {
      expect(after.stages[id].status).toBe("generating");
      // Still recorded against the old version, which is what makes it outdated.
      expect(after.stages[id].generatedFromVersion).toBe(1);
    }
    // Design Review is a view over the others plus the decision, not an artifact
    // of its own, so it stays readable rather than hiding behind a spinner.
    expect(after.stages["design-review"].status).toBe("complete");
    expect(after.stages["design-review"].generatedFromVersion).toBe(2);
    expect(after.thread.some((m) => m.content === "Add refunds")).toBe(true);
  });

  it("supersedes a decision when the requirements change under it", async () => {
    await api.submitGateDecision(PROJECT, { kind: "approved", by: "A. Chen" });
    const after = await api.submitChange(PROJECT, "Add refunds", "A. Chen");
    expect(after.gate.decision).toBeNull();
    expect(after.gate.history).toHaveLength(1);
    expect(after.gate.history[0].version).toBe(1);
  });

  it("records an approval against the version it covers", async () => {
    const after = await api.submitGateDecision(PROJECT, { kind: "approved", by: "A. Chen" });
    expect(after.gate.decision).toMatchObject({ kind: "approved", by: "A. Chen", version: 1 });
    // Approving does not regenerate anything.
    expect(after.stages["domain-model"].status).toBe("complete");
  });

  it("regenerates the design when changes are requested", async () => {
    const after = await api.submitGateDecision(PROJECT, {
      kind: "changes",
      by: "A. Chen",
      note: "Split the review queue by document type",
    });
    expect(after.gate.decision?.kind).toBe("changes");
    expect(after.gate.decision?.note).toContain("Split the review queue");
    expect(after.stages.wireframes.status).toBe("generating");
  });

  it("flags a flow that is waiting on a refinement", async () => {
    const after = await api.requestWireframeRefinement(PROJECT, "flow-payment", "Show the fee");
    const flow = after.wireframes.flows.find((f) => f.id === "flow-payment");
    expect(flow?.pendingRefinement).toBe(true);
    expect(flow?.refinementNote).toBe("Show the fee");
  });

  it("puts a retried stage back into generating", async () => {
    const after = await api.retryStage(PROJECT, "wireframes");
    expect(after.stages.wireframes.status).toBe("generating");
    expect(after.stages.wireframes.error).toBeNull();
  });

  it("keeps each project's design separate", async () => {
    await api.editRequirement(PROJECT, "R-1", "Changed for p1 only");
    const other = await api.getDesign("p4");
    expect(other.requirements.find((r) => r.id === "R-1")?.text).not.toBe("Changed for p1 only");
  });
});
