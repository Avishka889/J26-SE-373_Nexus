import { describe, expect, it } from "vitest";
import { seedGraph } from "@/entities/design-seed/projects/nexuspay/graph";
import { seedUseCases } from "@/entities/design-seed/projects/nexuspay/uml";
import { projectDomain } from "./domain";
import { buildClassDiagram, buildErDiagram, buildSequenceDiagram, resolveNames } from "./mermaid";

const domain = projectDomain(seedGraph);

describe("projectDomain", () => {
  it("splits actors into people and other systems, and never invents a third kind", () => {
    expect(domain.primaryActors.map((a) => a.name)).toEqual(["Customer", "Administrator"]);
    expect(domain.externalSystems.map((a) => a.name)).toEqual(["Payment Provider", "Identity Provider"]);
    const total = domain.primaryActors.length + domain.externalSystems.length;
    expect(total).toBe(seedGraph.nodes.filter((n) => n.kind === "actor").length);
  });

  it("reads actions as actor, verb, entity triples from action edges only", () => {
    const sentences = domain.actions.map((a) => `${a.actor} ${a.verb} ${a.entity}`);
    expect(sentences).toContain("Customer makes Payment");
    expect(sentences).toContain("Administrator approves Verification");
    // Topology edges describe wiring, not domain sentences.
    expect(domain.actions).toHaveLength(seedGraph.edges.filter((e) => e.kind === "action").length);
  });

  it("gives every entity the attributes the class diagram renders", () => {
    const payment = domain.entities.find((e) => e.name === "Payment");
    expect(payment?.attributes.map((a) => a.name)).toContain("amount");
    expect(payment?.ownedBy).toContain("Payment Service");
  });

  it("attaches every constraint to something, so none float", () => {
    expect(domain.constraints.length).toBeGreaterThan(0);
    for (const constraint of domain.constraints) {
      expect(constraint.appliesTo.length).toBeGreaterThan(0);
    }
  });

  it("carries traces on every projected element", () => {
    for (const entity of domain.entities) expect(entity.traces.length).toBeGreaterThan(0);
    for (const action of domain.actions) expect(action.traces.length).toBeGreaterThan(0);
  });
});

describe("generated diagrams", () => {
  it("marks entities and services with distinct stereotypes", () => {
    const source = buildClassDiagram(domain);
    expect(source).toContain("<<entity>>");
    expect(source).toContain("<<service>>");
    expect(source).toContain("<<external system>>");
  });

  it("renders entity attributes into the class diagram", () => {
    expect(buildClassDiagram(domain)).toContain("+Money amount");
  });

  it("keeps authored interaction depth in a sequence diagram", () => {
    const useCase = seedUseCases[0];
    const source = buildSequenceDiagram(useCase, domain);
    // More than a single arrow: a real interaction has several steps.
    expect(useCase.steps.length).toBeGreaterThan(3);
    expect(source.split("\n").filter((l) => l.includes("->>")).length).toBeGreaterThan(2);
  });

  it("resolves node tokens rather than hard coding names", () => {
    expect(resolveNames("a {e2} for {a1}", domain)).toBe("a Payment for Customer");
    // An unknown token is left alone rather than silently blanked.
    expect(resolveNames("{nope}", domain)).toBe("{nope}");
  });
});

describe("renaming an entity in the graph", () => {
  // This is the whole claim of the shared module: one source, three readers.
  const renamed = {
    ...seedGraph,
    nodes: seedGraph.nodes.map((n) => (n.id === "e2" ? { ...n, label: "Settlement" } : n)),
  };
  const after = projectDomain(renamed);

  it("changes the domain model", () => {
    expect(after.entities.map((e) => e.name)).toContain("Settlement");
    expect(after.entities.map((e) => e.name)).not.toContain("Payment");
  });

  it("changes the action triples", () => {
    const sentences = after.actions.map((a) => `${a.actor} ${a.verb} ${a.entity}`);
    expect(sentences).toContain("Customer makes Settlement");
  });

  it("changes the generated class diagram", () => {
    const source = buildClassDiagram(after);
    expect(source).toContain("class Settlement");
    expect(source).not.toContain("class Payment {");
  });

  it("changes the generated entity relationship diagram", () => {
    expect(buildErDiagram(after)).toContain("SETTLEMENT");
  });

  it("changes the sequence diagram text, including interpolated tokens", () => {
    const source = buildSequenceDiagram(seedUseCases[0], after);
    expect(source).not.toMatch(/\bPayment\b(?! Service| Provider)/);
  });
});
