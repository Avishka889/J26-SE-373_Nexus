"""The stack stage: arithmetic scores, honest availability, guarded prose."""

import pytest
from c2.stack import (
    CATALOG,
    StackFacts,
    build_stack_explainer,
    check_no_invented_figures,
    gather_stack_facts,
    score_stacks,
)
from pydantic_ai.models.test import TestModel
from sdlc_contracts import (
    ArchitectureGraph,
    ArchitectureRecommendation,
    ArchitectureStyleNote,
    GraphEdge,
    GraphNode,
    TopologyCandidate,
)


def _node(id: str, kind: str, label: str, **extra) -> GraphNode:
    return GraphNode(
        id=id, kind=kind, label=label, traces=["R-1"], position={"x": 0, "y": 0}, **extra
    )


def _graph_with_cross_writes() -> ArchitectureGraph:
    return ArchitectureGraph(
        nodes=[
            _node("s1", "service", "Order Service"),
            _node("s2", "service", "Billing Service"),
            _node("e1", "entity", "Order", attributes=[]),
            _node("e2", "entity", "Invoice", attributes=[]),
            _node("c1", "constraint", "PCI DSS", standard="PCI DSS", applies_to=["e1"]),
        ],
        edges=[
            GraphEdge(
                id="d1", source="s1", target="e1", kind="data", verb="writes", traces=["R-1"]
            ),
            GraphEdge(
                id="d2", source="s2", target="e1", kind="data", verb="writes", traces=["R-1"]
            ),
        ],
    )


def _recommendation(selected: str | None = "topo-modular") -> ArchitectureRecommendation:
    return ArchitectureRecommendation(
        candidates=[
            TopologyCandidate(
                id="topo-mono",
                name="Monolith",
                score=80,
                rationale="one deploy",
                pros=["one deploy"],
                cons=["a", "b"],
            ),
            TopologyCandidate(
                id="topo-modular",
                name="Modular Monolith",
                score=85,
                rationale="seams without services",
                pros=["seams"],
                cons=["a", "b"],
            ),
        ],
        recommended_candidate_id="topo-modular",
        selected_candidate_id=selected,
        style=ArchitectureStyleNote(id="layered", name="Layered", note="fits"),
    )


class TestTheFacts:
    def test_counting_is_from_the_graph_alone(self) -> None:
        facts = gather_stack_facts(_graph_with_cross_writes(), _recommendation())
        assert facts.n_services == 2
        assert facts.n_entities == 2
        assert facts.cross_service_writes == 1
        assert facts.n_standards == 1
        assert facts.selected_topology == "Modular Monolith"


class TestTheScoring:
    def test_a_compliance_heavy_design_leans_spring(self) -> None:
        facts = gather_stack_facts(_graph_with_cross_writes(), _recommendation())
        artefact = score_stacks(facts)
        by_id = {c.id: c for c in artefact.candidates}
        assert by_id["react-spring-postgres"].score > by_id["mern"].score
        assert artefact.recommended_id == "react-spring-postgres"

    def test_a_tiny_design_leans_mern(self) -> None:
        facts = StackFacts(n_entities=2, n_services=1)
        artefact = score_stacks(facts)
        assert artefact.recommended_id == "mern"

    def test_the_selection_defaults_to_the_top_available_candidate(self) -> None:
        # The arithmetic winner here is the Spring stack, whose generators do
        # not exist. Recommending it is honest; selecting it would promise a
        # build nobody can generate, so the default selection is mern.
        facts = gather_stack_facts(_graph_with_cross_writes(), _recommendation())
        artefact = score_stacks(facts)
        assert artefact.recommended_id == "react-spring-postgres"
        assert artefact.selected_id == "mern"
        assert artefact.selected_by == "system default"

    def test_the_scores_are_a_comparison_not_a_rubber_stamp(self) -> None:
        # On both corpus shapes the loser stays within 30 points: a function
        # that always produces one obvious winner is not a recommendation.
        for facts in (
            gather_stack_facts(_graph_with_cross_writes(), _recommendation()),
            StackFacts(n_entities=2, n_services=1),
        ):
            scores = sorted((c.score for c in score_stacks(facts).candidates), reverse=True)
            assert scores[0] - scores[1] <= 30

    def test_every_point_names_its_fact(self) -> None:
        artefact = score_stacks(gather_stack_facts(_graph_with_cross_writes(), _recommendation()))
        for candidate in artefact.candidates:
            assert sum(part.points for part in candidate.score_breakdown) == candidate.score

    def test_the_catalog_is_honest_about_availability(self) -> None:
        available = {entry.id: entry.available for entry in CATALOG}
        assert available == {"mern": True, "react-spring-postgres": False}


class TestTheFigureGuard:
    FACTS = StackFacts(n_entities=6, n_services=2, cross_service_writes=1)

    def test_counted_facts_may_be_cited(self) -> None:
        assert check_no_invented_figures("6 entities across 2 services", self.FACTS) == []

    def test_grounded_prose_with_an_adjective_still_passes(self) -> None:
        assert check_no_invented_figures("6 distinct entities", self.FACTS) == []

    def test_an_invented_user_count_is_refused(self) -> None:
        invented = check_no_invented_figures("handles 10,000 concurrent users", self.FACTS)
        assert invented and "10000" in invented[0].replace(",", "")

    def test_a_team_size_is_refused_even_when_the_digit_matches(self) -> None:
        # 2 services exist; "2 engineers" is still an invention, because the
        # number never meets one of its own fact words.
        assert check_no_invented_figures("a team of 2 engineers", self.FACTS) != []

    async def test_the_validator_retries_with_the_reason(self) -> None:
        agent = build_stack_explainer(
            TestModel(custom_output_args={"rationale": "supports 10,000 concurrent users"})
        )
        with pytest.raises(Exception) as error, agent.override(model=agent.model):
            await agent.run("explain", deps=self.FACTS)
        assert "10,000" in str(error.value) or "retries" in str(error.value).lower()

    async def test_grounded_prose_survives_the_validator(self) -> None:
        agent = build_stack_explainer(
            TestModel(custom_output_args={"rationale": "6 entities favor a relational schema"})
        )
        result = await agent.run("explain", deps=self.FACTS)
        assert "6 entities" in result.output.rationale
