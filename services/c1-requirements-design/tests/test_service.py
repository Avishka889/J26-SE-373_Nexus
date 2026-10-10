"""Component 1 as the orchestrator sees it: six calls, six artefacts.

The pieces are all tested on their own elsewhere. What is only testable here is
the surface: that every stage returns something the contract accepts, a sentence
a reader can read, and notes the evaluation can count, and that nothing leaks
between them.

Scripted models throughout, because the point is the wiring rather than the
answers. A live run of the whole thing is step 18's job, where it is checked
against the calculator corpus.
"""

import json

import pytest
from c1.architecture.scoring import ScoringFacts
from c1.architecture.style import MODULAR_ENTITY_THRESHOLD, choose_style
from c1.service import C1, StageResult
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sdlc_contracts import (
    ArchitectureGraph,
    GraphEdge,
    GraphNode,
    ParsedRequirement,
    Position,
    RequirementsArtefact,
    SprintPlan,
    UmlArtefact,
    WireframesArtefact,
)


def node(id: str, kind: str, label: str, traces: list[str], **extra) -> GraphNode:
    return GraphNode(
        id=id, kind=kind, label=label, position=Position(x=0, y=0), traces=traces, **extra
    )


REQUIREMENTS = [
    ParsedRequirement(
        id="R-1",
        text="A customer pays with a saved card.",
        type="functional",
        priority="must",
        confidence=85,
    ),
    ParsedRequirement(
        id="R-2",
        text="Every payment is recorded.",
        type="functional",
        priority="must",
        confidence=80,
    ),
]


def graph() -> ArchitectureGraph:
    return ArchitectureGraph(
        nodes=[
            node("a1", "actor", "Customer", ["R-1"], actorKind="primary"),
            node(
                "e1",
                "entity",
                "Payment",
                ["R-1", "R-2"],
                attributes=[{"name": "amount", "type": "number"}],
            ),
            node("m1", "service", "Payment Service", ["R-2"]),
        ],
        edges=[
            GraphEdge(
                id="x1", source="a1", target="e1", kind="action", verb="makes", traces=["R-1"]
            ),
            GraphEdge(id="x2", source="m1", target="e1", kind="data", verb="owns", traces=["R-2"]),
        ],
    )


