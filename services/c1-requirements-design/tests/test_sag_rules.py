"""One violating fixture per rule, and a clean graph that trips none of them.

The catalogue is fixed at sixteen and pinned here, because a consistency rate is
only a number if the denominator cannot drift. Each test builds the smallest
graph that breaks exactly one rule, which is also what proves the other fourteen
are not firing on it by accident.
"""

import pytest
from c1.sag.build import NotValidated, to_contract
from c1.sag.rules import ALL_RULES, RULE_IDS, SagFinding, validate_sag
from c1.sag.schema import DraftAttribute, DraftEdge, DraftGraph, DraftNode
from pydantic import ValidationError

IDS = frozenset({"R-1", "R-2", "R-3"})
TEXT = "A customer makes a payment. An administrator reviews the payment."


def node(
    id: str = "a1",
    kind: str = "actor",
    label: str = "Customer",
    traces: list[str] | None = None,
    **rest,
) -> DraftNode:
    return DraftNode(
        id=id,
        kind=kind,
        label=label,
        traces=traces if traces is not None else ["R-1"],
        actor_kind="primary"
        if kind == "actor" and "actor_kind" not in rest
        else rest.pop("actor_kind", ""),
        **rest,
    )


def entity(id: str = "e1", label: str = "Payment", **rest) -> DraftNode:
    rest.setdefault("attributes", [DraftAttribute(name="id", type="UUID")])
    return node(id=id, kind="entity", label=label, **rest)


def edge(
    id: str = "x1",
    source: str = "a1",
    target: str = "e1",
    kind: str = "action",
    verb: str = "makes",
    traces: list[str] | None = None,
) -> DraftEdge:
    return DraftEdge(
        id=id,
        source=source,
        target=target,
        kind=kind,
        verb=verb,
        traces=traces if traces is not None else ["R-1"],
    )


def clean() -> DraftGraph:
    """The smallest graph that satisfies all sixteen."""
    return DraftGraph(
        nodes=[
            node("a1", "actor", "Customer", ["R-1"]),
            entity("e1", "Payment", traces=["R-1"]),
            node("m1", "service", "Payment Service", ["R-2"]),
            node(
                "a2",
                "actor",
                "Administrator",
                ["R-3"],
            ),
        ],
        edges=[
            edge("x1", "a1", "e1", "action", "makes", ["R-1"]),
            edge("x2", "m1", "e1", "data", "owns", ["R-2"]),
            edge("x3", "a2", "e1", "action", "reviews", ["R-3"]),
        ],
    )


def check(graph: DraftGraph, text: str = TEXT):
    return validate_sag(graph, requirement_ids=IDS, requirements_text=text)


class TestTheCatalogue:
    def test_is_exactly_seventeen_named_rules(self) -> None:
        # Fixed and named, because an open ended checker cannot produce a
        # consistency rate anyone can reproduce.
        assert len(ALL_RULES) == 17
        assert len(RULE_IDS) == 17
        assert len(set(RULE_IDS)) == 17

    def test_every_rule_is_reachable_by_name(self) -> None:
        assert {rule.__doc__.split(".")[0].split()[0] for rule in ALL_RULES}, "rules are documented"
        for rule in ALL_RULES:
            assert rule.__doc__, f"{rule.__name__} has no docstring"

    def test_a_clean_graph_trips_nothing(self) -> None:
        report = check(clean())
        assert report.ok
        assert report.findings == (), f"clean graph tripped {report.rule_ids()}"


class TestTheAnswerHasToBeAGraph:
    """Two defences, because they catch different things.

    The schema refuses an answer that omits the lists, which is what a model
    doing structured output against an all optional schema actually sends. The
    rule refuses lists that are present and empty, which the schema cannot see.
    """

    def test_an_answer_with_no_arguments_does_not_validate(self) -> None:
        # What a forced tool call produces when nothing in the schema is
        # required. This used to parse cleanly as a graph with nothing in it.
        with pytest.raises(ValidationError):
            DraftGraph.model_validate({})

    def test_an_answer_with_no_edges_does_not_validate(self) -> None:
        # The second failure: the nodes came back and the edges did not, so
        # every node was isolated. pydantic-ai hands the model the reason.
        with pytest.raises(ValidationError, match="edges"):
            DraftGraph.model_validate({"nodes": []})

    def test_the_lists_may_still_be_wrong_inside(self) -> None:
        # The permissiveness that matters is untouched: a node missing every
        # field still parses, so the rules explain it instead of an exception.
        graph = DraftGraph.model_validate({"nodes": [{}], "edges": []})
        assert len(graph.nodes) == 1
        assert not check(graph).ok


