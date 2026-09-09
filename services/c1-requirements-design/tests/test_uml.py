"""Class and ER by rule, sequence by model, and the checks that keep names live.

The property running through all of it: no diagram ever holds a copy of a name.
Class and ER are drawn from the graph when they are shown, and a sequence step
refers to a participant by id and writes any name inside a message as a token. A
node renamed after generation therefore changes every diagram, which is what one
generative source is supposed to buy.
"""

import json

import pytest
from c1.uml.projections import class_diagram, er_diagram, projected_diagrams, sequence_diagram
from c1.uml.sequence import (
    DraftInteraction,
    DraftStep,
    blank_participants,
    build_sequence_agent,
    names_typed_instead_of_ids,
    prompt_for,
    unknown_participants,
    unresolved_tokens,
    write_interaction,
)
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sdlc_contracts import (
    ArchitectureGraph,
    EntityAttribute,
    GraphEdge,
    GraphNode,
    Position,
)


def graph() -> ArchitectureGraph:
    return ArchitectureGraph(
        nodes=[
            GraphNode(
                id="a1",
                kind="actor",
                label="Customer",
                position=Position(x=0, y=0),
                traces=["R-1"],
                actorKind="primary",
            ),
            GraphNode(
                id="a2",
                kind="actor",
                label="Payment Provider",
                position=Position(x=0, y=160),
                traces=["R-2"],
                actorKind="external_system",
            ),
            GraphNode(
                id="e1",
                kind="entity",
                label="Payment",
                position=Position(x=720, y=0),
                traces=["R-1", "R-3"],
                attributes=[EntityAttribute(name="id", type="UUID")],
            ),
            GraphNode(
                id="m1",
                kind="service",
                label="Payment Service",
                position=Position(x=340, y=0),
                traces=["R-2"],
            ),
            GraphNode(
                id="c1",
                kind="constraint",
                label="PCI",
                position=Position(x=1080, y=0),
                traces=["R-9"],
                standard="PCI DSS",
                appliesTo=["e1"],
            ),
        ],
        edges=[
            GraphEdge(
                id="x1", source="a1", target="e1", kind="action", verb="makes", traces=["R-1"]
            ),
            GraphEdge(id="d1", source="m1", target="e1", kind="data", verb="owns", traces=["R-2"]),
        ],
    )


class TestProjectedByRule:
    def test_the_picture_is_never_frozen_into_the_record(self) -> None:
        # Null source means "draw this from the graph when you show it". A frozen
        # string would keep the old name after a rename, which is the one thing
        # a single generative source is supposed to prevent.
        for diagram in projected_diagrams(graph()):
            assert diagram.source is None

    def test_the_class_diagram_covers_what_it_shows(self) -> None:
        diagram = class_diagram(graph())
        # Entities and services, so R-1, R-2 and R-3, and never the constraint's
        # R-9, which is not on this diagram.
        assert diagram.traces == ["R-1", "R-2", "R-3"]
        assert "R-9" not in diagram.traces

    def test_the_er_diagram_covers_only_the_entities(self) -> None:
        diagram = er_diagram(graph())
        assert diagram.traces == ["R-1", "R-3"]
        # The service's own requirement is not an entity relationship.
        assert "R-2" not in diagram.traces

    def test_traces_read_in_requirement_order_not_node_order(self) -> None:
        # Two runs over the same graph produce the same list, so a diff between
        # versions shows what changed rather than what moved.
        shuffled = graph()
        shuffled.nodes = list(reversed(shuffled.nodes))
        assert class_diagram(shuffled).traces == class_diagram(graph()).traces

    def test_a_sequence_record_points_at_its_use_case(self) -> None:
        diagram = sequence_diagram(graph(), "uc-pay", ["R-3", "R-1"])
        assert diagram.use_case_id == "uc-pay"
        assert diagram.traces == ["R-1", "R-3"]
        assert diagram.source is None

    def test_needs_no_model_at_all(self) -> None:
        # The entities and their owners are already in the graph. Asking a model
        # to restate them is asking it to get them wrong.
        assert len(projected_diagrams(graph())) == 2


