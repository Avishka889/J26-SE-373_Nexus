"""The repair loop, and the thing it would be worthless without.

A loop that re-sends the same prompt and hopes for a better answer is a retry, not
a repair. The claim this component makes is that the rules teach the model what to
fix, so the test that matters is not "did it try again" but "did the second prompt
carry the violations, naming the node and the rule".

`FunctionModel` is what makes that checkable: it hands back whatever we choose and
records what it was asked, so a test can return a broken graph first, a good one
second, and then read the prompts the model actually received.
"""

import json

import pytest
from c1.sag.extractor import (
    CouldNotBuildGraph,
    build_graph_agent,
    extract_graph,
    prompt_for,
    repair_prompt,
)
from c1.sag.rules import validate_sag
from c1.sag.schema import DraftGraph
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sdlc_contracts import ParsedRequirement

REQUIREMENTS = [
    ParsedRequirement(
        id="R-1",
        text="A customer makes a payment.",
        type="functional",
        priority="must",
        confidence=90,
    ),
    ParsedRequirement(
        id="R-2",
        text="A payment service records every payment.",
        type="functional",
        priority="must",
        confidence=88,
    ),
]
TEXT = "A customer makes a payment. A payment service records every payment."


def good_graph() -> dict:
    return {
        "nodes": [
            {
                "id": "a1",
                "kind": "actor",
                "label": "Customer",
                "traces": ["R-1"],
                "actor_kind": "primary",
                "attributes": [],
                "applies_to": [],
                "standard": "",
                "description": "",
            },
            {
                "id": "e1",
                "kind": "entity",
                "label": "Payment",
                "traces": ["R-1"],
                "attributes": [{"name": "id", "type": "UUID"}],
                "actor_kind": "",
                "applies_to": [],
                "standard": "",
                "description": "",
            },
            {
                "id": "m1",
                "kind": "service",
                "label": "Payment Service",
                "traces": ["R-2"],
                "attributes": [],
                "actor_kind": "",
                "applies_to": [],
                "standard": "",
                "description": "",
            },
        ],
        "edges": [
            {
                "id": "x1",
                "source": "a1",
                "target": "e1",
                "kind": "action",
                "verb": "makes",
                "traces": ["R-1"],
            },
            {
                "id": "x2",
                "source": "m1",
                "target": "e1",
                "kind": "data",
                "verb": "owns",
                "traces": ["R-2"],
            },
        ],
    }


def broken_graph() -> dict:
    """Two rules broken, and both of them the kind a hint can actually fix."""
    graph = good_graph()
    # An actor that is really a screen.
    graph["nodes"][0]["label"] = "Login Page"
    # And an entity that says nothing about what it holds.
    graph["nodes"][1]["attributes"] = []
    return graph


class Recorder:
    """Scripted graphs, and a record of what the model was asked each time.

    `FunctionModel` wants a plain function rather than a callable object, so the
    recording lives here and `as_function` closes over it.
    """

    def __init__(self, *graphs: dict) -> None:
        self.graphs = list(graphs)
        self.prompts: list[str] = []

    def as_function(self):
        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            self.prompts.append(_last_user_text(messages))
            graph = self.graphs[min(len(self.prompts) - 1, len(self.graphs) - 1)]
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(graph))])

        return respond


def _last_user_text(messages: list[ModelMessage]) -> str:
    """The prompt this attempt was sent, which is what the test is here to read."""
    for message in reversed(messages):
        for part in getattr(message, "parts", []):
            content = getattr(part, "content", None)
            if isinstance(content, str) and content.strip():
                return content
    return ""


def agent_for(recorder: Recorder):
    return build_graph_agent(FunctionModel(recorder.as_function()))


