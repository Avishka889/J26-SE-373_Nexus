"""The boundary between the orchestrator and Component 2.

C1's boundary test, aimed at C2, and for the same reason: `C2_MODE` appears in
the configuration and in compose, and it would be easy for the HTTP path to be
a client with nothing on the other end that nobody had ever run. The
component's own service is stood up over an ASGI transport, with no server and
no Docker, and every stage call is made through it.

The real component answers, not a double, because the double cannot prove the
wire shapes: the code stages return files plus manifest rows rather than one
artefact, and that shape only exists where the component and the client meet.
The model is scripted, so the run is deterministic and free.

The design under test is CannedC1's, which is the honest choice: it is what a
C2 run in these tests actually reads, an actor who creates a record over two
screens, and it exercises the mapping the rule arm performs.
"""

import json

import httpx
import pytest
from c2.app import create_app as create_c2_app
from c2.service import C2
from orchestrator.checks.coverage import with_coverage
from orchestrator.clients.c2 import (
    FilesOutcome,
    HttpC2,
    InProcessC2,
    PushOutcome,
    make_c2_client,
)
from orchestrator.clients.canned import CannedC1, CannedC2
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sdlc_contracts import BuildReport, BuildStepReport, EndpointTraces, ManifestRow


def scripted_model() -> FunctionModel:
    """One model that answers whichever C2 agent is asking.

    The agents are told apart by the shape they demand rather than by call
    order, so a test that drives one stage does not depend on which stages ran
    before it.
    """

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        tool = info.output_tools[0]
        properties = set((tool.parameters_json_schema or {}).get("properties", {}))
        if "endpoints" in properties:
            payload = {
                "entities": [
                    {
                        "name": "Record",
                        "fields": [{"name": "name", "type": "string"}],
                        "requirement_ids": ["R-1"],
                    }
                ],
                "endpoints": [
                    {
                        "method": "POST",
                        "path": "/records",
                        "summary": "Create a record",
                        "auth_actors": ["Someone"],
                        "request": {
                            "entity": "Record",
                            "fields": [{"name": "name", "type": "string"}],
                        },
                        "response": {"entity": "Record"},
                        "screen_ids": ["flow-a1/s1"],
                        "action_ids": ["l1"],
                        "story_ids": ["US-1"],
                        "requirement_ids": ["R-1"],
                    }
                ],
            }
        elif "rationale" in properties:
            payload = {"rationale": "One deployable unit for one team."}
        else:
            payload = {"content": "// filled\n"}
        return ModelResponse(parts=[ToolCallPart(tool.name, json.dumps(payload))])

    return FunctionModel(respond)


@pytest.fixture
async def over_http():
    """The component's own service, reachable without a port being opened."""
    component = C2(scripted_model())
    app = create_c2_app(component)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://c2") as http:
            yield HttpC2("http://c2", client=http)


@pytest.fixture
async def design():
    """A whole design, from the double the spine tests already run on."""
    c1 = CannedC1()
    requirements = (await c1.parse_requirements("Someone creates a record.")).artefact
    graph = (await c1.build_graph(requirements.requirements, text="x")).artefact
    wireframes = (
        await c1.draw_wireframes(
            graph, requirement_ids=[r.id for r in requirements.requirements], version="v1"
        )
    ).artefact
    sprint = (await c1.plan_sprint(requirements.requirements, graph)).artefact
    # Coverage is derived by the read model, never stored, so a C2 run reading
    # the artefact straight out of the table would see none of it.
    return graph, with_coverage(wireframes, sprint, graph), sprint


