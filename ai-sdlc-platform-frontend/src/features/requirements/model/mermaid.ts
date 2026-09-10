import type { UseCase } from "../api/types";
import type { DomainModel } from "./domain";

/**
 * Diagram sources built from the domain projection, never hand written.
 *
 * The class diagram is generated outright: it is a structural view of the same
 * entities, so authoring it separately would just create a copy to drift.
 *
 * Sequence diagrams keep authored interaction steps, because a real interaction
 * has request, validation, persistence and response, and a mechanical rendering
 * of one actor-verb-entity triple would be a single shallow arrow. What they do
 * not keep is authored names: every participant and every `{nodeId}` token is
 * resolved from the graph, so a rename propagates by construction.
 */

/** Mermaid identifiers cannot carry spaces or punctuation. */
function safeId(name: string): string {
  const cleaned = name.replace(/[^A-Za-z0-9]/g, "");
  return cleaned.length > 0 ? cleaned : "Node";
}

/** Resolve `{nodeId}` tokens in authored text against the current graph. */
export function resolveNames(text: string, domain: DomainModel): string {
  return text.replace(/\{([A-Za-z0-9_-]+)\}/g, (whole, id: string) => domain.byId[id]?.label ?? whole);
}

export function buildClassDiagram(domain: DomainModel): string {
  const lines: string[] = ["classDiagram"];

  for (const entity of domain.entities) {
    const id = safeId(entity.name);
    lines.push(`  class ${id} {`);
    lines.push("    <<entity>>");
    for (const attribute of entity.attributes) {
      lines.push(`    +${attribute.type} ${attribute.name}`);
    }
    lines.push("  }");
  }

  for (const service of domain.services) {
    const id = safeId(service.name);
    lines.push(`  class ${id} {`);
    lines.push("    <<service>>");
    lines.push("  }");
  }

  // A service that reads or writes an entity depends on it.
  for (const entity of domain.entities) {
    for (const owner of entity.ownedBy) {
      lines.push(`  ${safeId(owner)} ..> ${safeId(entity.name)} : uses`);
    }
  }

  // Actions become associations, so the diagram says who acts on what.
  for (const action of domain.actions) {
    lines.push(`  ${safeId(action.actor)} --> ${safeId(action.entity)} : ${action.verb}`);
  }

  for (const actor of [...domain.primaryActors, ...domain.externalSystems]) {
    const id = safeId(actor.name);
    lines.push(`  class ${id} {`);
    lines.push(actor.kind === "external_system" ? "    <<external system>>" : "    <<actor>>");
    lines.push("  }");
  }

  return lines.join("\n");
}

export function buildErDiagram(domain: DomainModel): string {
  const lines: string[] = ["erDiagram"];

  for (const entity of domain.entities) {
    for (const owner of entity.ownedBy) {
      lines.push(`  ${safeId(owner).toUpperCase()} ||--o{ ${safeId(entity.name).toUpperCase()} : manages`);
    }
  }

  for (const entity of domain.entities) {
    lines.push(`  ${safeId(entity.name).toUpperCase()} {`);
    for (const attribute of entity.attributes) {
      lines.push(`    ${attribute.type.toLowerCase()} ${attribute.name}`);
    }
    lines.push("  }");
  }

  return lines.join("\n");
}

export function buildSequenceDiagram(useCase: UseCase, domain: DomainModel): string {
  const participantIds: string[] = [];
  for (const step of useCase.steps) {
    if (!participantIds.includes(step.fromId)) participantIds.push(step.fromId);
    if (!participantIds.includes(step.toId)) participantIds.push(step.toId);
  }

  const lines: string[] = ["sequenceDiagram"];
  lines.push("  autonumber");
  for (const id of participantIds) {
    const label = domain.byId[id]?.label ?? id;
    lines.push(`  participant ${safeId(label)} as ${label}`);
  }

  for (const step of useCase.steps) {
    const from = safeId(domain.byId[step.fromId]?.label ?? step.fromId);
    const to = safeId(domain.byId[step.toId]?.label ?? step.toId);
    const message = resolveNames(step.message, domain);
    if (step.kind === "note") {
      lines.push(`  Note over ${from},${to}: ${message}`);
    } else if (step.kind === "return") {
      lines.push(`  ${from}-->>${to}: ${message}`);
    } else {
      lines.push(`  ${from}->>${to}: ${message}`);
    }
  }

  return lines.join("\n");
}
