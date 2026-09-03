"""What answered a stage, kept on the stage and read back by its page (0015).

Every stage that asks a model now reports, in its notes, the models the
responses named and what they used. That reached the audit log as one line of
words and nowhere a page could read it; these hold each phase to keeping it on
the stage, and to clearing it when a later version is made without a model.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.clients.canned import CannedC1, CannedC2, CannedC3
from orchestrator.clients.canned_c4 import CannedC4
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.graph.runner import RunSupervisor
from orchestrator.main import create_app, lifespan_for_tests

from .conftest import needs_db
from .test_code_spine import _approved_design, _start_code_run
from .test_deployment_spine import _start_deploy_run, _tested
from .test_testing_spine import _generated_code, _start_testing_run

pytestmark = needs_db

#: As a component's notes carry it.
REPORTED = {
    "answered_by": ["deepseek-flash"],
    "thinking": ["disabled"],
    "requests": 2,
    "tokens_in": 3100,
    "tokens_out": 900,
    "reasoning_tokens": 0,
}

#: As the page reads it.
SHOWN = {
    "answeredBy": ["deepseek-flash"],
    "thinking": ["disabled"],
    "requests": 2,
    "tokensIn": 3100,
    "tokensOut": 900,
    "reasoningTokens": 0,
}


def _reporting(outcome: Any, reported: dict | None) -> Any:
    if reported is not None:
        outcome.notes["model_use"] = reported
    return outcome


@dataclass
class ReportingC1(CannedC1):
    """Requirements Analysis reports what answered, as the real component does."""

    reported: dict | None = None

    async def parse_requirements(self, text: str):  # type: ignore[override]
        return _reporting(await super().parse_requirements(text), self.reported)


@dataclass
class ReportingC2(CannedC2):
    """Two of code generation's stages report: one artefact, one set of files."""

    reported: dict | None = None

    async def propose_stack(self, *args, **kwargs):  # type: ignore[override]
        return _reporting(await super().propose_stack(*args, **kwargs), self.reported)

    async def generate_frontend(self, *args, **kwargs):  # type: ignore[override]
        return _reporting(await super().generate_frontend(*args, **kwargs), self.reported)


@dataclass
class ReportingC3(CannedC3):
    reported: dict | None = None

    async def generate_tests(self, *args, **kwargs):  # type: ignore[override]
        return _reporting(await super().generate_tests(*args, **kwargs), self.reported)


@dataclass
class ReportingC4(CannedC4):
    reported: dict | None = None

    async def analyse_changelogs(self, *args, **kwargs):  # type: ignore[override]
        return _reporting(await super().analyse_changelogs(*args, **kwargs), self.reported)


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings, lifespan_factory=lifespan_for_tests)
    app.state.c1 = ReportingC1(reported=REPORTED)
    app.state.c2 = ReportingC2(reported=REPORTED)
    app.state.c3 = ReportingC3(reported=REPORTED)
    app.state.c4 = ReportingC4(reported=REPORTED)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            c.app = app  # type: ignore[attr-defined]
            created: list[str] = []
            c.created_projects = created  # type: ignore[attr-defined]
            try:
                yield c
            finally:
                async with app.state.pool.connection() as conn:
                    for project_id in created:
                        await store.delete_project(conn, project_id, owner_id=DEV_OWNER_ID)


async def _advance(client: httpx.AsyncClient, run_id: Any) -> None:
    supervisor: RunSupervisor = client.app.state.supervisor  # type: ignore[attr-defined]
    await supervisor.advance(uuid.UUID(str(run_id)))


async def _design(client: httpx.AsyncClient) -> tuple[str, str]:
    created = await client.post("/projects", json={"name": "Ledger", "description": ""})
    project_id = created.json()["id"]
    client.created_projects.append(project_id)  # type: ignore[attr-defined]
    await client.patch(f"/projects/{project_id}", json={"requirementText": "A clerk posts."})
    run_id = (await client.get("/runs", params={"project": project_id})).json()[0]["id"]
    await _advance(client, run_id)
    return project_id, run_id