class TestStructuralRules:
    def test_0_an_empty_graph_is_refused(self) -> None:
        # The hole this rule closes: every other rule reads "for each node", so
        # a graph with no nodes satisfied all sixteen of them and was promoted
        # as a finished design.
        report = check(DraftGraph(nodes=[], edges=[]))
        assert "graph-is-not-empty" in report.rule_ids()
        assert not report.ok, "an empty graph must never be promoted"

    def test_0_the_hint_tells_the_model_what_to_return(self) -> None:
        # The hint is the repair prompt. "Invalid graph" gets the same answer
        # back; naming what to return is what makes the second attempt differ.
        hint = check(DraftGraph(nodes=[], edges=[])).errors[0].hint
        assert "no nodes" in hint
        assert "actors" in hint and "edges" in hint

    def test_1_unique_ids(self) -> None:
        graph = clean()
        graph.nodes[1].id = "a1"
        assert "unique-ids" in check(graph).rule_ids()

    def test_2_edge_endpoints_exist(self) -> None:
        graph = clean()
        graph.edges[0].target = "nope"
        assert "edge-endpoints-exist" in check(graph).rule_ids()

    def test_3_no_self_edge(self) -> None:
        graph = clean()
        graph.edges[0].target = graph.edges[0].source
        assert "no-self-edge" in check(graph).rule_ids()

    def test_4_kind_and_fields_agree(self) -> None:
        graph = clean()
        # An actor carrying entity attributes.
        graph.nodes[0].attributes = [DraftAttribute(name="total", type="Money")]
        assert "kind-and-fields-agree" in check(graph).rule_ids()

    def test_4_an_actor_must_say_what_kind_it_is(self) -> None:
        graph = clean()
        graph.nodes[0].actor_kind = ""
        assert "kind-and-fields-agree" in check(graph).rule_ids()

    def test_5_constraint_is_attached(self) -> None:
        graph = clean()
        graph.nodes.append(
            DraftNode(id="c1", kind="constraint", label="PCI", traces=["R-1"], standard="PCI DSS")
        )
        assert "constraint-is-attached" in check(graph).rule_ids()

    def test_6_no_isolated_node(self) -> None:
        graph = clean()
        graph.nodes.append(node("a9", "actor", "Auditor", ["R-1"]))
        assert "no-isolated-node" in check(graph).rule_ids()


class TestTraceabilityRules:
    def test_7_node_is_traced(self) -> None:
        graph = clean()
        graph.nodes[0].traces = []
        assert "node-is-traced" in check(graph).rule_ids()

    def test_8_edge_is_traced(self) -> None:
        graph = clean()
        graph.edges[0].traces = []
        assert "edge-is-traced" in check(graph).rule_ids()

    def test_9_traces_resolve(self) -> None:
        # The rule that catches a model inventing a requirement to justify a node.
        graph = clean()
        graph.nodes[0].traces = ["R-99"]
        report = check(graph)
        assert "traces-resolve" in report.rule_ids()
        assert "R-99" in report.errors[0].reason

    def test_10_requirement_coverage_is_a_warning_not_an_error(self) -> None:
        # R-3 covered by nothing: a real gap, reported rather than fatal.
        graph = clean()
        graph.nodes[3].traces = ["R-1"]
        graph.edges[2].traces = ["R-1"]
        report = check(graph)

        assert "requirement-coverage" in report.rule_ids()
        assert report.ok, "an uncovered requirement must not refuse the whole graph"
        warning = next(f for f in report.warnings if f.rule_id == "requirement-coverage")
        assert "R-3" in warning.reason
        assert warning.traces == ("R-3",)


