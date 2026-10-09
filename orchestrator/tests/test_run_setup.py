"""What a run ran on, written on the run (0014).

A run wrote its model once, into the free text of its "Run started" entry, and
nowhere else. A regeneration after "changes" resumes the same run and wrote no
model at all, and neither did a single stage retry. Once a person can choose,
two runs of the same phase can differ, and a version that cannot be traced to
the settings that made it can never be traced afterwards.
"""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.clients.canned import CannedC1
from orchestrator.clients.thinking import thinking_sent
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.graph.runner import RunSupervisor
from orchestrator.main import create_app, lifespan_for_tests

from .conftest import needs_db

DEEPSEEK = "deepseek:deepseek-flash"


def _in_process(component: str, model: str) -> Any:
    if component == "c1":
        from orchestrator.clients.c1 import InProcessC1

        return InProcessC1(model)
    if component == "c2":
        from orchestrator.clients.c2 import InProcessC2

        return InProcessC2(model)
    if component == "c3":
        from orchestrator.clients.c3 import InProcessC3

        return InProcessC3(model)
    from orchestrator.clients.c4 import InProcessC4

    return InProcessC4(model)


class TestWhatAComponentAsksAboutThinking:
    """Read from the settings its agents are built with, never assumed."""

    def test_a_body_that_turns_thinking_off_says_disabled(self) -> None:
        assert thinking_sent({"extra_body": {"thinking": {"type": "disabled"}}}) == "disabled"

    def test_saying_nothing_leaves_it_to_the_provider(self) -> None:
        assert thinking_sent({"max_tokens": 16384}) == "default"
        assert thinking_sent(None) == "default"

    @pytest.mark.parametrize("component", ["c1", "c2", "c3", "c4"])
    def test_every_in_process_client_says_deepseek_thinking_is_off(
        self, component: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Building a client builds its agents, and a provider refuses to
        # construct without a key. Nothing here calls one.
        monkeypatch.setenv("DEEPSEEK_API_KEY", "placeholder")

        assert _in_process(component, DEEPSEEK).thinking == "disabled"

    def test_a_provider_the_component_sends_nothing_is_left_its_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder")

        assert _in_process("c1", "anthropic:claude-haiku-4-5").thinking == "default"

    def test_a_supervisor_without_a_client_records_nothing_rather_than_a_guess(self) -> None:
        runner = RunSupervisor(pool=None, graph=None)  # type: ignore[arg-type]

        assert runner._setup("c1") == (None, None)


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    """An app whose design component says what a DeepSeek client says.

    Canned, so the run makes no request; given the model and thinking a real
    DeepSeek client reports, so what the run records can be read back.
    """
    app = create_app(settings, lifespan_factory=lifespan_for_tests)
    app.state.c1 = CannedC1(model=DEEPSEEK, thinking="disabled")
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


async def _start(client: httpx.AsyncClient) -> tuple[str, str]:
    created = await client.post("/projects", json={"name": "Calculator", "description": ""})
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]
    client.created_projects.append(project_id)  # type: ignore[attr-defined]
    patched = await client.patch(
        f"/projects/{project_id}", json={"requirementText": "Build a simple calculator app"}
    )
    assert patched.status_code == 200, patched.text
    runs = (await client.get("/runs", params={"project": project_id})).json()
    return project_id, runs[0]["id"]


async def _advance(client: httpx.AsyncClient, run_id: str) -> None:
    supervisor: RunSupervisor = client.app.state.supervisor  # type: ignore[attr-defined]
    await supervisor.advance(uuid.UUID(run_id))


async def _entries(client: httpx.AsyncClient, project_id: str, action: str) -> list[dict]:
    entries = (await client.get("/audit", params={"project": project_id})).json()
    return [e for e in entries if e["action"] == action]


async def _request_changes(client: httpx.AsyncClient, project_id: str) -> None:
    decided = await client.post(
        f"/projects/{project_id}/design/decision",
        json={"kind": "changes", "by": "A. Chen", "note": "Add a memory function"},
    )
    assert decided.status_code == 200, decided.text


@needs_db
class TestARunRecordsWhatItRanOn:
    async def test_a_run_records_its_model_and_thinking_when_it_starts(
        self, client: httpx.AsyncClient
    ) -> None:
        project_id, run_id = await _start(client)

        await _advance(client, run_id)

        run = (await client.get(f"/runs/{run_id}")).json()
        assert (run["model"], run["thinking"]) == (DEEPSEEK, "disabled")
        [started] = await _entries(client, project_id, "Run started")
        assert started["detail"] == (
            "Requirements and Design on deepseek:deepseek-flash, thinking off."
        )

    async def test_the_phase_page_reads_what_its_run_ran_on(
        self, client: httpx.AsyncClient
    ) -> None:
        project_id, run_id = await _start(client)

        await _advance(client, run_id)

        snapshot = (await client.get(f"/projects/{project_id}/design")).json()
        assert (snapshot["run"]["model"], snapshot["run"]["thinking"]) == (DEEPSEEK, "disabled")

    async def test_a_regeneration_after_changes_says_what_it_ran_on(
        self, client: httpx.AsyncClient
    ) -> None:
        project_id, run_id = await _start(client)
        await _advance(client, run_id)
        await _request_changes(client, project_id)

        await _advance(client, run_id)

        [resumed] = await _entries(client, project_id, "Run resumed")
        assert resumed["detail"] == (
            "Requirements and Design regenerating version 2 on "
            "deepseek:deepseek-flash, thinking off."
        )

    async def test_a_regeneration_on_another_model_says_what_the_run_started_on(
        self, client: httpx.AsyncClient
    ) -> None:
        project_id, run_id = await _start(client)
        await _advance(client, run_id)
        # The process restarted with another model between the review opening
        # and the change being asked for: the regeneration runs on that one.
        component: CannedC1 = client.app.state.c1  # type: ignore[attr-defined]
        component.model, component.thinking = "anthropic:claude-sonnet-5", "default"
        await _request_changes(client, project_id)

        await _advance(client, run_id)

        [resumed] = await _entries(client, project_id, "Run resumed")
        assert "on anthropic:claude-sonnet-5, thinking left to the provider." in resumed["detail"]
        assert "The run started on deepseek:deepseek-flash, thinking off." in resumed["detail"]
        # The run keeps the record of how it began.
        run = (await client.get(f"/runs/{run_id}")).json()
        assert run["model"] == DEEPSEEK

    async def test_a_stage_retry_records_what_it_ran_on(self, client: httpx.AsyncClient) -> None:
        project_id, run_id = await _start(client)
        await _advance(client, run_id)
        retried = await client.post(f"/projects/{project_id}/design/stages/wireframes/retry")
        assert retried.status_code == 200, retried.text
        runs = (await client.get("/runs", params={"project": project_id})).json()
        retry = next(r for r in runs if r["onlyStage"] == "wireframes")

        await _advance(client, retry["id"])

        run = (await client.get(f"/runs/{retry['id']}")).json()
        assert (run["model"], run["thinking"]) == (DEEPSEEK, "disabled")
        [regenerated] = await _entries(client, project_id, "Regenerated one stage")
        assert regenerated["detail"].endswith("on deepseek:deepseek-flash, thinking off.")