def scripted(payload: dict) -> FunctionModel:
    """A model that always answers the same thing."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(payload))])

    return FunctionModel(respond)


def c1_answering(payload: dict) -> C1:
    """A component whose every agent returns the one payload it is given.

    Crude and correct for this file: each test drives one stage, so only that
    stage's agent is ever called.
    """
    component = C1.__new__(C1)
    component.model = "scripted"
    model = scripted(payload)
    from c1.architecture.explain import build_explainer
    from c1.llm.extractor import build_agent
    from c1.sag.extractor import build_graph_agent
    from c1.sprint.extractor import build_sprint_agent
    from c1.uml.sequence import build_sequence_agent
    from c1.wireframes.extractor import build_wireframe_agent

    component._requirements = build_agent(model)
    component._graph = build_graph_agent(model)
    component._explainer = build_explainer(model)
    component._sequence = build_sequence_agent(model)
    component._wireframes = build_wireframe_agent(model)
    component._sprint = build_sprint_agent(model)
    return component


class TestParsingRequirements:
    async def test_it_returns_the_artefact_a_summary_and_notes(self) -> None:
        component = c1_answering(
            {
                "requirements": [
                    {
                        "text": "A customer pays with a saved card.",
                        "source_start": 0,
                        "source_end": 34,
                        "source_quote": "A customer pays with a saved card.",
                        "rationale_kind": "read",
                    }
                ],
                # Optional, and sent anyway so the fixture says what the model
                # returned rather than leaning on a default.
                "gaps": [],
            }
        )
        result = await component.parse_requirements("A customer pays with a saved card.")

        assert isinstance(result, StageResult)
        RequirementsArtefact.model_validate(result.artefact.model_dump(by_alias=True))
        assert result.artefact.requirements
        assert "requirement" in result.summary
        # The evaluation reads these, so they have to be present rather than
        # quietly defaulted away.
        assert set(result.notes) == {
            "returned",
            "over_budget",
            "spans_refused",
            "self_declared_inferred",
            # Whether the questions asked were about this brief.
            "gaps_returned",
            "gaps_recovered",
            "gaps_refused",
            # What answered, read from the response rather than the configuration.
            "model_use",
        }
        assert result.notes["model_use"]["answered_by"] == ["function:respond:"]
        assert result.notes["model_use"]["requests"] == 1


class TestBuildingTheGraph:
    async def test_it_returns_a_graph_the_contract_accepts(self) -> None:
        component = c1_answering(
            {
                "nodes": [
                    {
                        "id": "a1",
                        "kind": "actor",
                        "label": "Customer",
                        "traces": ["R-1"],
                        "actor_kind": "primary",
                    },
                    {
                        "id": "e1",
                        "kind": "entity",
                        "label": "Payment",
                        "traces": ["R-1", "R-2"],
                        "attributes": [{"name": "amount", "type": "number"}],
                    },
                    {"id": "m1", "kind": "service", "label": "Payment Service", "traces": ["R-2"]},
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
        )
        result = await component.build_graph(REQUIREMENTS, text="A customer pays. It is recorded.")

        ArchitectureGraph.model_validate(result.artefact.model_dump(by_alias=True))
        assert {n.id for n in result.artefact.nodes} == {"a1", "e1", "m1"}
        assert result.notes["attempts"] == 1
        assert result.notes["repaired"] is False
        # Positions are computed, never asked of the model, so the canvas does
        # not rearrange itself between two runs over the same requirements.
        assert all(n.position is not None for n in result.artefact.nodes)


class TestRecommending:
    async def test_the_model_writes_prose_and_never_a_score(self) -> None:
        component = c1_answering(
            {
                "rationale": "It suits this design because the services are few.",
                "pros": ["One thing to deploy"],
                "cons": ["Scales as one piece", "One failure takes everything"],
            }
        )
        result = await component.recommend(REQUIREMENTS, graph())

        assert len(result.artefact.candidates) >= 2
        # The scores came from arithmetic. If the model could set one, every
        # candidate here would carry the same number the payload implies.
        assert len({c.score for c in result.artefact.candidates}) > 1
        assert result.artefact.selected_candidate_id is None, "nobody has chosen yet"
        assert result.notes["margin"] >= 0
        assert result.artefact.style.id in {"clean", "modular", "layered"}


class TestWritingUml:
    async def test_it_projects_two_diagrams_and_writes_one_interaction(self) -> None:
        component = c1_answering(
            {
                "name": "Paying",
                "steps": [
                    {"from_id": "a1", "to_id": "m1", "message": "pay for {e1}", "kind": "call"},
                    {"from_id": "m1", "to_id": "a1", "message": "done", "kind": "return"},
                ],
            }
        )
        result = await component.write_uml(graph())

        UmlArtefact.model_validate(result.artefact.model_dump(by_alias=True))
        kinds = [d.kind for d in result.artefact.diagrams]
        assert kinds.count("class") == 1 and kinds.count("er") == 1
        assert len(result.artefact.use_cases) == 1

    async def test_diagram_ids_stay_unique_when_more_interactions_are_written(self) -> None:
        # The sequence diagram id used to be the literal "sequence", so a second
        # interaction produced a second diagram with the same id and nothing
        # validated it.
        from c1.uml.projections import sequence_diagram

        first = sequence_diagram(graph(), "uc1", ["R-1"])
        second = sequence_diagram(graph(), "uc2", ["R-2"])
        assert first.id != second.id

    async def test_the_projected_diagrams_carry_no_frozen_source(self) -> None:
        component = c1_answering(
            {
                "name": "Paying",
                "steps": [
                    {"from_id": "a1", "to_id": "m1", "message": "pay", "kind": "call"},
                ],
            }
        )
        result = await component.write_uml(graph())
        # Null on purpose: the picture is drawn from the graph when it is shown,
        # so a rename reaches it. Frozen text would keep the old name.
        assert all(d.source is None for d in result.artefact.diagrams)


class TestDrawingWireframes:
    async def test_coverage_is_left_for_the_read_model(self) -> None:
        component = c1_answering(
            {
                "name": "Paying",
                "screens": [
                    {
                        "id": "s1",
                        "name": "Your Basket",
                        "traces": ["R-1"],
                        "blocks": [{"id": "b1", "kind": "summary", "label": "Total"}],
                        "links": [
                            {"id": "l1", "label": "Pay", "target_id": "s2", "variant": "primary"}
                        ],
                    },
                    {
                        "id": "s2",
                        "name": "Payment Confirmed",
                        "traces": ["R-2"],
                        "blocks": [{"id": "b2", "kind": "banner", "label": "Paid"}],
                        "links": [],
                    },
                ],
            }
        )
        result = await component.draw_wireframes(
            graph(), requirement_ids=["R-1", "R-2"], version="v1"
        )

        WireframesArtefact.model_validate(result.artefact.model_dump(by_alias=True))
        assert result.artefact.flows
        # Both derived by the read model against the sprint plan, which does not
        # exist at this point in the run.
        assert result.artefact.coverage == []
        assert all(flow.covers_story_ids == [] for flow in result.artefact.flows)
        # And the ending was marked by rule rather than claimed by the model.
        assert result.artefact.flows[0].screens[1].terminal is True


class TestPlanningTheSprint:
    async def test_every_number_comes_from_arithmetic(self) -> None:
        component = c1_answering(
            {
                "goal": "A customer can pay.",
                "stories": [
                    {
                        "title": "As a customer, I can pay with a saved card",
                        "epic": "Payments",
                        "traces": ["R-1", "R-2"],
                        "acceptance": [
                            {
                                "given": "a saved card",
                                "when": "they pay",
                                "then": "the payment is recorded",
                            }
                        ],
                    }
                ],
            }
        )
        result = await component.plan_sprint(REQUIREMENTS, graph())

        SprintPlan.model_validate(result.artefact.model_dump(by_alias=True))
        story = result.artefact.proposed[0]
        assert story.id == "US-1", "ids are allocated, not asked for"
        assert story.priority == "must", "inherited from the requirements it traces"
        assert story.points in {1, 2, 3, 5, 8, 13, 21}
        assert result.artefact.estimated_points == sum(s.points for s in result.artefact.proposed)
        assert "not measured" in result.artefact.velocity_assumption.basis


class TestChoosingAStyle:
    def test_something_outside_the_design_chooses_clean(self) -> None:
        chosen = choose_style(ScoringFacts(n_entities=2, n_services=1, n_external=1))
        assert chosen.id == "clean"
        assert "1 external system" in chosen.note

    def test_a_rule_to_satisfy_also_chooses_clean(self) -> None:
        chosen = choose_style(ScoringFacts(n_entities=2, n_services=1, compliance_signal=True))
        assert chosen.id == "clean"

    def test_a_large_design_with_several_services_chooses_modular(self) -> None:
        chosen = choose_style(ScoringFacts(n_entities=MODULAR_ENTITY_THRESHOLD, n_services=2))
        assert chosen.id == "modular"

    def test_a_small_self_contained_design_chooses_layered(self) -> None:
        # The calculator shape. Layered is the honest answer for it, not a
        # consolation prize.
        chosen = choose_style(ScoringFacts(n_entities=1, n_services=1))
        assert chosen.id == "layered"

    @pytest.mark.parametrize(
        "facts",
        [
            ScoringFacts(n_entities=2, n_services=1, n_external=1),
            ScoringFacts(n_entities=6, n_services=2),
            ScoringFacts(n_entities=1, n_services=1),
        ],
    )
    def test_every_note_says_which_fact_chose_it(self, facts: ScoringFacts) -> None:
        # A style with no stated reason is an opinion in a box. A reader has to
        # be able to disagree with the rule, which means seeing it.
        note = choose_style(facts).note
        assert "Chosen because" in note
        assert any(str(n) in note for n in (facts.n_entities, facts.n_services, facts.n_external))
