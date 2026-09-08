"""Promoting a validated draft into the graph the rest of the system reads.

One direction, one gate. A draft becomes an `ArchitectureGraph` only after the
fifteen rules have passed it, so the strict type never has to raise: by the time
it is constructed, everything it would refuse has already been reported as a
sentence with a hint attached.

Warnings travel with the graph rather than being dropped here. A node the rules
could not confirm carries its finding, which is what the canvas renders as
"needs a closer look" and what the reader clicks to see why.
"""

from sdlc_contracts import ArchitectureGraph, EntityAttribute, GraphEdge, GraphNode, Position

from .rules import ValidationReport
from .schema import DraftGraph, DraftNode


class NotValidated(RuntimeError):
    """Raised when a draft with errors is promoted anyway.

    A programming mistake rather than a model mistake: the caller was supposed to
    run the repair loop first. It names the rules that fired so the mistake is
    obvious from the message.
    """


def to_contract(
    draft: DraftGraph,
    report: ValidationReport,
    *,
    positions: dict[str, Position] | None = None,
) -> ArchitectureGraph:
    """Build the strict graph from a draft the rules accepted."""
    if not report.ok:
        raise NotValidated(
            "this draft has unresolved errors and must not be promoted: "
            + ", ".join(sorted({finding.rule_id for finding in report.errors}))
        )

    placed = positions or {}
    nodes = [
        GraphNode(
            id=node.id,
            kind=node.kind,  # type: ignore[arg-type]
            label=node.label,
            description=node.description,
            position=placed.get(node.id, Position(x=0, y=0)),
            traces=list(node.traces),
            attributes=[
                EntityAttribute(name=attribute.name, type=attribute.type)
                for attribute in node.attributes
            ],
            actorKind=node.actor_kind or None,  # type: ignore[arg-type]
            standard=node.standard or None,
            appliesTo=list(node.applies_to),
            # The warning the reader sees, carried from the rule that raised it.
            unconfirmed=_finding_for(node, report),
            changedInVersion=None,
        )
        for node in draft.nodes
    ]

    edges = [
        GraphEdge(
            id=edge.id,
            source=edge.source,
            target=edge.target,
            kind=edge.kind,  # type: ignore[arg-type]
            verb=edge.verb,
            traces=list(edge.traces),
        )
        for edge in draft.edges
    ]

    return ArchitectureGraph(nodes=nodes, edges=edges, changedNodeIds=[])


def _finding_for(node: DraftNode, report: ValidationReport):
    """The warning this node carries into the artefact, if it has one."""
    finding = report.for_subject(node.id)
    return finding.to_contract() if finding else None