async def _design_stages(client: httpx.AsyncClient, project_id: str) -> dict[str, Any]:
    return (await client.get(f"/projects/{project_id}/design")).json()["stages"]


class TestTheDesignPhase:
    async def test_a_stage_keeps_what_answered_and_its_page_reads_it(
        self, client: httpx.AsyncClient
    ) -> None:
        project_id, _ = await _design(client)

        stages = await _design_stages(client, project_id)

        assert stages["requirements"]["modelUse"] == SHOWN
        entries = (await client.get("/audit", params={"project": project_id})).json()
        generated = next(e for e in entries if e["action"] == "Generated Requirements Analysis")
        assert "answered by deepseek-flash" in generated["detail"]

    async def test_a_stage_made_without_a_model_says_nothing(
        self, client: httpx.AsyncClient
    ) -> None:
        project_id, _ = await _design(client)

        stages = await _design_stages(client, project_id)

        # A projection over other artefacts, and stages whose canned answer
        # reports nothing: none of them claims a model.
        assert stages["domain-model"]["modelUse"] is None
        assert stages["wireframes"]["modelUse"] is None

    async def test_a_version_made_without_a_model_clears_the_earlier_record(
        self, client: httpx.AsyncClient
    ) -> None:
        project_id, run_id = await _design(client)
        client.app.state.c1.reported = None  # type: ignore[attr-defined]
        decided = await client.post(
            f"/projects/{project_id}/design/decision",
            json={"kind": "changes", "by": "A. Chen", "note": "Add a reversal"},
        )
        assert decided.status_code == 200, decided.text

        await _advance(client, run_id)

        stages = await _design_stages(client, project_id)
        assert stages["requirements"]["generatedFromVersion"] == 2
        assert stages["requirements"]["modelUse"] is None

    async def test_a_record_that_does_not_validate_loses_the_record_not_the_stage(
        self, client: httpx.AsyncClient
    ) -> None:
        client.app.state.c1.reported = {"answered_by": [], "requests": 0}  # type: ignore[attr-defined]

        project_id, _ = await _design(client)

        stages = await _design_stages(client, project_id)
        assert stages["requirements"]["status"] == "complete"
        assert stages["requirements"]["modelUse"] is None

    async def test_a_kept_record_that_does_not_validate_does_not_hide_the_phase(
        self, client: httpx.AsyncClient
    ) -> None:
        project_id, _ = await _design(client)
        async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
            await conn.execute(
                "UPDATE app.stage_states SET model_use = '{\"requests\": -1}'::jsonb "
                "WHERE project_id = %s AND stage_id = 'requirements'",
                (project_id,),
            )

        answer = await client.get(f"/projects/{project_id}/design")

        assert answer.status_code == 200, answer.text
        assert answer.json()["stages"]["requirements"]["modelUse"] is None


class TestTheLaterPhases:
    async def test_code_generation_keeps_it_for_an_artefact_and_for_files(
        self, client: httpx.AsyncClient
    ) -> None:
        project_id = await _approved_design(client)
        run, _, _ = await _start_code_run(client, project_id)

        await _advance(client, run["id"])

        stages = (await client.get(f"/projects/{project_id}/code")).json()["stages"]
        assert stages["tech-stack"]["modelUse"] == SHOWN
        assert stages["frontend-code"]["modelUse"] == SHOWN
        assert stages["backend-code"]["modelUse"] is None

    async def test_testing_keeps_it(self, client: httpx.AsyncClient) -> None:
        project_id, code_version = await _generated_code(client)
        run, _ = await _start_testing_run(client, project_id, code_version)

        await _advance(client, run["id"])

        stages = (await client.get(f"/projects/{project_id}/testing")).json()["stages"]
        assert stages["test-generation"]["modelUse"] == SHOWN

    async def test_deployment_keeps_it(self, client: httpx.AsyncClient) -> None:
        project_id, _, test_version = await _tested(client)
        run, _ = await _start_deploy_run(client, project_id, test_version)

        await _advance(client, run["id"])

        stages = (await client.get(f"/projects/{project_id}/deployment")).json()["stages"]
        assert stages["changelog-analysis"]["modelUse"] == SHOWN