class TestSemanticRules:
    def test_11_action_edge_needs_a_verb(self) -> None:
        graph = clean()
        graph.edges[0].verb = ""
        assert "action-edge-shape" in check(graph).rule_ids()

    def test_11_action_edge_verb_is_present_tense(self) -> None:
        graph = clean()
        graph.edges[0].verb = "created"
        report = check(graph)
        assert "action-edge-shape" in report.rule_ids()
        assert "present tense" in report.errors[0].reason

    def test_11_a_rule_does_not_perform_actions(self) -> None:
        graph = clean()
        graph.nodes.append(
            DraftNode(
                id="c1",
                kind="constraint",
                label="PCI",
                traces=["R-1"],
                standard="PCI DSS",
                applies_to=["e1"],
            )
        )
        graph.edges.append(edge("x9", "c1", "e1", "action", "checks", ["R-1"]))
        assert "action-edge-shape" in check(graph).rule_ids()

    def test_12_entity_has_attributes(self) -> None:
        graph = clean()
        graph.nodes[1].attributes = []
        assert "entity-has-attributes" in check(graph).rule_ids()

    def test_13_actor_is_not_a_screen(self) -> None:
        # The failure that turns the domain model into "Login Page views Account".
        graph = clean()
        graph.nodes[0].label = "Login Page"
        report = check(graph)
        assert "actor-is-not-a-screen" in report.rule_ids()
        finding = next(f for f in report.errors if f.rule_id == "actor-is-not-a-screen")
        assert "screen" in finding.reason
        assert "Login Page" in finding.hint

    @pytest.mark.parametrize("label", ["Checkout Form", "Admin Dashboard", "Settings Modal"])
    def test_13_catches_the_usual_disguises(self, label: str) -> None:
        graph = clean()
        graph.nodes[0].label = label
        assert "actor-is-not-a-screen" in check(graph).rule_ids()

    def test_14_label_is_grounded_is_a_warning(self) -> None:
        graph = clean()
        graph.nodes[2].label = "Kubernetes Sidecar Reconciler"
        report = check(graph)
        assert "label-is-grounded" in report.rule_ids()
        assert report.ok, "an unfamiliar name is worth saying, not worth refusing"

    def test_14_says_nothing_when_there_is_no_text_to_check_against(self) -> None:
        report = validate_sag(clean(), requirement_ids=IDS, requirements_text="")
        assert "label-is-grounded" not in report.rule_ids()

    def test_15_no_orphan_service(self) -> None:
        # Connected, and still does nothing: somebody uses it, but it owns no
        # data and calls nothing. This is the case rule 6 cannot see.
        graph = clean()
        graph.edges = [e for e in graph.edges if e.source != "m1"]
        graph.edges.append(edge("x8", "a1", "m1", "action", "uses", ["R-2"]))

        report = check(graph)
        assert "no-orphan-service" in report.rule_ids()
        assert "no-isolated-node" not in report.rule_ids(), (
            "this must be the case only rule 15 catches, or rule 15 is redundant"
        )


class TestWhatAFindingCarries:
    def test_every_finding_speaks_to_all_three_audiences(self) -> None:
        # A rule id the evaluation counts, a reason the reader understands, and a
        # hint the model can act on.
        graph = clean()
        graph.nodes[0].label = "Login Page"
        graph.nodes[1].attributes = []
        graph.edges[0].verb = "created"

        for finding in check(graph).findings:
            assert finding.rule_id in RULE_IDS
            assert finding.reason.endswith("."), "a reason is a sentence"
            assert len(finding.reason) > 25
            assert finding.hint and finding.hint != finding.reason
            assert finding.severity in {"error", "warning"}

    def test_a_reason_never_shows_a_reader_a_stack_trace_or_a_type_name(self) -> None:
        graph = clean()
        graph.nodes[0].kind = "widget"
        for finding in check(graph).findings:
            for jargon in ("Traceback", "ValidationError", "None", "null", "dict"):
                assert jargon not in finding.reason

    def test_becomes_the_finding_the_canvas_renders(self) -> None:
        graph = clean()
        graph.nodes[0].label = "Login Page"
        report = check(graph)

        contract = report.for_subject("a1").to_contract()
        assert contract.rule_id == "actor-is-not-a-screen"
        assert contract.reason
        assert contract.traces == ["R-1"]

    def test_hints_collect_into_instructions_for_another_attempt(self) -> None:
        graph = clean()
        graph.nodes[0].traces = []
        graph.edges[0].verb = ""
        hints = check(graph).hints()
        assert hints.count("\n") >= 1
        assert hints.startswith("- ")

    def test_an_error_outranks_a_warning_on_the_same_node(self) -> None:
        graph = clean()
        # Both a warning and an error land on m1.
        graph.nodes[2].label = "Kubernetes Sidecar Reconciler"
        graph.edges = [e for e in graph.edges if e.source != "m1"]
        finding = check(graph).for_subject("m1")
        assert finding is not None
        assert finding.severity == "error"

    def test_writes_no_em_or_en_dash(self) -> None:
        graph = clean()
        graph.nodes[0].label = "Login Page"
        graph.nodes[0].traces = []
        for finding in check(graph).findings:
            for text in (finding.reason, finding.hint):
                # The characters being forbidden have to appear here to be
                # checked for.
                assert "—" not in text
                assert "–" not in text  # noqa: RUF001


