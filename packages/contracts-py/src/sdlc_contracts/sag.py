"""The Semantic Architecture Graph.

One typed graph of the system, and the single generative source every other
design artefact is produced from: the domain model is a projection of it, the
class and entity relationship diagrams are generated from it, the sequence
diagrams resolve their participant names from it, and the architecture
recommendation scores over it.

That is why nothing here is optional decoration. A node without traces breaks
the traceability claim; a constraint attached to nothing is a rule the design
does not actually apply; an actor that is really a screen produces a domain
model that reads as nonsense.
"""

from typing import Literal

from pydantic import Field, model_validator

from .ids import Traces
from .wire import WireModel

GraphNodeKind = Literal["actor", "entity", "service", "constraint"]

#: A person, or another system this one talks to. A screen is never an actor.
ActorKind = Literal["primary", "external_system"]

#: `action` edges carry the domain verb (who does what to what) and are what the
#: domain projection reads. The rest describe topology: which service owns which
#: data, who calls whom, and which rule binds what.
GraphEdgeKind = Literal["action", "data", "dependency", "constraint"]


class EntityAttribute(WireModel):
    name: str = Field(min_length=1)
    type: str = Field(min_length=1)


class Position(WireModel):
    x: float
    y: float


class ValidationFinding(WireModel):
    """A named rule check that could not confirm a node.

    Carried on the node itself rather than reported in a separate list, because a
    warning the reader cannot trace to a cause is worse than no warning: the
    canvas has to be able to say which rule fired, in plain words, and which
    requirement the reader should go and look at.

    `rule_id` is the stable name of one of C1's rule checks, so the same finding
    can be counted across runs for the evaluation. `reason` is written for the
    person reading the design, and doubles as the repair hint the extraction loop
    feeds back to the model.
    """

    rule_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    #: The requirements this concerns, so the warning can link somewhere useful.
    traces: Traces


class GraphNode(WireModel):
    id: str = Field(min_length=1)
    kind: GraphNodeKind
    label: str = Field(min_length=1)
    description: str = ""
    #: Laid out deterministically, so the canvas does not rearrange itself
    #: between two runs over the same requirements.
    position: Position
    traces: Traces
    #: Entities only. The same attributes the class diagram renders, because it
    #: renders them from here.
    attributes: list[EntityAttribute] = Field(default_factory=list)
    #: Actors only.
    actor_kind: ActorKind | None = None
    #: Constraints only, for example "PCI DSS 4.0".
    standard: str | None = None
    #: Constraints only: the node ids this constrains, so none of them float.
    applies_to: list[str] = Field(default_factory=list)
    #: Null when every rule check confirmed this node, which is the normal case.
    #: There is deliberately no `validated: bool`: a bare boolean can be rendered
    #: as a warning badge but cannot say why, and an unexplained warning is what
    #: this replaces.
    unconfirmed: ValidationFinding | None = None
    #: The requirements version that last changed this node, which is what the
    #: impact highlight reads after a change.
    changed_in_version: int | None = None

    @model_validator(mode="after")
    def fields_match_the_kind(self) -> "GraphNode":
        """Each kind carries its own fields and not the others'.

        The frontend renders by kind, so a constraint carrying attributes or an
        actor carrying a standard produces a confidently wrong picture rather
        than an obvious error.

        There is no technology field on any kind. A node is an actor, an entity,
        a service or a rule, and nothing more: the stack is proposed and chosen in
        C2, so naming a framework here would let the design contradict the
        decision that has not been taken yet.
        """
        wrong: list[str] = []
        if self.kind != "entity" and self.attributes:
            wrong.append("attributes belong to entities")
        if self.kind != "actor" and self.actor_kind is not None:
            wrong.append("actorKind belongs to actors")
        if self.kind != "constraint" and (self.standard is not None or self.applies_to):
            wrong.append("standard and appliesTo belong to constraints")
        if self.kind == "actor" and self.actor_kind is None:
            wrong.append("an actor must say whether it is a person or another system")
        if self.kind == "constraint" and not self.applies_to:
            wrong.append("a constraint must name what it constrains")
        if wrong:
            raise ValueError(f"node {self.id} ({self.kind}): " + "; ".join(wrong))
        return self


class GraphEdge(WireModel):
    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    kind: GraphEdgeKind
    #: The verb that makes the sentence read: "Customer makes Payment".
    verb: str = Field(min_length=1)
    traces: Traces

    @model_validator(mode="after")
    def no_self_edge(self) -> "GraphEdge":
        if self.source == self.target:
            raise ValueError(f"edge {self.id}: a node cannot relate to itself")
        return self


class ArchitectureGraph(WireModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    #: Node ids the current requirements version changed.
    changed_node_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def ids_are_unique(self) -> "ArchitectureGraph":
        for label, items in (
            ("node", [n.id for n in self.nodes]),
            ("edge", [e.id for e in self.edges]),
        ):
            duplicates = sorted({i for i in items if items.count(i) > 1})
            if duplicates:
                raise ValueError(f"duplicate {label} ids: {', '.join(duplicates)}")
        return self

    @model_validator(mode="after")
    def every_reference_resolves(self) -> "ArchitectureGraph":
        """No dangling edges, no constraint pointing at nothing, no phantom
        change highlight. All three are the same failure: an id that does not
        name a node in this graph."""
        known = {n.id for n in self.nodes}
        problems: list[str] = []

        for edge in self.edges:
            for end, node_id in (("source", edge.source), ("target", edge.target)):
                if node_id not in known:
                    problems.append(f"edge {edge.id} has an unknown {end}: {node_id}")

        for node in self.nodes:
            for target in node.applies_to:
                if target not in known:
                    problems.append(f"constraint {node.id} applies to an unknown node: {target}")

        for node_id in self.changed_node_ids:
            if node_id not in known:
                problems.append(f"changedNodeIds names an unknown node: {node_id}")

        if problems:
            raise ValueError("; ".join(problems))
        return self