class TestTheHintsActuallyTravel:
    async def test_the_second_prompt_names_the_rules_the_first_answer_broke(self) -> None:
        recorder = Recorder(broken_graph(), good_graph())
        await extract_graph(REQUIREMENTS, agent=agent_for(recorder), requirements_text=TEXT)

        assert len(recorder.prompts) == 2, "it should have asked exactly twice"
        first, second = recorder.prompts

        # The whole claim: the second ask is different, and different in the way
        # that matters.
        assert first != second
        assert "Login Page" in second, "the hint did not name the offending node"
        assert "e1" in second, "the hint did not name the entity with no attributes"
        assert "screen" in second.lower()
        assert "attributes" in second.lower()

        # And nothing about the failure leaked into the first ask.
        assert "Login Page" not in first
        assert "broke these rules" not in first

    async def test_a_repaired_graph_is_the_one_returned(self) -> None:
        recorder = Recorder(broken_graph(), good_graph())
        graph, report = await extract_graph(
            REQUIREMENTS, agent=agent_for(recorder), requirements_text=TEXT
        )

        assert report.attempts == 2
        assert report.repaired is True
        assert report.errors_per_attempt[0] == ("actor-is-not-a-screen", "entity-has-attributes")
        assert report.errors_per_attempt[1] == ()

        # The graph handed back is the fixed one, not the first attempt.
        customer = next(node for node in graph.nodes if node.id == "a1")
        assert customer.label == "Customer"

    async def test_the_hints_name_ids_and_actions_not_reader_prose(self) -> None:
        # The reader-facing reason and the model-facing hint are different jobs.
        # Sending the reason would be polite and useless.
        draft = DraftGraph.model_validate(broken_graph())
        report = validate_sag(
            draft, requirement_ids=frozenset({"R-1", "R-2"}), requirements_text=TEXT
        )
        hints = report.hints()

        assert "a1" in hints or "Login Page" in hints
        assert "e1" in hints
        for finding in report.errors:
            assert finding.hint != finding.reason


class TestTheLoopIsBounded:
    async def test_a_clean_graph_is_asked_for_once(self) -> None:
        recorder = Recorder(good_graph())
        _, report = await extract_graph(
            REQUIREMENTS, agent=agent_for(recorder), requirements_text=TEXT
        )

        assert len(recorder.prompts) == 1
        assert report.attempts == 1
        assert report.clean_first_time is True
        assert report.repaired is False

    async def test_a_model_that_never_fixes_it_stops_after_two(self) -> None:
        # An unbounded loop against a model that cannot satisfy a rule is an
        # expensive way to fail.
        recorder = Recorder(broken_graph(), broken_graph(), good_graph())
        with pytest.raises(CouldNotBuildGraph) as caught:
            await extract_graph(REQUIREMENTS, agent=agent_for(recorder), requirements_text=TEXT)

        assert len(recorder.prompts) == 2, "it must not keep asking"
        assert caught.value.attempts == 2

    async def test_the_failure_carries_reasons_a_reader_can_read(self) -> None:
        recorder = Recorder(broken_graph(), broken_graph())
        with pytest.raises(CouldNotBuildGraph) as caught:
            await extract_graph(REQUIREMENTS, agent=agent_for(recorder), requirements_text=TEXT)

        # The stage fails with sentences, not a stack trace, because the contract
        # has a place for a plain-words error and this is what fills it.
        message = str(caught.value)
        assert "screen" in message or "holds" in message
        assert "Traceback" not in message
        for finding in caught.value.report.errors:
            assert finding.reason.endswith(".")

    async def test_nothing_broken_is_promoted_and_nothing_is_quietly_deleted(self) -> None:
        # The tempting alternative is to drop the offending nodes and hand back
        # what is left. That produces a design nobody asked for and calls it
        # generated, so failing is the honest outcome.
        recorder = Recorder(broken_graph(), broken_graph())
        with pytest.raises(CouldNotBuildGraph) as caught:
            await extract_graph(REQUIREMENTS, agent=agent_for(recorder), requirements_text=TEXT)

        # Both offending nodes are still named in the failure, so nothing was
        # silently removed to make the graph pass.
        subjects = {finding.subject for finding in caught.value.report.errors}
        assert {"a1", "e1"} <= subjects