class TestTheParticipantChecks:
    def test_a_step_with_a_blank_end_is_caught_before_construction(self) -> None:
        # Found by a live run, not by reading the code. The check for unknown
        # participants skips empty strings, so a blank used to sail through
        # validation and raise a ValidationError while the use case was being
        # built: a stack trace where a retry belonged.
        interaction = DraftInteraction(
            name="Paying",
            steps=[
                DraftStep(from_id="a1", to_id="m1", message="pay", kind="call"),
                DraftStep(from_id="", to_id="m1", message="check", kind="call"),
                DraftStep(from_id="m1", to_id="   ", message="save", kind="call"),
            ],
        )
        assert blank_participants(interaction) == [2, 3]
        # And it is not silently folded into the unknown-participant message.
        assert "" not in unknown_participants(interaction, {"a1", "m1"})

    def test_a_full_interaction_reports_no_blanks(self) -> None:
        whole = DraftInteraction(
            name="Paying",
            steps=[
                DraftStep(from_id="a1", to_id="m1", message="pay", kind="call"),
                DraftStep(from_id="m1", to_id="a1", message="done", kind="return"),
            ],
        )
        assert blank_participants(whole) == []

    def test_catches_a_participant_the_graph_does_not_have(self) -> None:
        interaction = DraftInteraction(
            name="Pay",
            steps=[DraftStep(from_id="a1", to_id="zz9", message="asks", kind="call")],
        )
        assert unknown_participants(interaction, {"a1", "e1"}) == ["zz9"]

    def test_catches_a_token_that_names_nothing(self) -> None:
        # An unresolved token is worse than a wrong name: it renders as literal
        # braces in the middle of a sentence.
        interaction = DraftInteraction(
            name="An interaction",
            steps=[DraftStep(from_id="a1", to_id="e1", message="creates a {e9}", kind="call")],
        )
        assert unresolved_tokens(interaction, {"a1", "e1"}) == ["e9"]

    def test_accepts_a_token_that_resolves(self) -> None:
        interaction = DraftInteraction(
            name="An interaction",
            steps=[DraftStep(from_id="a1", to_id="e1", message="creates a {e1}", kind="call")],
        )
        assert unresolved_tokens(interaction, {"a1", "e1"}) == []

    def test_catches_a_name_typed_in_instead_of_a_token(self) -> None:
        # The failure that looks harmless: correct today, stale the moment
        # somebody renames the node, because this copy was never connected to it.
        interaction = DraftInteraction(
            name="An interaction",
            steps=[
                DraftStep(from_id="a1", to_id="m1", message="asks the Payment Service", kind="call")
            ],
        )
        assert names_typed_instead_of_ids(interaction, graph()) == ["Payment Service"]

    def test_a_token_is_not_mistaken_for_a_typed_name(self) -> None:
        interaction = DraftInteraction(
            name="An interaction",
            steps=[DraftStep(from_id="a1", to_id="m1", message="asks the {m1}", kind="call")],
        )
        assert names_typed_instead_of_ids(interaction, graph()) == []


def agent_returning(payload: dict, *, then: dict | None = None):
    calls: list[int] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(1)
        body = payload if (len(calls) == 1 or then is None) else then
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(body))])

    return build_sequence_agent(FunctionModel(respond)), calls


GOOD = {
    "name": "Pay with a saved card",
    "steps": [
        {"from_id": "a1", "to_id": "m1", "message": "confirms a payment", "kind": "call"},
        {"from_id": "m1", "to_id": "e1", "message": "records the {e1}", "kind": "call"},
        {"from_id": "m1", "to_id": "a2", "message": "charges the card", "kind": "call"},
        {"from_id": "a2", "to_id": "m1", "message": "settled", "kind": "return"},
        {"from_id": "m1", "to_id": "a1", "message": "confirmed", "kind": "return"},
    ],
}


