import { describe, expect, it } from "vitest";
import { DESIGN_SEEDS } from "@/entities/design-seed";
import { CODE_STAGE_IDS } from "@/types/project";
import { buildCodeSnapshot } from "./buildCodeSnapshot";
import { codePostureFor } from "./codeDb";

/**
 * The demo's traceability has to be real.
 *
 * Traceability is the claim this platform is built on, and a chip that opens
 * nothing is worse than no chip: it demonstrates the opposite of the thing it
 * exists to demonstrate. Every screen id, requirement id and story id in the
 * code fixtures has to name something in that project's own design.
 *
 * The grounded half matters as much as the negative one. An empty contract
 * traces to nothing and would pass every "no dangling id" check ever written,
 * so each project must also produce endpoints, entities and scope.
 */

const PROJECT_IDS = Object.keys(DESIGN_SEEDS);

function idsIn(projectId: string) {
  const seed = DESIGN_SEEDS[projectId];
  return {
    screens: new Set(
      seed.flows.flatMap((flow) => flow.screens.map((screen) => `${flow.id}/${screen.id}`)),
    ),
    actions: new Set(
      seed.flows.flatMap((flow) => flow.screens.flatMap((screen) => screen.links.map((l) => l.id))),
    ),
    requirements: new Set(seed.requirements.map((requirement) => requirement.id)),
    stories: new Set([...seed.sprint.proposed, ...seed.sprint.backlog].map((story) => story.id)),
    entities: new Set(seed.nodes.filter((node) => node.kind === "entity").map((n) => n.label)),
  };
}

describe.each(PROJECT_IDS)("the code fixture for %s", (projectId) => {
  const snapshot = buildCodeSnapshot(projectId, DESIGN_SEEDS[projectId], "awaiting", 1);
  const known = idsIn(projectId);

  it("produces a contract with something in it", () => {
    // The grounded half: a leakage style check on empty output proves nothing.
    expect(snapshot.contract?.contract.endpoints.length ?? 0).toBeGreaterThan(0);
    expect(snapshot.contract?.contract.entities.length ?? 0).toBeGreaterThan(0);
    expect(snapshot.scope?.stories.length ?? 0).toBeGreaterThan(0);
  });

  it("traces every endpoint to ids that exist in this project's design", () => {
    for (const endpoint of snapshot.contract?.contract.endpoints ?? []) {
      for (const screenId of endpoint.traces.screenIds) {
        expect(known.screens, `${endpoint.id} traces to ${screenId}`).toContain(screenId);
      }
      for (const actionId of endpoint.traces.actionIds) {
        expect(known.actions, `${endpoint.id} traces to ${actionId}`).toContain(actionId);
      }
      for (const requirementId of endpoint.traces.requirementIds) {
        expect(known.requirements, `${endpoint.id} traces to ${requirementId}`).toContain(
          requirementId,
        );
      }
      for (const storyId of endpoint.traces.storyIds) {
        expect(known.stories, `${endpoint.id} traces to ${storyId}`).toContain(storyId);
      }
    }
  });

  it("names only entities the design graph has", () => {
    for (const entity of snapshot.contract?.contract.entities ?? []) {
      expect(known.entities).toContain(entity.name);
    }
    for (const endpoint of snapshot.contract?.contract.endpoints ?? []) {
      if (endpoint.response?.entity) expect(known.entities).toContain(endpoint.response.entity);
      if (endpoint.request?.entity) expect(known.entities).toContain(endpoint.request.entity);
    }
  });

  it("scopes only stories the sprint plan has, with screens that exist", () => {
    for (const story of snapshot.scope?.stories ?? []) {
      expect(known.stories).toContain(story.id);
      for (const screenId of story.traces.screenIds) {
        expect(known.screens).toContain(screenId);
      }
    }
  });

  it("manifests only files the contract accounts for", () => {
    const endpointIds = new Set(
      (snapshot.contract?.contract.endpoints ?? []).map((endpoint) => endpoint.id),
    );
    const entityNames = new Set(
      (snapshot.contract?.contract.entities ?? []).map((entity) => entity.name),
    );
    for (const row of snapshot.repository?.manifest ?? []) {
      for (const implemented of row.implements) {
        expect(
          endpointIds.has(implemented) || entityNames.has(implemented),
          `${row.path} claims to implement ${implemented}`,
        ).toBe(true);
      }
    }
  });

  it("claims no repository, because the demo has no connection", () => {
    // The one lie this phase most needs not to tell. A URL here would be an
    // invented repository that nobody could open.
    expect(snapshot.repository?.repository).toBeNull();
    expect(snapshot.repository?.notPushedReason).toContain("no GitHub connection");
  });
});

describe("the postures the four demo projects sit in", () => {
  it("derives from the project's own status, so a badge cannot contradict a phase", () => {
    expect(codePostureFor("design")).toBe("not-started");
    expect(codePostureFor("code")).toBe("awaiting");
    expect(codePostureFor("testing")).toBe("approved");
    expect(codePostureFor("deploy")).toBe("approved");
  });

  it("gives a not started project every stage pending and no artefacts", () => {
    const snapshot = buildCodeSnapshot("p3", DESIGN_SEEDS.p3, "not-started", 1);
    expect(snapshot.codeVersion).toBe(0);
    expect(CODE_STAGE_IDS.every((id) => snapshot.stages[id].status === "pending")).toBe(true);
    expect(snapshot.contract).toBeNull();
    expect(snapshot.repository).toBeNull();
  });

  it("gives an approved project a recorded decision", () => {
    const snapshot = buildCodeSnapshot("p1", DESIGN_SEEDS.p1, "approved", 1);
    expect(snapshot.gate.decision?.kind).toBe("approved");
  });

  it("shows the stack it cannot generate rather than hiding it", () => {
    const snapshot = buildCodeSnapshot("p2", DESIGN_SEEDS.p2, "awaiting", 1);
    const unavailable = (snapshot.techStack?.candidates ?? []).filter((c) => !c.available);
    expect(unavailable.length).toBeGreaterThan(0);
    expect(unavailable.every((candidate) => candidate.unavailableReason)).toBe(true);
  });
});