class TestTheServiceAnswersEveryStage:
    async def test_the_scope_survives_the_round_trip(self, over_http, design) -> None:
        _, wireframes, sprint = design
        outcome = await over_http.derive_scope(sprint, wireframes)
        assert outcome.artefact.in_scope_ids == ["US-1"]
        story = outcome.artefact.stories[0]
        assert story.traces.screen_ids == ["flow-a1/s1", "flow-a1/s2"]
        assert outcome.summary
        assert outcome.notes["stories_in_scope"] == 1

    async def test_the_stack_survives_with_its_unavailable_reason(self, over_http, design) -> None:
        graph, _, _ = design
        outcome = await over_http.propose_stack(graph)
        artefact = outcome.artefact
        assert artefact.recommended_id in {c.id for c in artefact.candidates}
        unavailable = [c for c in artefact.candidates if not c.available]
        # The contract refuses an unavailable candidate with no reason, so this
        # arriving at all means the honesty survived serialisation.
        assert unavailable and all(c.unavailable_reason for c in unavailable)
        # Arithmetic, not prose: the score is not a field any model output has.
        assert all(0 <= c.score <= 100 for c in artefact.candidates)

    async def test_both_contract_arms_and_the_comparison_survive(self, over_http, design) -> None:
        graph, wireframes, sprint = design
        scope = (await over_http.derive_scope(sprint, wireframes)).artefact
        outcome = await over_http.infer_contract(1, graph, wireframes, scope, arm="rule")
        artefact = outcome.artefact

        assert artefact.rule_arm.endpoints, "the rule arm always produces something"
        assert artefact.llm_arm is not None and artefact.llm_failure is None
        assert artefact.comparison is not None
        assert artefact.chosen == "rule"

        # Traces are a model on arrival, not a dict: every reader indexes them.
        traces = artefact.contract.endpoints[0].traces
        assert isinstance(traces, EndpointTraces)
        assert not traces.is_empty
        assert traces.requirement_ids == ["R-1"] and traces.story_ids == ["US-1"]
        # Screen grounding is deliberately absent here and that is the honest
        # answer for this design: its only link says "Save", which names
        # neither the verb nor the entity, so there is no screen evidence to
        # claim. The real corpus grounds 15 of 15 endpoints on the cold chain
        # design; the rule arm's own tests own that question.
        assert traces.screen_ids == []

    async def test_the_code_stages_answer_files_and_typed_manifest_rows(
        self, over_http, design
    ) -> None:
        graph, wireframes, sprint = design
        scope = (await over_http.derive_scope(sprint, wireframes)).artefact
        contract = (await over_http.infer_contract(1, graph, wireframes, scope)).artefact.contract

        front = await over_http.generate_frontend(
            "Records", contract, wireframes, scope, design_version=1, arm="rule"
        )
        back = await over_http.generate_backend(contract, arm="rule")

        assert isinstance(front, FilesOutcome) and isinstance(back, FilesOutcome)
        assert all(isinstance(row, ManifestRow) for row in front.manifest + back.manifest)
        assert {row.path for row in front.manifest} == set(front.files)
        assert any(path.startswith("apps/web/src/pages/") for path in front.files)
        assert any(path.startswith("apps/api/src/routes/") for path in back.files)
        assert all(row.arm == "rule" for row in front.manifest + back.manifest)

    async def test_agreement_counts_survive_the_round_trip(self, over_http, design) -> None:
        graph, wireframes, sprint = design
        scope = (await over_http.derive_scope(sprint, wireframes)).artefact
        contract = (await over_http.infer_contract(1, graph, wireframes, scope)).artefact.contract
        front = await over_http.generate_frontend(
            "Records", contract, wireframes, scope, design_version=1, arm="rule"
        )
        back = await over_http.generate_backend(contract)

        outcome = await over_http.check_agreement(contract, {**front.files, **back.files})
        counts = outcome.artefact.counts
        assert counts.endpoints_total == len(contract.endpoints)
        assert counts.agreement_rate == 1.0
        assert outcome.artefact.errors == []

    async def test_the_build_report_survives_with_honest_outcomes(
        self, over_http, monkeypatch
    ) -> None:
        """The wire shape, not the build: the sandbox has its own proof, and a
        real npm install has no business inside a boundary test."""
        import c2.service as service_module

        def stub(sources, *, on_step=None):
            return BuildReport(
                toolchain="stub",
                isolation="none: this is the boundary test's stub",
                steps=[
                    BuildStepReport(name="install", command="true", outcome="failed"),
                    BuildStepReport(name="typecheck", command="true", outcome="not-run"),
                ],
            )

        monkeypatch.setattr(service_module, "run_build", stub)
        outcome = await over_http.build({"README.md": "x"})
        assert [step.outcome for step in outcome.artefact.steps] == ["failed", "not-run"]
        assert outcome.artefact.passed is False
        # A not-run step carries no duration, and the contract enforces it, so
        # this arriving proves the honesty rule crossed the wire intact.
        assert outcome.artefact.steps[1].duration_seconds is None

    async def test_a_push_with_no_connection_is_an_outcome_not_an_error(self, over_http) -> None:
        outcome = await over_http.push(
            {"README.md": "x"}, name="records", token=None, message="Generate v1"
        )
        assert isinstance(outcome, PushOutcome)
        assert outcome.pointer is None
        assert "no GitHub connection" in (outcome.reason or "")


class TestTheDouble:
    """CannedC2 stands where the client stands, so the graph tests can use it."""

    async def test_it_answers_every_call_the_protocol_names(self, design) -> None:
        graph, wireframes, sprint = design
        canned = CannedC2()
        scope = (await canned.derive_scope(sprint, wireframes)).artefact
        assert scope.in_scope_ids == ["US-1"]
        contract = (await canned.infer_contract(1, graph, wireframes, scope)).artefact.contract
        front = await canned.generate_frontend(
            "Records", contract, wireframes, scope, design_version=1, arm="rule"
        )
        back = await canned.generate_backend(contract)
        agreement = await canned.check_agreement(contract, {**front.files, **back.files})
        build = await canned.build({**front.files, **back.files})
        push = await canned.push(front.files, name="records", token=None, message="m")

        assert canned.calls == [
            "sprint-scope",
            "api-contract",
            "frontend-code",
            "backend-code",
            "contract-agreement",
            "build",
            "push",
        ]
        assert build.artefact.passed
        assert push.pointer is None and push.reason
        # Counted from what it was handed. A constant here would pass every
        # assertion about a generation that served nothing.
        assert agreement.artefact.counts.agreement_rate == 1.0

    async def test_its_agreement_falls_when_the_backend_is_missing(self, design) -> None:
        _, wireframes, sprint = design
        canned = CannedC2()
        scope = (await canned.derive_scope(sprint, wireframes)).artefact
        contract = (await canned.infer_contract(1, None, wireframes, scope)).artefact.contract
        front = await canned.generate_frontend(
            "Records", contract, wireframes, scope, design_version=1, arm="rule"
        )
        agreement = await canned.check_agreement(contract, front.files)
        assert agreement.artefact.counts.agreement_rate == 0.0
        assert agreement.artefact.counts.endpoints_missing == ["get-things"]


class TestChoosingTheClient:
    def test_http_mode_gets_the_http_client(self) -> None:
        client = make_c2_client("http", model="google:gemini-2.5-pro", base_url="http://c2")
        assert isinstance(client, HttpC2)
        # It names where the answer came from rather than a model this process
        # merely configured and the other side may not be running.
        assert "http://c2" in client.model

    def test_inprocess_mode_imports_the_component(self) -> None:
        # A built model rather than a string, exactly as C1's tests do it: the
        # signature says `str` because that is what a deployment passes.
        client = make_c2_client("inprocess", model=scripted_model(), base_url="")  # type: ignore[arg-type]
        assert isinstance(client, InProcessC2)
