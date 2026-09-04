"""A restart settles what the process before it left running.

Nothing marked a run the old process had been working on. It looked busy for
its component's whole stale window, up to half an hour, and was then abandoned
with "start a new run instead", though Continue goes on from its last saved
step. Now, before running anything, a starting process stops each such run as
one a person can continue, and queues one that never saved a step.
"""

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.main import create_app, lifespan_for_tests

from .conftest import needs_db
from .test_spine import _advance, _start

pytestmark = needs_db


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings, lifespan_factory=lifespan_for_tests)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            c.app = app  # type: ignore[attr-defined]
            created: list[str] = []
            c.created_projects = created  # type: ignore[attr-defined]
            try:
                yield c
            finally:
                app.state.c1.fails.clear()
                async with app.state.pool.connection() as conn:
                    for project_id in created:
                        await store.delete_project(conn, project_id, owner_id=DEV_OWNER_ID)


async def _run(client: httpx.AsyncClient, run_id: str) -> store.Row:
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        run = await store.get_run(conn, uuid.UUID(run_id))
    assert run is not None
    return run


async def _left_running(client: httpx.AsyncClient, run_id: str) -> None:
    """The row as a process that died mid run left it: still saying running."""
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        await store.set_run_state(conn, uuid.UUID(run_id), "running")


class TestARestart:
    async def test_a_run_that_saved_steps_stops_as_one_a_person_can_continue(self, client) -> None:
        component = client.app.state.c1  # type: ignore[attr-defined]
        component.fails.add("architecture-graph")
        _, run_id = await _start(client)
        await _advance(client, run_id)
        component.fails.clear()
        await _left_running(client, run_id)

        await client.app.state.supervisor.stop_orphans()  # type: ignore[attr-defined]

        run = await _run(client, run_id)
        assert run["state"] == "failed"
        assert "the orchestrator restarted while this run was working" in run["error"]
        continued = await client.post(f"/runs/{run_id}/continue")
        assert continued.status_code == 200, continued.text

    async def test_starting_the_supervisor_settles_them_before_anything_runs(self, client) -> None:
        component = client.app.state.c1  # type: ignore[attr-defined]
        component.fails.add("architecture-graph")
        _, run_id = await _start(client)
        await _advance(client, run_id)
        component.fails.clear()
        await _left_running(client, run_id)
        supervisor = client.app.state.supervisor  # type: ignore[attr-defined]

        await supervisor.start()
        await supervisor.stop()

        assert (await _run(client, run_id))["state"] == "failed"

    async def test_a_run_that_saved_nothing_is_queued_to_start(self, client) -> None:
        created = await client.post("/projects", json={"name": "Restart case"})
        project_id = created.json()["id"]
        client.created_projects.append(project_id)  # type: ignore[attr-defined]
        async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
            run = await store.create_run(
                conn, project_id=project_id, requirements_version=1, component="c1"
            )
        await _left_running(client, str(run["id"]))

        await client.app.state.supervisor.stop_orphans()  # type: ignore[attr-defined]

        assert (await _run(client, str(run["id"])))["state"] == "queued"

    async def test_a_run_waiting_on_a_person_is_left_waiting(self, client) -> None:
        _, run_id = await _start(client)
        await _advance(client, run_id)
        assert (await _run(client, run_id))["state"] == "awaiting_gate"

        await client.app.state.supervisor.stop_orphans()  # type: ignore[attr-defined]

        assert (await _run(client, run_id))["state"] == "awaiting_gate"


class TestAStalledRunThePollerFinds:
    async def test_it_is_stopped_as_one_to_continue_not_to_start_again(self, client) -> None:
        """It was abandoned with "start a new run instead", though Continue goes
        on from its last saved step and starting again pays for every stage."""
        component = client.app.state.c1  # type: ignore[attr-defined]
        component.fails.add("architecture-graph")
        _, run_id = await _start(client)
        await _advance(client, run_id)
        component.fails.clear()
        await _left_running(client, run_id)

        await client.app.state.supervisor.advance(uuid.UUID(run_id))  # type: ignore[attr-defined]

        run = await _run(client, run_id)
        assert run["state"] == "failed"
        assert "Continue it to go on from where it stopped" in run["error"]
        assert "Start a new run" not in run["error"]
        continued = await client.post(f"/runs/{run_id}/continue")
        assert continued.status_code == 200, continued.text