class TestWritingAnInteraction:
    async def test_a_clean_interaction_becomes_a_use_case(self) -> None:
        agent, calls = agent_returning(GOOD)
        use_case, report = await write_interaction(
            graph(),
            "paying with a saved card",
            agent=agent,
            use_case_id="uc-pay",
            traces=["R-1", "R-2"],
            story_id="US-101",
        )

        assert len(calls) == 1
        assert use_case.id == "uc-pay"
        assert use_case.story_id == "US-101"
        assert len(use_case.steps) == 5
        assert report.unknown_participants == ()
        assert report.unresolved_tokens == ()

    async def test_every_participant_is_a_node_that_exists(self) -> None:
        agent, _ = agent_returning(GOOD)
        use_case, _ = await write_interaction(
            graph(), "paying", agent=agent, use_case_id="uc-pay", traces=["R-1"]
        )
        known = {node.id for node in graph().nodes}
        for step in use_case.steps:
            assert step.from_id in known
            assert step.to_id in known

    async def test_an_invented_participant_is_sent_back_with_the_real_ids(self) -> None:
        bad = {
            "name": "Pay",
            "steps": [{"from_id": "a1", "to_id": "ledger9", "message": "posts", "kind": "call"}],
        }
        agent, calls = agent_returning(bad, then=GOOD)
        use_case, report = await write_interaction(
            graph(), "paying", agent=agent, use_case_id="uc-pay", traces=["R-1"]
        )

        assert len(calls) == 2, "it should have asked again"
        assert report.unknown_participants == ()
        assert all(step.to_id != "ledger9" for step in use_case.steps)

    async def test_a_typed_name_is_corrected_rather_than_sent_back(self) -> None:
        # Replacing the exact label with its token is mechanical and loses
        # nothing, so it is done here rather than spent as a retry. Refusing it
        # instead cost two retries and then the whole run when a real model wrote
        # "Payment" for a node called Payment.
        typed = {
            "name": "Pay",
            "steps": [
                {
                    "from_id": "a1",
                    "to_id": "m1",
                    "message": "asks the Payment Service",
                    "kind": "call",
                }
            ],
        }
        agent, calls = agent_returning(typed)
        use_case, report = await write_interaction(
            graph(), "paying", agent=agent, use_case_id="uc-pay", traces=["R-1"]
        )

        assert len(calls) == 1, "a fixable problem must not cost a retry"
        assert use_case.steps[0].message == "asks the {m1}"
        # Counted, because how often the model ignores the instruction is worth
        # knowing even when it costs nothing.
        assert report.names_tokenised == ("Payment Service",)

    async def test_the_correction_survives_a_rename_where_the_typed_name_would_not(self) -> None:
        typed = {
            "name": "Pay",
            "steps": [
                {
                    "from_id": "a1",
                    "to_id": "m1",
                    "message": "asks the Payment Service",
                    "kind": "call",
                }
            ],
        }
        agent, _ = agent_returning(typed)
        use_case, _ = await write_interaction(
            graph(), "paying", agent=agent, use_case_id="uc-pay", traces=["R-1"]
        )

        renamed = {node.id: node.label for node in graph().nodes}
        renamed["m1"] = "Settlement Service"
        rendered = use_case.steps[0].message.replace("{m1}", renamed["m1"])
        assert rendered == "asks the Settlement Service"

    async def test_the_longest_name_is_replaced_as_one_thing(self) -> None:
        # "Payment" is a prefix of "Payment Service", and swapping the first word
        # out from under the longer name would produce "{e1} Service".
        typed = {
            "name": "Pay",
            "steps": [
                {
                    "from_id": "a1",
                    "to_id": "m1",
                    "message": "the Payment Service records it",
                    "kind": "call",
                }
            ],
        }
        agent, _ = agent_returning(typed)
        use_case, _ = await write_interaction(
            graph(), "paying", agent=agent, use_case_id="uc-pay", traces=["R-1"]
        )
        assert use_case.steps[0].message == "the {m1} records it"

    async def test_an_empty_interaction_is_refused(self) -> None:
        agent, calls = agent_returning({"name": "Nothing", "steps": []}, then=GOOD)
        use_case, _ = await write_interaction(
            graph(), "paying", agent=agent, use_case_id="uc-pay", traces=["R-1"]
        )
        assert len(calls) == 2
        assert use_case.steps

    async def test_an_unknown_step_kind_becomes_a_call_rather_than_breaking(self) -> None:
        odd = {
            "name": "Pay",
            "steps": [{"from_id": "a1", "to_id": "m1", "message": "asks", "kind": "shout"}],
        }
        agent, _ = agent_returning(odd)
        use_case, _ = await write_interaction(
            graph(), "paying", agent=agent, use_case_id="uc-pay", traces=["R-1"]
        )
        assert use_case.steps[0].kind == "call"

    def test_the_prompt_gives_ids_and_leaves_the_rules_out_of_the_graph(self) -> None:
        prompt = prompt_for(graph(), "paying with a saved card")
        assert "a1: Customer" in prompt
        assert "m1: Payment Service" in prompt
        # A constraint is not a participant in an interaction.
        assert "c1: PCI" not in prompt


class TestRenamingReachesTheDiagram:
    async def test_a_renamed_node_changes_what_the_interaction_says(self) -> None:
        # The whole reason participants are ids and names are tokens.
        agent, _ = agent_returning(GOOD)
        use_case, _ = await write_interaction(
            graph(), "paying", agent=agent, use_case_id="uc-pay", traces=["R-1"]
        )

        renamed = graph()
        for node in renamed.nodes:
            if node.id == "e1":
                node.label = "Settlement"

        # The frontend resolves {e1} against the graph, so the same steps read
        # differently once the node is renamed, with nothing regenerated.
        by_id = {node.id: node.label for node in renamed.nodes}
        rendered = [step.message.replace("{e1}", by_id["e1"]) for step in use_case.steps]
        assert any("Settlement" in line for line in rendered)
        assert not any("Payment" in line for line in rendered if "Settlement" not in line)


@pytest.mark.live
@pytest.mark.filterwarnings("ignore::ResourceWarning")
@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
class TestAgainstARealProvider:
    async def test_writes_an_interaction_using_only_real_participants(
        self, allow_live_requests: None, live_model_name: str, live
    ) -> None:
        use_case, report = await write_interaction(
            graph(),
            "a customer paying with a saved card",
            agent=await live(build_sequence_agent(live_model_name)),
            use_case_id="uc-pay",
            traces=["R-1", "R-2"],
        )

        assert use_case.steps, "the model wrote no steps"
        known = {node.id for node in graph().nodes}
        for step in use_case.steps:
            assert step.from_id in known, f"invented participant {step.from_id}"
            assert step.to_id in known, f"invented participant {step.to_id}"
        assert report.unresolved_tokens == ()

        print(f"\nsteps={report.steps_returned}")
        for step in use_case.steps:
            print(f"  {step.from_id} -> {step.to_id} [{step.kind}] {step.message}")
