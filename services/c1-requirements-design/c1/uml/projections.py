"""Class and entity relationship diagrams, projected from the graph by rule.

No model is involved and none is needed. The entities, their attributes and the
services that own them are already in the graph, so asking a model to draw them
would be asking it to restate data it was given, with a chance of restating it
wrongly.

What this produces is the diagram record: which diagrams exist, what each one
covers, and which requirements it traces to. The picture itself is generated from
the graph at render time, which is why `source` is null: a diagram whose text was
frozen at generation would keep the old name after a node is renamed, and the
whole point of one generative source is that renaming a node changes everything
that reads it.

Traces are computed from the nodes each diagram actually shows, so a diagram
cannot claim to cover a requirement nothing in it came from.
"""

from sdlc_contracts import ArchitectureGraph, UmlDiagram


def _traces_of(graph: ArchitectureGraph, kinds: set[str]) -> list[str]:
    """Every requirement the nodes of these kinds came from, in order.

    Sorted by requirement number rather than by node order, so two runs over the
    same graph produce the same list and a diff between versions shows what
    actually changed.
    """
    found: set[str] = set()
    for node in graph.nodes:
        if node.kind in kinds:
            found.update(node.traces)
    return sorted(found, key=_requirement_order)


def _requirement_order(requirement_id: str) -> tuple[int, str]:
    digits = "".join(character for character in requirement_id if character.isdigit())
    return (int(digits) if digits else 10_000, requirement_id)


def class_diagram(graph: ArchitectureGraph) -> UmlDiagram:
    """The entities and the services that own them."""
    return UmlDiagram(
        id="class",
        kind="class",
        title="Class Diagram",
        description="The domain entities and the services that own them, generated from the graph.",
        # Null on purpose: the picture is built from the graph when it is shown,
        # so a rename reaches it. Freezing the text here would not.
        source=None,
        useCaseId=None,
        traces=_traces_of(graph, {"entity", "service"}),
    )


def er_diagram(graph: ArchitectureGraph) -> UmlDiagram:
    """The same entities, as stored data."""
    return UmlDiagram(
        id="er",
        kind="er",
        title="Entity Relationship Diagram",
        description="The same entities as stored data, generated from the graph.",
        source=None,
        useCaseId=None,
        traces=_traces_of(graph, {"entity"}),
    )


def sequence_diagram(graph: ArchitectureGraph, use_case_id: str, traces: list[str]) -> UmlDiagram:
    """One interaction, drawn from its steps.

    The steps live on the use case rather than here, and the participants in them
    are node ids, so the drawing resolves names from the graph every time it is
    shown.
    """
    return UmlDiagram(
        # Derived from the use case rather than a fixed "sequence", so a second
        # interaction does not silently produce a second diagram with the same
        # id. Nothing validates diagram ids for uniqueness, which makes a
        # collision here a duplicate a reader would see rather than an error.
        id=f"sequence-{use_case_id}",
        kind="sequence",
        title="Sequence Diagram",
        description="One interaction per use case, with names read from the graph.",
        source=None,
        useCaseId=use_case_id,
        traces=sorted(set(traces), key=_requirement_order),
    )


def projected_diagrams(graph: ArchitectureGraph) -> list[UmlDiagram]:
    """The diagrams that need no model at all."""
    return [class_diagram(graph), er_diagram(graph)]
