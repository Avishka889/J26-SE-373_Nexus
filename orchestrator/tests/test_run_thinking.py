"""Each run thinks at the level its account chose for the phase (3B).

The account's choice is read when a run starts and when a single stage retry
starts, and a run keeps it for its whole life: a regeneration after "changes"
resumes at the level the run began at, whatever was chosen since. The level
reaches the component through a per task context, and each in-process client
keeps one component per level.

These never write the development identity's settings: the runs here stub the
account's choices, and the settings route is driven as the test owner.
"""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.clients.canned import CannedC1
from orchestrator.clients.thinking import RUN_THINKING, Levelled, level_recorded
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.graph.runner import RunSupervisor
from orchestrator.main import create_app, lifespan_for_tests
from pydantic_ai import PromptedOutput

from .conftest import needs_db

DEEPSEEK = "deepseek:deepseek-flash"


class _Component:
    """A component that says whether it is open, as C1's and C2's are contexts."""

    def __init__(self, level: str) -> None:
        self.level = level
        self.open = False

    async def __aenter__(self) -> "_Component":
        self.open = True
        return self

    async def __aexit__(self, *args: Any) -> None:
        self.open = False


class TestOneComponentPerLevel:
    async def test_outside_a_run_the_configured_component_answers(self) -> None:
        levels = Levelled(_Component, "off", opens=True)

        assert (await levels.current()).level == "off"

    async def test_a_run_gets_its_level_built_once_and_closed_with_the_rest(self) -> None:
        levels = Levelled(_Component, "off", opens=True)
        await levels.open()
        asked = RUN_THINKING.set("high")
        try:
            first = await levels.current()
            again = await levels.current()
        finally:
            RUN_THINKING.reset(asked)

        assert first is again and first.level == "high" and first.open
        await levels.close()
        assert not first.open and not levels.configured.open

    def test_a_level_is_read_back_from_what_its_run_recorded(self) -> None:
        assert level_recorded("high") == "high"
        assert [level_recorded(sent) for sent in ("disabled", "default", None)] == ["off"] * 3

    def test_the_in_process_client_builds_a_thinking_component_for_a_thinking_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "placeholder")
        from orchestrator.clients.c1 import InProcessC1

        client = InProcessC1(DEEPSEEK)
        assert client.thinking_for("max") == "max" and client.thinking == "disabled"

        import asyncio

        async def at(level: str) -> Any:
            asked = RUN_THINKING.set(level)
            try:
                return await client._levels.current()
            finally:
                RUN_THINKING.reset(asked)

        thinking = asyncio.run(at("high"))
        assert thinking is not client._c1
        assert isinstance(thinking._requirements.output_type, PromptedOutput)
        assert not isinstance(client._c1._requirements.output_type, PromptedOutput)


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings, lifespan_factory=lifespan_for_tests)
    # Says what a DeepSeek client says, so a level reads back as itself.
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


@pytest.fixture
def choices(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """The account's choices, stubbed rather than written to anybody's settings."""
    chosen: dict[str, str] = {}

    async def read(conn: Any, owner_id: str) -> dict[str, str]:
        return dict(chosen)

    monkeypatch.setattr(store, "thinking_choices", read)
    return chosen


async def _start(client: httpx.AsyncClient) -> tuple[str, str]:
    created = await client.post("/projects", json={"name": "Ledger", "description": ""})
    project_id = created.json()["id"]
    client.created_projects.append(project_id)  # type: ignore[attr-defined]
    await client.patch(f"/projects/{project_id}", json={"requirementText": "A clerk posts."})
    run_id = (await client.get("/runs", params={"project": project_id})).json()[0]["id"]
    return project_id, run_id


async def _advance(client: httpx.AsyncClient, run_id: str) -> None:
    supervisor: RunSupervisor = client.app.state.supervisor  # type: ignore[attr-defined]
    await supervisor.advance(uuid.UUID(run_id))


def _canned(client: httpx.AsyncClient) -> CannedC1:
    return client.app.state.c1  # type: ignore[attr-defined]


@needs_db
class TestARunThinksAtItsAccountsLevel:
    async def test_a_run_starts_at_the_level_its_account_chose(
        self, client: httpx.AsyncClient, choices: dict[str, str]
    ) -> None:
        choices["design"] = "high"
        project_id, run_id = await _start(client)

        await _advance(client, run_id)

        assert set(_canned(client).levels) == {"high"}, "a stage was asked at another level"
        run = (await client.get(f"/runs/{run_id}")).json()
        assert run["thinking"] == "high"
        entries = (await client.get("/audit", params={"project": project_id})).json()
        started = next(e for e in entries if e["action"] == "Run started")
        assert started["detail"].endswith("thinking on, high effort.")

    async def test_with_no_choice_a_run_starts_at_the_configured_level(
        self, client: httpx.AsyncClient, choices: dict[str, str]
    ) -> None:
        _canned(client).level = "low"
        _, run_id = await _start(client)

        await _advance(client, run_id)

        assert set(_canned(client).levels) == {"low"}
        assert (await client.get(f"/runs/{run_id}")).json()["thinking"] == "low"

    async def test_a_regeneration_keeps_the_level_its_run_began_at(
        self, client: httpx.AsyncClient, choices: dict[str, str]
    ) -> None:
        choices["design"] = "high"
        project_id, run_id = await _start(client)
        await _advance(client, run_id)
        # Chosen while the review waits: it applies from the next run.
        choices["design"] = "off"
        before = len(_canned(client).levels)
        decided = await client.post(
            f"/projects/{project_id}/design/decision",
            json={"kind": "changes", "by": "A. Chen", "note": "Add a reversal"},
        )
        assert decided.status_code == 200, decided.text

        await _advance(client, run_id)

        assert set(_canned(client).levels[before:]) == {"high"}
        entries = (await client.get("/audit", params={"project": project_id})).json()
        resumed = next(e for e in entries if e["action"] == "Run resumed")
        assert "thinking on, high effort." in resumed["detail"]

    async def test_a_stage_retry_takes_the_level_chosen_now(
        self, client: httpx.AsyncClient, choices: dict[str, str]
    ) -> None:
        choices["design"] = "high"
        project_id, run_id = await _start(client)
        await _advance(client, run_id)
        choices["design"] = "max"
        retried = await client.post(f"/projects/{project_id}/design/stages/wireframes/retry")
        assert retried.status_code == 200, retried.text
        runs = (await client.get("/runs", params={"project": project_id})).json()
        retry = next(r for r in runs if r["onlyStage"] == "wireframes")
        before = len(_canned(client).levels)

        await _advance(client, retry["id"])

        assert set(_canned(client).levels[before:]) == {"max"}
        assert (await client.get(f"/runs/{retry['id']}")).json()["thinking"] == "max"
