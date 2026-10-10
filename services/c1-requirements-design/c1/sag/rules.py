"""The seventeen named checks a graph has to pass.

Seventeen, named, and fixed. Not open-ended "does this look right" checking: a
fixed catalogue is what makes a consistency rate a number rather than an
impression, and what lets the evaluation say which rule fired how often across a
corpus.

Every finding carries three things for three different readers:

    rule_id   the evaluation, which counts them
    reason    the person reading the design, in plain words
    hint      the model, on the next attempt of the repair loop

The hint matters more than it looks. "Node n7 'Login Page' is a screen, not an
actor; make it a service or delete it" gets a useful second attempt, where
"invalid graph" gets the same answer again.

Errors block: a graph with one is not promoted to the strict contract type.
Warnings inform: requirement coverage is reported rather than enforced, because
a requirement no node covers is a fact about the design worth showing, not a
reason to refuse the whole graph.
"""

from ..rules.findings import Finding, Report
from ..rules.lexicons import NOISE_WORDS, verb_stem
from .schema import DraftGraph, DraftNode

NODE_KINDS = frozenset({"actor", "entity", "service", "constraint"})
EDGE_KINDS = frozenset({"action", "data", "dependency", "constraint"})
ACTOR_KINDS = frozenset({"primary", "external_system"})

#: Words that name a piece of user interface. An actor is a person or another
#: system; a screen is neither, and a graph that says otherwise produces a domain
#: model reading "Login Page views Account", which is nonsense a reader will
#: blame on the whole tool.
SCREEN_WORDS = frozenset(
    {
        "page",
        "screen",
        "form",
        "dashboard",
        "view",
        "modal",
        "dialog",
        "popup",
        "button",
        "menu",
        "tab",
        "panel",
        "widget",
        "window",
        "layout",
        "ui",
        "interface",
        "wizard",
        "stepper",
        "sidebar",
        "header",
        "footer",
    }
)


#: The finding type is shared with every other rule catalogue in C1, under the
#: names this module has always used. One severity notion and one `to_contract`,
#: so findings stay comparable when the evaluation counts them together.
SagFinding = Finding
ValidationReport = Report


def _words(text: str) -> set[str]:
    return {
        word.strip(".,;:()'\"").lower()
        for word in text.split()
        if len(word.strip(".,;:()'\"")) > 3 and word.strip(".,;:()'\"").lower() not in NOISE_WORDS
    }


def _article(word: str) -> str:
    """ "a" or "an". Small, and this text is read by the person the phase is for."""
    return "an" if word[:1].lower() in "aeiou" else "a"


def _label(node: DraftNode) -> str:
    return node.label or node.id or "an unnamed node"


def validate_sag(
    graph: DraftGraph,
    *,
    requirement_ids: frozenset[str],
    requirements_text: str = "",
) -> ValidationReport:
    """Run all seventeen and collect what they say."""
    findings: list[SagFinding] = []
    for rule in ALL_RULES:
        findings.extend(rule(graph, requirement_ids, requirements_text))
    return ValidationReport(tuple(findings))


# ------------------------------------------------------------- structural (6)


def graph_is_not_empty(graph: DraftGraph, _ids: frozenset[str], _text: str) -> list[SagFinding]:
    """0. The graph has at least one node.

    The only rule here that reads nothing but a length, and the reason it exists
    is that every other rule is written as "for each node" or "for each edge". An
    empty graph therefore satisfies all sixteen of them vacuously and is promoted
    as a finished design.

    That is not hypothetical. A stored artefact of `{"nodes": [], "edges": []}`
    was marked complete on the first attempt with no rule firing, and the UML
    stage then spent its whole retry budget trying to project diagrams from
    nothing before failing.

    The draft type cannot catch this instead. Its fields default to empty on
    purpose, so that a malformed answer arrives as something the repair loop can
    read rather than as an exception, which means a model that returns no
    arguments at all validates cleanly. The guard has to live here.
    """
    if graph.nodes:
        return []
    return [
        SagFinding(
            "graph-is-not-empty",
            "error",
            "The graph is empty, so there is no design to review.",
            "You returned a graph with no nodes. Read the requirements again and "
            "return the actors, entities and services they describe, with the "
            "edges between them.",
        )
    ]


