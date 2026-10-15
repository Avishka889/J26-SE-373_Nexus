"""The service surface: transport only, one endpoint per stage.

Driven through FastAPI's TestClient with a scripted component, because what
this file owns is the boundary: inputs parse into contract types, replies
carry artefact, summary and notes in wire casing, and the push endpoint
answers outcomes rather than errors.
"""

import json

from c2.app import create_app
from c2.contract.rule_arm import generate_rule_contract
from c2.service import C2
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from .design_fixture import graph, scope, sprint, wireframes


def _component() -> C2:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, json.dumps({"rationale": "Plain."}))]
        )

    return C2(FunctionModel(respond))


def _wire(model) -> dict:
    return model.model_dump(by_alias=True, mode="json")


def test_health_and_the_scope_round_trip() -> None:
    with TestClient(create_app(_component())) as client:
        assert client.get("/health").json() == {"status": "ok"}
        answer = client.post(
            "/stages/sprint-scope",
            json={"sprint": _wire(sprint()), "wireframes": _wire(wireframes())},
        )
        assert answer.status_code == 200
        body = answer.json()
        assert body["summary"].startswith("Sprint scope proposed")
        # Wire casing on the artefact, exactly as stored and typed.
        assert body["artefact"]["sprintName"] == "Sprint 1 (proposed)"
        assert body["notes"]["stories_in_scope"] == 1


def test_the_code_stages_answer_files_and_manifest() -> None:
    contract = generate_rule_contract(1, graph(), wireframes(), scope())
    with TestClient(create_app(_component())) as client:
        answer = client.post(
            "/stages/backend-code",
            json={"contract": _wire(contract), "arm": "rule"},
        )
        assert answer.status_code == 200
        body = answer.json()
        assert any(path.startswith("apps/api/src/routes/") for path in body["files"])
        assert all(row["arm"] == "rule" for row in body["manifest"])
        assert {row["path"] for row in body["manifest"]} == set(body["files"])


def test_agreement_is_checkable_over_the_wire() -> None:
    contract = generate_rule_contract(1, graph(), wireframes(), scope())
    with TestClient(create_app(_component())) as client:
        backend = client.post("/stages/backend-code", json={"contract": _wire(contract)}).json()
        answer = client.post(
            "/stages/contract-agreement",
            json={"contract": _wire(contract), "sources": backend["files"]},
        )
        assert answer.status_code == 200
        # Only the backend was handed over, so nothing calls the client: the
        # counts must say unused, not invent agreement.
        assert answer.json()["artefact"]["counts"]["endpointsCalled"] == 0


def test_push_without_a_token_is_an_outcome_not_an_error() -> None:
    with TestClient(create_app(_component())) as client:
        answer = client.post(
            "/push",
            json={"files": {"README.md": "x"}, "name": "shopflow", "message": "m"},
        )
        assert answer.status_code == 200
        body = answer.json()
        assert body["pointer"] is None
        assert "no GitHub connection" in body["reason"]
