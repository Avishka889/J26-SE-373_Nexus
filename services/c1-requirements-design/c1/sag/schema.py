"""What the model may return for a graph, before anything is checked.

Deliberately permissive, and that is not laziness.

`sdlc_contracts.ArchitectureGraph` refuses a graph with duplicate ids or dangling
edges by raising at construction. That is right for a graph on the wire, and
useless for a repair loop: an exception says the model got something wrong
without saying what, and there is nothing structured to hand back to it. So the
model answers in this shape, the fifteen rules read it and produce findings with
hints, and only a draft that passes is promoted to the strict type.

Everything here is a plain field with no cross-validation. The validation lives in
`rules.py`, where a violation becomes a sentence rather than a stack trace.
"""

from pydantic import BaseModel, Field


class DraftAttribute(BaseModel):
    name: str = ""
    type: str = ""


class DraftNode(BaseModel):
    """One node as the model described it."""

    id: str = Field(default="", description="Short and unique, for example 'a1' or 'e2'.")
    kind: str = Field(
        default="",
        description="One of: actor, entity, service, constraint. Nothing else.",
    )
    label: str = Field(default="", description="What it is called, in the reader's own words.")
    description: str = ""
    traces: list[str] = Field(
        default_factory=list,
        description="The requirement ids this came from, for example ['R-1', 'R-3'].",
    )
    attributes: list[DraftAttribute] = Field(
        default_factory=list, description="Entities only: the fields it holds."
    )
    actor_kind: str = Field(
        default="",
        description="Actors only: 'primary' for a person, 'external_system' for another system.",
    )
    standard: str = Field(default="", description="Constraints only, for example 'PCI DSS 4.0'.")
    applies_to: list[str] = Field(
        default_factory=list, description="Constraints only: the node ids this binds."
    )


class DraftEdge(BaseModel):
    """One relationship as the model described it."""

    id: str = Field(default="", description="Short and unique, for example 'x1'.")
    source: str = Field(default="", description="The node id this starts at.")
    target: str = Field(default="", description="The node id this ends at.")
    kind: str = Field(
        default="",
        description="One of: action, data, dependency, constraint.",
    )
    verb: str = Field(
        default="",
        description="Present tense, so the sentence reads: 'Customer makes Payment'.",
    )
    traces: list[str] = Field(
        default_factory=list, description="The requirement ids this came from."
    )


class DraftGraph(BaseModel):
    """A graph the model produced, before the rules have read it.

    These two are the only required fields in this module, and the exception is
    the point. Everything inside a node or an edge defaults, so a wrong answer
    arrives as something the rules can explain. These do not, because an answer
    missing them is not a wrong graph, it is not a graph.

    That distinction cost two runs to find. With both optional the generated tool
    schema had `required: []` at every level, so a forced tool call was satisfied
    by `{}`: one run stored a graph with nothing in it, and the next returned the
    nodes and omitted the edges, leaving every node isolated. The instructions say
    "every node has to be wired" and give a worked example; a model doing
    structured output follows the schema, and the schema said the field was
    optional.

    Required here means a missing field is a validation error, which pydantic-ai
    hands back to the model as "edges: Field required" and retries. That is the
    behaviour the permissiveness was protecting in the first place: a reason the
    model can act on, rather than silence.
    """

    nodes: list[DraftNode] = Field(
        description="Every node in the graph. Required: answer with the list, even if short."
    )
    edges: list[DraftEdge] = Field(
        description=(
            "Every edge in the graph. Required: a graph of nodes with no edges is "
            "not an answer. Each node id you created must appear here."
        )
    )