def unique_ids(graph: DraftGraph, _ids: frozenset[str], _text: str) -> list[SagFinding]:
    """1. No two nodes, and no two edges, share an id."""
    findings: list[SagFinding] = []
    for label, items in (("node", graph.nodes), ("edge", graph.edges)):
        seen: set[str] = set()
        for item in items:
            if not item.id:
                findings.append(
                    SagFinding(
                        "unique-ids",
                        "error",
                        f"A {label} has no id, so nothing else can refer to it.",
                        f"Every {label} needs a short unique id. One has none.",
                    )
                )
            elif item.id in seen:
                findings.append(
                    SagFinding(
                        "unique-ids",
                        "error",
                        f"Two {label}s are both called {item.id}, so a reference to it is ambiguous.",
                        f"The {label} id {item.id} is used twice. Give each one its own id.",
                        subject=item.id,
                    )
                )
            else:
                seen.add(item.id)
    return findings


def names_are_present(graph: DraftGraph, _ids: frozenset[str], _text: str) -> list[SagFinding]:
    """16. Nothing the contract requires as text arrives blank.

    A guard on the seam rather than a rule about design. `ArchitectureGraph`
    refuses an empty id, label or verb by raising at construction, and everything
    between here and there is permissive, so a blank reached promotion and came
    back as a pydantic error nobody could act on. A real run died on
    "1 validation error for GraphEdge verb", which says nothing about the design
    and cannot be repaired, because the loop only sends back findings.

    Every contract constraint that can hard fail at promotion needs a rule in
    front of it. This is that rule for the graph, and it is the same one the
    wireframe catalogue already has for the same reason.

    The verb matters on every kind, not only on actions. `action_edge_shape` asks
    whether an action's verb reads as a sentence; the contract asks every edge for
    one, and a data edge with no verb is exactly as unpromotable.
    """
    findings: list[SagFinding] = []

    for index, node in enumerate(graph.nodes):
        if not node.id.strip():
            findings.append(
                SagFinding(
                    "names-are-present",
                    "error",
                    f"The node at position {index + 1} has no id, so nothing can point at it.",
                    f"The node at position {index + 1} has an empty id. Give it a short unique "
                    f"one such as a1, e1 or m1.",
                )
            )
        if not node.label.strip():
            findings.append(
                SagFinding(
                    "names-are-present",
                    "error",
                    f"Node {node.id or index + 1} has no name, so the design cannot say what it is.",
                    f"Node {node.id or index + 1} has an empty label. Name it in the reader's "
                    f"own words.",
                    subject=node.id or None,
                    traces=tuple(node.traces),
                )
            )

    for index, edge in enumerate(graph.edges):
        blank = [
            name
            for name, value in (("id", edge.id), ("source", edge.source), ("target", edge.target))
            if not value.strip()
        ]
        if not edge.verb.strip():
            blank.append("verb")
        if blank:
            findings.append(
                SagFinding(
                    "names-are-present",
                    "error",
                    f"A relationship is missing its {' and '.join(blank)}, so it cannot be drawn.",
                    f"The relationship at position {index + 1} has an empty "
                    f"{', '.join(blank)}. Every relationship needs an id, a source, a target and "
                    f"a present tense verb, whatever its kind.",
                    subject=edge.id or None,
                    traces=tuple(edge.traces),
                )
            )
    return findings