class TestWhatTravelsWithASuccessfulGraph:
    async def test_warnings_reach_the_reader_rather_than_blocking_the_run(self) -> None:
        graph_with_gap = good_graph()
        # Nothing covers R-2 any more, which is a warning, not an error.
        graph_with_gap["nodes"][2]["traces"] = ["R-1"]
        graph_with_gap["edges"][1]["traces"] = ["R-1"]

        recorder = Recorder(graph_with_gap)
        _, report = await extract_graph(
            REQUIREMENTS, agent=agent_for(recorder), requirements_text=TEXT
        )

        assert report.attempts == 1
        assert any(w.rule_id == "requirement-coverage" for w in report.warnings)
        assert (
            "R-2" in next(w for w in report.warnings if w.rule_id == "requirement-coverage").reason
        )

    async def test_the_graph_comes_back_laid_out(self) -> None:
        # Positions are computed from the graph, never asked of the model: a
        # model's guesses differ between two runs over identical requirements,
        # and a canvas that rearranges itself makes the impact highlight noise.
        recorder = Recorder(good_graph())
        graph, _ = await extract_graph(
            REQUIREMENTS, agent=agent_for(recorder), requirements_text=TEXT
        )

        from c1.sag.layout import COLUMN_X

        for node in graph.nodes:
            assert node.position.x == COLUMN_X[node.kind]
        # And no two nodes share a spot.
        spots = {(node.position.x, node.position.y) for node in graph.nodes}
        assert len(spots) == len(graph.nodes)

    async def test_the_same_requirements_lay_out_the_same_way_twice(self) -> None:
        first, _ = await extract_graph(
            REQUIREMENTS, agent=agent_for(Recorder(good_graph())), requirements_text=TEXT
        )
        # The same nodes, listed in a different order, as a second run would.
        shuffled = good_graph()
        shuffled["nodes"] = list(reversed(shuffled["nodes"]))
        second, _ = await extract_graph(
            REQUIREMENTS, agent=agent_for(Recorder(shuffled)), requirements_text=TEXT
        )

        def places(graph):
            return {node.id: (node.position.x, node.position.y) for node in graph.nodes}

        assert places(first) == places(second)

    async def test_a_node_the_rules_could_not_confirm_carries_its_finding(self) -> None:
        odd = good_graph()
        odd["nodes"][2]["label"] = "Kubernetes Sidecar Reconciler"

        recorder = Recorder(odd)
        graph, _ = await extract_graph(
            REQUIREMENTS, agent=agent_for(recorder), requirements_text=TEXT
        )

        service = next(node for node in graph.nodes if node.id == "m1")
        assert service.unconfirmed is not None
        assert service.unconfirmed.rule_id == "label-is-grounded"
        assert service.unconfirmed.traces == ["R-2"]


class TestThePrompts:
    def test_the_first_prompt_carries_the_requirements_and_their_ids(self) -> None:
        prompt = prompt_for(REQUIREMENTS)
        assert "R-1" in prompt and "R-2" in prompt
        assert "A customer makes a payment." in prompt

    def test_the_repair_prompt_keeps_the_request_and_adds_the_failures(self) -> None:
        draft = DraftGraph.model_validate(broken_graph())
        report = validate_sag(draft, requirement_ids=frozenset({"R-1", "R-2"}))
        second = repair_prompt(prompt_for(REQUIREMENTS), report)

        # Still the same job, with the corrections appended rather than replacing.
        assert "R-1" in second
        assert "Fix each one" in second
        assert second.count("- ") >= 2


@pytest.mark.live
# The provider closes its sockets after the loop ends, and this workspace runs
# warnings as errors. Scoped here so warnings stay fatal everywhere else.
@pytest.mark.filterwarnings("ignore::ResourceWarning")
@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
class TestAgainstARealProvider:
    """Whether a real model builds a graph the rules accept, and repairs one.

    The mocked tests prove the loop carries hints. This proves a model does
    something useful with them, which no amount of FunctionModel can show.
    """

    async def test_builds_a_graph_the_fifteen_rules_accept(
        self, allow_live_requests: None, live_model_name: str
    ) -> None:
        from c1.sag.extractor import build_graph_agent as build

        graph, report = await extract_graph(
            REQUIREMENTS, agent=build(live_model_name), requirements_text=TEXT
        )

        assert graph.nodes, "the model returned an empty graph"
        # Reaching here at all means every error rule passed, since a draft with
        # errors is never promoted.
        assert report.attempts <= 2
        assert all(node.traces for node in graph.nodes)

        # Recorded rather than asserted: how often the first attempt is clean is
        # a number about the model.
        print(
            f"\nattempts={report.attempts} repaired={report.repaired} "
            f"errors_per_attempt={report.errors_per_attempt}"
        )