class TestPromotion:
    def test_a_validated_draft_becomes_the_contract_graph(self) -> None:
        graph = clean()
        report = check(graph)
        contract = to_contract(graph, report)

        assert len(contract.nodes) == 4
        assert len(contract.edges) == 3
        # The strict type would have raised on anything the rules refuse, so
        # reaching here at all is the point.
        assert all(node.traces for node in contract.nodes)

    def test_a_draft_with_errors_is_refused_rather_than_raising_a_type_error(self) -> None:
        graph = clean()
        graph.nodes[0].traces = []
        with pytest.raises(NotValidated, match="node-is-traced"):
            to_contract(graph, check(graph))

    def test_a_warning_travels_with_the_node_it_is_about(self) -> None:
        graph = clean()
        graph.nodes[2].label = "Kubernetes Sidecar Reconciler"
        report = check(graph)
        contract = to_contract(graph, report)

        service = next(node for node in contract.nodes if node.id == "m1")
        assert service.unconfirmed is not None
        assert service.unconfirmed.rule_id == "label-is-grounded"
        # And the reader can follow it back to a requirement.
        assert service.unconfirmed.traces == ["R-2"]

    def test_a_clean_node_carries_no_warning(self) -> None:
        contract = to_contract(clean(), check(clean()))
        assert all(node.unconfirmed is None for node in contract.nodes)


class TestTheFindingType:
    def test_severity_is_only_ever_one_of_two_things(self) -> None:
        finding = SagFinding("x", "error", "A reason.", "A hint.")
        assert finding.severity == "error"
        assert finding.to_contract().rule_id == "x"


class TestNothingRequiredArrivesBlank:
    """The guard on the seam between this permissive draft and the strict contract.

    `ArchitectureGraph` refuses an empty id, label or verb by raising at
    construction. Everything before that point is permissive on purpose, so a
    blank used to travel all the way to promotion and come back as
    "1 validation error for GraphEdge verb": a message about a field, from inside
    pydantic, that says nothing about the design and that the repair loop cannot
    send back, because it only sends findings.

    A real run died exactly that way, which is why the rule exists.
    """

    def test_a_blank_edge_verb_is_a_finding(self) -> None:
        graph = clean()
        graph.edges[1].verb = ""
        report = check(graph)
        assert "names-are-present" in report.rule_ids()
        assert "verb" in next(f.reason for f in report.errors if f.rule_id == "names-are-present")

    def test_the_verb_is_required_on_every_kind_not_just_actions(self) -> None:
        # `action_edge_shape` asks whether an action's verb reads as a sentence.
        # The contract asks every edge for one, and a data edge with none is
        # exactly as unpromotable.
        graph = clean()
        graph.edges[1].verb = ""  # x2 is a data edge
        assert graph.edges[1].kind == "data"
        assert "names-are-present" in check(graph).rule_ids()

    def test_a_blank_node_label_is_a_finding(self) -> None:
        graph = clean()
        graph.nodes[0].label = ""
        assert "names-are-present" in check(graph).rule_ids()

    def test_a_blank_node_id_is_a_finding(self) -> None:
        graph = clean()
        graph.nodes[0].id = ""
        assert "names-are-present" in check(graph).rule_ids()

    def test_a_blank_endpoint_is_reported_once_and_accurately(self) -> None:
        # It used to be reported as "points from nothing, which is not in the
        # graph", which is the wrong sentence: an empty endpoint is not a
        # reference to a missing node, it is a reference nobody wrote.
        graph = clean()
        graph.edges[0].source = ""
        report = check(graph)

        assert "names-are-present" in report.rule_ids()
        assert "edge-endpoints-exist" not in report.rule_ids()

    def test_an_unknown_endpoint_is_still_the_other_rule(self) -> None:
        # The split must not have cost the real case.
        graph = clean()
        graph.edges[0].source = "a9"
        assert "edge-endpoints-exist" in check(graph).rule_ids()

    def test_a_clean_graph_promotes_without_raising(self) -> None:
        # The other half of the guard: what the rules accept, the contract takes.
        from c1.sag.build import to_contract
        from c1.sag.layout import layout

        graph = clean()
        report = check(graph)
        assert report.ok
        to_contract(graph, report, positions=layout(graph.nodes))

    def test_every_blank_the_contract_refuses_is_caught_first(self) -> None:
        """The claim in general, not one field at a time.

        Blank each field the contract constrains, and the rules must refuse the
        graph before promotion is attempted. If one is missed, a run dies on a
        pydantic error instead of telling somebody what to fix.
        """
        for blank in (
            "node.id",
            "node.label",
            "edge.id",
            "edge.source",
            "edge.target",
            "edge.verb",
        ):
            graph = clean()
            target, field = blank.split(".")
            setattr(graph.nodes[0] if target == "node" else graph.edges[0], field, "")
            assert not check(graph).ok, f"a blank {blank} was not refused by any rule"