def edge_endpoints_exist(graph: DraftGraph, _ids: frozenset[str], _text: str) -> list[SagFinding]:
    """2. No edge points at a node that is not in the graph.

    Blanks are skipped, because `names_are_present` reports those and this rule's
    sentence would be wrong about them: an empty endpoint is not a reference to a
    node that is missing, it is a reference nobody wrote.
    """
    known = {node.id for node in graph.nodes}
    findings: list[SagFinding] = []
    for edge in graph.edges:
        for end, node_id in (("from", edge.source), ("to", edge.target)):
            if node_id.strip() and node_id not in known:
                findings.append(
                    SagFinding(
                        "edge-endpoints-exist",
                        "error",
                        f"A relationship points {end} {node_id or 'nothing'}, which is not in the graph.",
                        f"Edge {edge.id} goes {end} {node_id!r}, and no node has that id. "
                        f"Either add the node or remove the edge.",
                        subject=edge.id,
                        traces=tuple(edge.traces),
                    )
                )
    return findings


def no_self_edge(graph: DraftGraph, _ids: frozenset[str], _text: str) -> list[SagFinding]:
    """3. Nothing relates to itself."""
    return [
        SagFinding(
            "no-self-edge",
            "error",
            f"{edge.source} is related to itself, which says nothing about the design.",
            f"Edge {edge.id} starts and ends at {edge.source}. Point it at the other node "
            f"it was meant to reach, or remove it.",
            subject=edge.id,
            traces=tuple(edge.traces),
        )
        for edge in graph.edges
        if edge.source and edge.source == edge.target
    ]


def kind_and_fields_agree(graph: DraftGraph, _ids: frozenset[str], _text: str) -> list[SagFinding]:
    """4. Each kind carries its own fields and not another kind's."""
    findings: list[SagFinding] = []
    for node in graph.nodes:
        if node.kind not in NODE_KINDS:
            findings.append(
                SagFinding(
                    "kind-and-fields-agree",
                    "error",
                    f"{_label(node)} has no recognisable kind, so nothing knows how to draw it.",
                    f"Node {node.id} has kind {node.kind!r}. Use one of: "
                    f"{', '.join(sorted(NODE_KINDS))}.",
                    subject=node.id,
                    traces=tuple(node.traces),
                )
            )
            continue

        # Two different faults, and they need different sentences. Carrying
        # another kind's fields is one thing; missing your own is the opposite,
        # and a message saying "carrying fields that belong to something else"
        # about a node that is missing a field sends a reader looking for
        # something that is not there. A real run reported exactly that.
        borrowed: list[str] = []
        missing: list[str] = []

        if node.kind != "entity" and node.attributes:
            borrowed.append(
                "only an entity has fields, so move these to the entity they describe or remove them"
            )
        if node.kind != "actor" and node.actor_kind:
            borrowed.append("actor_kind belongs to actors, so remove it")
        if node.kind != "constraint" and (node.standard or node.applies_to):
            borrowed.append("standard and appliesTo belong to constraints, so remove them")
        if node.kind == "actor" and node.actor_kind not in ACTOR_KINDS:
            missing.append(
                "set actor_kind to 'primary' for a person or 'external_system' for another system"
            )

        if borrowed:
            findings.append(
                SagFinding(
                    "kind-and-fields-agree",
                    "error",
                    f"{_label(node)} is {_article(node.kind)} {node.kind} carrying fields that "
                    f"belong to something else.",
                    f"Node {node.id} ({node.kind}): {'; '.join(borrowed)}.",
                    subject=node.id,
                    traces=tuple(node.traces),
                )
            )
        if missing:
            findings.append(
                SagFinding(
                    "kind-and-fields-agree",
                    "error",
                    f"{_label(node)} does not say whether it is a person or another system.",
                    f"Node {node.id} ({node.kind}): {'; '.join(missing)}.",
                    subject=node.id,
                    traces=tuple(node.traces),
                )
            )

    for edge in graph.edges:
        if edge.kind not in EDGE_KINDS:
            findings.append(
                SagFinding(
                    "kind-and-fields-agree",
                    "error",
                    "A relationship has no recognisable kind.",
                    f"Edge {edge.id} has kind {edge.kind!r}. Use one of: "
                    f"{', '.join(sorted(EDGE_KINDS))}.",
                    subject=edge.id,
                    traces=tuple(edge.traces),
                )
            )
    return findings


