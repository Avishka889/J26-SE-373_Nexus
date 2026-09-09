"""How many flows there are, and what each one is about, decided by counting.

Asking a model how many journeys a system has produces a different answer every
run, and there is nothing to check it against. The graph already knows: a journey
is what one person does with the system, so the primary actors and the action
edges leaving them are the plan.

External systems are excluded. A payment gateway is an actor in the graph and
nobody clicks through its screens, so giving it a flow would produce a prototype
of somebody else's product.

The cap is four. Not because a system cannot have more journeys, but because each
flow is a model call and a design review nobody can read is not a design review.
The actors are ranked by how much of the system they touch, so what is cut is the
least involved rather than whatever came last out of the graph.
"""

from dataclasses import dataclass, field

from sdlc_contracts import ArchitectureGraph, GraphNode

#: Flows generated at most, and the reason is cost and readability rather than
#: any belief that a system has at most four journeys.
MAX_FLOWS = 4


@dataclass(frozen=True)
class FlowBrief:
    """One journey, before anybody has drawn a screen for it."""

    id: str
    #: The actor whose journey this is, or None for a system with no actor that
    #: does anything, where the flow covers the system as a whole.
    actor_id: str | None
    actor_label: str
    #: Reads "makes a Payment", one per action this actor takes.
    actions: tuple[str, ...] = field(default=())
    #: Ids of the entities this journey touches, for grounding the screens.
    entity_ids: tuple[str, ...] = field(default=())
    traces: tuple[str, ...] = field(default=())


def _label_of(graph: ArchitectureGraph, node_id: str) -> str:
    for node in graph.nodes:
        if node.id == node_id:
            return node.label
    return node_id


def _primary_actors(graph: ArchitectureGraph) -> list[GraphNode]:
    return [n for n in graph.nodes if n.kind == "actor" and n.actor_kind != "external_system"]


def plan_flows(graph: ArchitectureGraph, *, max_flows: int = MAX_FLOWS) -> list[FlowBrief]:
    """One journey per primary actor that does something, busiest first."""
    actions_by_actor: dict[str, list[tuple[str, str, tuple[str, ...]]]] = {}
    for edge in graph.edges:
        if edge.kind == "action":
            actions_by_actor.setdefault(edge.source, []).append(
                (edge.verb, edge.target, tuple(edge.traces))
            )

    briefs: list[FlowBrief] = []
    for actor in _primary_actors(graph):
        actions = actions_by_actor.get(actor.id, [])
        if not actions:
            # An actor the requirements mention but never has do anything. There
            # is no journey to draw, and inventing one would be inventing scope.
            continue
        traces: set[str] = set(actor.traces)
        for _verb, _target, edge_traces in actions:
            traces.update(edge_traces)
        briefs.append(
            FlowBrief(
                id=f"flow-{actor.id}",
                actor_id=actor.id,
                actor_label=actor.label,
                actions=tuple(f"{verb} {_label_of(graph, target)}" for verb, target, _ in actions),
                entity_ids=tuple(dict.fromkeys(target for _, target, _ in actions)),
                traces=tuple(sorted(traces, key=_requirement_order)),
            )
        )

    if not briefs:
        # No actor does anything, which happens on a thin requirement like a
        # calculator where the graph is one service and one entity. There is
        # still a journey: it just does not belong to a named person.
        entities = [n.id for n in graph.nodes if n.kind == "entity"]
        traces = sorted(
            {t for n in graph.nodes if n.kind in {"entity", "service"} for t in n.traces},
            key=_requirement_order,
        )
        return [
            FlowBrief(
                id="flow-main",
                actor_id=None,
                actor_label="Someone using the system",
                actions=(),
                entity_ids=tuple(entities),
                traces=tuple(traces),
            )
        ]

    # Busiest first, so the cap drops the least involved actor rather than
    # whichever one the graph happened to list last.
    briefs.sort(key=lambda brief: (-len(brief.actions), brief.actor_label))
    return briefs[:max_flows]


def _requirement_order(requirement_id: str) -> tuple[int, str]:
    digits = "".join(character for character in requirement_id if character.isdigit())
    return (int(digits) if digits else 10_000, requirement_id)
