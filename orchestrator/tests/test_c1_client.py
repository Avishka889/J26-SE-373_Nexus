"""The boundary between the orchestrator and Component 1.

The point of these is that the boundary is real rather than claimed. C1_MODE
appears in the configuration and in compose, and it would be easy for the HTTP
path to be a client with nothing on the other end that nobody had ever run. So
the component's own service is stood up over an ASGI transport, with no server
and no Docker, and the same six stage calls are made through it, plus a seventh
for naming a project: not a stage, so it answers with a bare title rather than
an outcome.

What has to hold is that the design survives the round trip. Every response is
validated back into the contract type on arrival, which is the whole reason the
schema is generated from those models: a service that returns the wrong shape is
caught at the boundary it crossed rather than three stages later when something
reads a field that is not there.
"""

import httpx
import pytest
from c1.app import create_app as create_c1_app
from orchestrator.clients.c1 import HttpC1, StageOutcome, make_c1_client
from orchestrator.clients.canned import CannedC1
from sdlc_contracts import ArchitectureGraph, ParsedRequirement


@pytest.fixture
async def over_http():
    """The component's own service, reachable without a port being opened."""
    component = CannedC1()
    app = create_c1_app(component)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://c1") as http:
            yield HttpC1("http://c1", client=http), component


async def _graph(client) -> ArchitectureGraph:
    requirements = (await client.parse_requirements("Someone creates a record.")).artefact
    return (await client.build_graph(requirements.requirements, text="x")).artefact


class TestTheServiceAnswersEveryStage:
    async def test_requirements_survive_the_round_trip(self, over_http) -> None:
        client, component = over_http
        outcome = await client.parse_requirements("Someone creates a record.")

        assert isinstance(outcome, StageOutcome)
        assert outcome.artefact.requirements[0].text == "Someone creates a record."
        assert outcome.summary
        assert component.calls == ["requirements"]

    async def test_the_graph_survives_the_round_trip(self, over_http) -> None:
        client, _ = over_http
        graph = await _graph(client)
        assert {n.id for n in graph.nodes} == {"a1", "e1", "m1"}
        # Positions are floats on the wire and have to come back as a Position,
        # not a dict, or every reader of the canvas breaks.
        assert graph.nodes[1].position.x == 240

    async def test_the_recommendation_survives_the_round_trip(self, over_http) -> None:
        client, _ = over_http
        graph = await _graph(client)
        outcome = await client.recommend([], graph)
        assert outcome.artefact.recommended_candidate_id == "monolith"
        assert outcome.artefact.selected_candidate_id is None
        assert outcome.notes["margin"] == 41

    async def test_the_uml_survives_the_round_trip(self, over_http) -> None:
        client, _ = over_http
        outcome = await client.write_uml(await _graph(client))
        assert [d.kind for d in outcome.artefact.diagrams] == ["class", "sequence"]
        # The token convention has to make it across as text rather than being
        # resolved or mangled somewhere in the middle.
        assert "{e1}" in outcome.artefact.use_cases[0].steps[0].message

    async def test_the_wireframes_survive_the_round_trip(self, over_http) -> None:
        client, _ = over_http
        outcome = await client.draw_wireframes(
            await _graph(client), requirement_ids=["R-1"], version="v2"
        )
        flow = outcome.artefact.flows[0]
        assert flow.version == "v2", "the request's arguments reached the service"
        assert flow.screens[1].terminal is True
        assert outcome.artefact.coverage == [], "coverage is the read model's job"

    async def test_the_sprint_plan_survives_the_round_trip(self, over_http) -> None:
        client, _ = over_http
        requirements = [
            ParsedRequirement(
                id="R-1",
                text="Someone creates a record.",
                type="functional",
                priority="must",
                confidence=70,
            )
        ]
        outcome = await client.plan_sprint(requirements, await _graph(client))
        assert outcome.artefact.proposed[0].id == "US-1"
        assert outcome.artefact.estimated_points == 3

    async def test_a_title_survives_the_round_trip(self, over_http) -> None:
        """Outside /stages, so it answers with a bare title rather than an outcome."""
        client, component = over_http

        assert await client.name_project("Build a pharmacy dispensing system.") == (
            "Pharmacy Dispensing"
        )
        assert "naming" in component.calls

    async def test_the_service_is_transport_and_nothing_else(self, over_http) -> None:
        # Every call reaches the component rather than being answered by the
        # endpoint. An endpoint that started deciding things would be a second
        # implementation drifting against the first.
        client, component = over_http
        graph = await _graph(client)
        await client.recommend([], graph)
        await client.write_uml(graph)
        await client.draw_wireframes(graph, requirement_ids=["R-1"], version="v1")
        await client.plan_sprint([], graph)

        assert component.calls == [
            "requirements",
            "architecture-graph",
            "architecture-recommendation",
            "uml-diagrams",
            "wireframes",
            "sprint-plan",
        ]


class TestChoosingAClient:
    def test_http_mode_never_imports_the_component(self) -> None:
        # The reason the import is deferred: an orchestrator deployed to call C1
        # over the wire must start without the component's dependencies.
        client = make_c1_client("http", model="unused", base_url="http://c1:8001")
        assert isinstance(client, HttpC1)

    def test_the_default_is_in_process(self) -> None:
        from orchestrator.clients.c1 import InProcessC1

        client = make_c1_client("inprocess", model="test", base_url="")
        assert isinstance(client, InProcessC1)