def constraint_is_attached(graph: DraftGraph, _ids: frozenset[str], _text: str) -> list[SagFinding]:
    """5. A rule names what it binds, and those nodes exist."""
    known = {node.id for node in graph.nodes}
    findings: list[SagFinding] = []
    for node in graph.nodes:
        if node.kind != "constraint":
            continue
        if not node.applies_to:
            findings.append(
                SagFinding(
                    "constraint-is-attached",
                    "error",
                    f"{_label(node)} is a rule the design does not actually apply anywhere.",
                    f"Constraint {node.id} names nothing in appliesTo. List the node ids it "
                    f"binds, or remove it.",
                    subject=node.id,
                    traces=tuple(node.traces),
                )
            )
            continue
        missing = [target for target in node.applies_to if target not in known]
        if missing:
            findings.append(
                SagFinding(
                    "constraint-is-attached",
                    "error",
                    f"{_label(node)} binds {', '.join(missing)}, which is not in the graph.",
                    f"Constraint {node.id} applies to {missing}, and no node has those ids.",
                    subject=node.id,
                    traces=tuple(node.traces),
                )
            )
    return findings


def no_isolated_node(graph: DraftGraph, _ids: frozenset[str], _text: str) -> list[SagFinding]:
    """6. Every node is connected to something."""
    if len(graph.nodes) <= 1:
        return []
    touched: set[str] = set()
    for edge in graph.edges:
        touched.update({edge.source, edge.target})
    for node in graph.nodes:
        if node.kind == "constraint":
            # A constraint binds through appliesTo rather than through an edge.
            touched.update(node.applies_to)
            touched.add(node.id)

    return [
        SagFinding(
            "no-isolated-node",
            "error",
            f"{_label(node)} is not connected to anything, so it plays no part in the design.",
            f"Node {node.id} has no edges. Relate it to something, or remove it.",
            subject=node.id,
            traces=tuple(node.traces),
        )
        for node in graph.nodes
        if node.id not in touched
    ]


# ----------------------------------------------------------- traceability (4)


def node_is_traced(graph: DraftGraph, _ids: frozenset[str], _text: str) -> list[SagFinding]:
    """7. Every node came from a requirement."""
    return [
        SagFinding(
            "node-is-traced",
            "error",
            f"{_label(node)} traces to no requirement, so nothing explains why it is here.",
            f"Node {node.id} has an empty traces list. Name the requirement ids it came "
            f"from, or remove it.",
            subject=node.id,
        )
        for node in graph.nodes
        if not node.traces
    ]


def edge_is_traced(graph: DraftGraph, _ids: frozenset[str], _text: str) -> list[SagFinding]:
    """8. Every relationship came from a requirement."""
    return [
        SagFinding(
            "edge-is-traced",
            "error",
            "A relationship traces to no requirement, so nothing explains why it is here.",
            f"Edge {edge.id} has an empty traces list. Name the requirement ids it came from.",
            subject=edge.id,
        )
        for edge in graph.edges
        if not edge.traces
    ]


def traces_resolve(graph: DraftGraph, ids: frozenset[str], _text: str) -> list[SagFinding]:
    """9. Every trace names a requirement that exists.

    The rule that catches a model inventing R-14 to justify a node it wanted.
    """
    findings: list[SagFinding] = []
    for node in graph.nodes:
        unknown = [trace for trace in node.traces if trace not in ids]
        if unknown:
            findings.append(
                SagFinding(
                    "traces-resolve",
                    "error",
                    f"{_label(node)} claims to come from {', '.join(unknown)}, which does not exist.",
                    f"Node {node.id} traces to {unknown}. Those are not requirement ids. "
                    f"Use ids from the list you were given.",
                    subject=node.id,
                    traces=tuple(t for t in node.traces if t in ids),
                )
            )
    for edge in graph.edges:
        unknown = [trace for trace in edge.traces if trace not in ids]
        if unknown:
            findings.append(
                SagFinding(
                    "traces-resolve",
                    "error",
                    f"A relationship claims to come from {', '.join(unknown)}, which does not exist.",
                    f"Edge {edge.id} traces to {unknown}, which are not requirement ids.",
                    subject=edge.id,
                    traces=tuple(t for t in edge.traces if t in ids),
                )
            )
    return findings


