import type { ArchitectureGraph, EntityAttribute, GraphNode } from "../api/types";

/**
 * The domain model is a projection over the architecture graph, not a stored
 * artifact. One source, three readers: the Domain Model stage, the Architecture
 * Graph stage, and the diagram generators. That is what makes renaming an entity
 * in one place change all of them, instead of leaving three copies to drift.
 */

export interface DomainActor {
  id: string;
  name: string;
  description: string;
  /** A person, or another system this one talks to. A screen is never an actor. */
  kind: "primary" | "external_system";
  traces: string[];
}

export interface DomainEntity {
  id: string;
  name: string;
  description: string;
  attributes: EntityAttribute[];
  traces: string[];
  /** Services that read or write it, by name. */
  ownedBy: string[];
}

export interface DomainService {
  id: string;
  name: string;
  description: string;
  traces: string[];
}

/** Who does what to what, as one sentence the graph can prove. */
export interface DomainAction {
  id: string;
  actorId: string;
  actor: string;
  verb: string;
  entityId: string;
  entity: string;
  traces: string[];
}

export interface DomainConstraint {
  id: string;
  name: string;
  standard: string | null;
  description: string;
  /** Names of the nodes it binds, so nothing renders unattached. */
  appliesTo: string[];
  traces: string[];
}

export interface DomainModel {
  primaryActors: DomainActor[];
  externalSystems: DomainActor[];
  entities: DomainEntity[];
  services: DomainService[];
  actions: DomainAction[];
  constraints: DomainConstraint[];
  /** Every node by id, so callers can resolve a name without re-scanning. */
  byId: Record<string, GraphNode>;
}

const labelOf = (byId: Record<string, GraphNode>, id: string) => byId[id]?.label ?? id;

export function projectDomain(graph: ArchitectureGraph): DomainModel {
  const byId: Record<string, GraphNode> = {};
  for (const node of graph.nodes) byId[node.id] = node;

  const actors = graph.nodes.filter((n) => n.kind === "actor");
  const entities = graph.nodes.filter((n) => n.kind === "entity");
  const services = graph.nodes.filter((n) => n.kind === "service");
  const constraints = graph.nodes.filter((n) => n.kind === "constraint");

  const toActor = (n: GraphNode): DomainActor => ({
    id: n.id,
    name: n.label,
    description: n.description,
    kind: n.actorKind ?? "primary",
    traces: n.traces,
  });

  const ownersOf = (entityId: string) =>
    graph.edges
      .filter((e) => e.kind === "data" && e.target === entityId)
      .map((e) => labelOf(byId, e.source));

  return {
    primaryActors: actors.filter((n) => n.actorKind !== "external_system").map(toActor),
    externalSystems: actors.filter((n) => n.actorKind === "external_system").map(toActor),

    entities: entities.map((n) => ({
      id: n.id,
      name: n.label,
      description: n.description,
      attributes: n.attributes,
      traces: n.traces,
      ownedBy: ownersOf(n.id),
    })),

    services: services.map((n) => ({
      id: n.id,
      name: n.label,
      description: n.description,
      traces: n.traces,
    })),

    // Only action edges are domain sentences. Topology edges describe wiring,
    // which is a different question and belongs on the graph, not in prose.
    actions: graph.edges
      .filter((e) => e.kind === "action")
      .map((e) => ({
        id: e.id,
        actorId: e.source,
        actor: labelOf(byId, e.source),
        verb: e.verb,
        entityId: e.target,
        entity: labelOf(byId, e.target),
        traces: e.traces,
      })),

    constraints: constraints.map((n) => ({
      id: n.id,
      name: n.label,
      standard: n.standard,
      description: n.description,
      appliesTo: n.appliesTo.map((id) => labelOf(byId, id)),
      traces: n.traces,
    })),

    byId,
  };
}