def requirement_coverage(graph: DraftGraph, ids: frozenset[str], _text: str) -> list[SagFinding]:
    """10. Which requirements no part of the design covers.

    A warning, not an error. This is the traceability completeness measure the
    evaluation reports, so it is counted and shown rather than used to refuse a
    graph: a requirement with no node is a real gap, and hiding it behind a
    rejected graph helps nobody.
    """
    covered = {trace for node in graph.nodes for trace in node.traces}
    covered |= {trace for edge in graph.edges for trace in edge.traces}
    uncovered = sorted(ids - covered)
    if not uncovered:
        return []
    return [
        SagFinding(
            "requirement-coverage",
            "warning",
            f"Nothing in the design covers {', '.join(uncovered)}.",
            f"These requirements have no node or edge: {uncovered}. Add what they ask for, "
            f"or say why they need nothing.",
            traces=tuple(uncovered),
        )
    ]


# --------------------------------------------------------------- semantic (5)


def action_edge_shape(graph: DraftGraph, _ids: frozenset[str], _text: str) -> list[SagFinding]:
    """11. An action reads as a sentence, with a present tense verb.

    Action edges are what the domain model renders as "Customer makes Payment",
    so an edge with no verb, or a verb in the past, produces a sentence that
    reads as broken English on a page a reader is asked to approve.
    """
    by_id = {node.id: node for node in graph.nodes}
    findings: list[SagFinding] = []
    for edge in graph.edges:
        if edge.kind != "action":
            continue

        verb = edge.verb.strip()
        if not verb:
            findings.append(
                SagFinding(
                    "action-edge-shape",
                    "error",
                    "An action has no verb, so it does not say what happens.",
                    f"Edge {edge.id} is an action with an empty verb. Give it one in the "
                    f"present tense, so it reads 'X {{verb}} Y'.",
                    subject=edge.id,
                    traces=tuple(edge.traces),
                )
            )
            continue

        first = verb.split()[0].lower()
        if first.endswith("ed") or first.endswith("ing"):
            findings.append(
                SagFinding(
                    "action-edge-shape",
                    "error",
                    f"The action '{verb}' is not in the present tense, so the sentence does not read.",
                    f"Edge {edge.id} uses {verb!r}. Write it in the present tense, for example "
                    f"{verb_stem(first) or 'make'!r}.",
                    subject=edge.id,
                    traces=tuple(edge.traces),
                )
            )

        source = by_id.get(edge.source)
        if source is not None and source.kind == "constraint":
            findings.append(
                SagFinding(
                    "action-edge-shape",
                    "error",
                    f"{_label(source)} is a rule, and a rule does not perform actions.",
                    f"Edge {edge.id} makes constraint {edge.source} the actor of an action. "
                    f"A rule binds things through appliesTo; it does not do them.",
                    subject=edge.id,
                    traces=tuple(edge.traces),
                )
            )
    return findings


def entity_has_attributes(graph: DraftGraph, _ids: frozenset[str], _text: str) -> list[SagFinding]:
    """12. An entity says what it holds.

    The class and entity relationship diagrams are generated from these, so an
    entity with none renders as an empty box.
    """
    return [
        SagFinding(
            "entity-has-attributes",
            "error",
            f"{_label(node)} is something the system keeps, but nothing says what it holds.",
            f"Entity {node.id} has no attributes. Name the fields it holds, even if only an "
            f"id and one more, since the class diagram is generated from them.",
            subject=node.id,
            traces=tuple(node.traces),
        )
        for node in graph.nodes
        if node.kind == "entity" and not node.attributes
    ]


def actor_is_not_a_screen(graph: DraftGraph, _ids: frozenset[str], _text: str) -> list[SagFinding]:
    """13. An actor is a person or another system, never a piece of interface.

    A real and common failure mode, and the one most visible to a reader: it
    turns the domain model into "Login Page views Account".
    """
    findings: list[SagFinding] = []
    for node in graph.nodes:
        if node.kind != "actor":
            continue
        offending = _words(node.label) & SCREEN_WORDS
        if offending:
            findings.append(
                SagFinding(
                    "actor-is-not-a-screen",
                    "error",
                    f"{_label(node)} looks like a screen, and a screen is not someone who uses "
                    f"the system.",
                    f"Node {node.id} is an actor called {node.label!r}. That is a piece of "
                    f"interface, not a person or another system. Name whoever uses that "
                    f"screen instead, or make it a service.",
                    subject=node.id,
                    traces=tuple(node.traces),
                )
            )
    return findings


def label_is_grounded(graph: DraftGraph, _ids: frozenset[str], text: str) -> list[SagFinding]:
    """14. Node names use the reader's vocabulary, not invented jargon.

    A warning rather than an error: a design may reasonably name something the
    brief did not, and refusing the whole graph for it would be too strict. But
    a graph full of words nobody wrote is a graph about a different system, and
    the reader should be told which names came from nowhere.
    """
    if not text.strip():
        return []
    vocabulary = _words(text)
    findings: list[SagFinding] = []
    for node in graph.nodes:
        label_words = _words(node.label)
        if not label_words:
            continue
        if not (label_words & vocabulary):
            findings.append(
                SagFinding(
                    "label-is-grounded",
                    "warning",
                    f"Nothing in your input uses the words in {_label(node)}.",
                    f"Node {node.id} is called {node.label!r}, and none of those words appear "
                    f"in the requirements. Use the reader's own vocabulary where you can.",
                    subject=node.id,
                    traces=tuple(node.traces),
                )
            )
    return findings


def no_orphan_service(graph: DraftGraph, _ids: frozenset[str], _text: str) -> list[SagFinding]:
    """15. A service owns data or calls something.

    Distinct from rule 6, and deliberately so. Rule 6 catches a node joined to
    nothing at all. This catches a service that is joined to something and still
    does nothing: an action edge pointing at it means somebody uses it, not that
    it holds or calls anything. Counting action edges here would make this rule
    fire only when rule 6 already had, which is a rule that never earns its place
    in the catalogue.
    """
    findings: list[SagFinding] = []
    for node in graph.nodes:
        if node.kind != "service":
            continue
        does_something = any(
            edge.source == node.id or edge.target == node.id
            for edge in graph.edges
            if edge.kind in {"data", "dependency"}
        )
        if not does_something:
            findings.append(
                SagFinding(
                    "no-orphan-service",
                    "error",
                    f"{_label(node)} owns no data and calls nothing, so it does nothing.",
                    f"Service {node.id} has no data or dependency edge. Say what it owns or "
                    f"what it calls, or remove it.",
                    subject=node.id,
                    traces=tuple(node.traces),
                )
            )
    return findings


#: All sixteen, in the order they are reported. Structural first, because a graph
#: that does not hold together makes the semantic findings noise.
ALL_RULES = (
    graph_is_not_empty,
    unique_ids,
    names_are_present,
    edge_endpoints_exist,
    no_self_edge,
    kind_and_fields_agree,
    constraint_is_attached,
    no_isolated_node,
    node_is_traced,
    edge_is_traced,
    traces_resolve,
    requirement_coverage,
    action_edge_shape,
    entity_has_attributes,
    actor_is_not_a_screen,
    label_is_grounded,
    no_orphan_service,
)

#: The names, for the evaluation and for the test that pins the catalogue.
RULE_IDS = (
    "graph-is-not-empty",
    "unique-ids",
    "names-are-present",
    "edge-endpoints-exist",
    "no-self-edge",
    "kind-and-fields-agree",
    "constraint-is-attached",
    "no-isolated-node",
    "node-is-traced",
    "edge-is-traced",
    "traces-resolve",
    "requirement-coverage",
    "action-edge-shape",
    "entity-has-attributes",
    "actor-is-not-a-screen",
    "label-is-grounded",
    "no-orphan-service",
)
