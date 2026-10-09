"""A stopped run goes on from where it stopped, at a person's request.

The only way past a run that stopped was to start over, which generated every
stage again and paid again for every one that had already finished. Try again
on the stage that stopped it regenerated that one stage and stopped there, so
the review still never came. LangGraph keeps the run's progress at every step,
so continuing re-runs the stage that broke and what follows it, and nothing
that already finished.

Only a person continues a run. The poller never does, because restarting runs
on its own is how an approved design was once regenerated in place.
"""

import contextlib
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.main import create_app, lifespan_for_tests

from .conftest import needs_db
from .test_deployment_routes import _approved_tests
from .test_spine import _advance, _start

pytestmark = needs_db


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    async with _serving(create_app(settings, lifespan_factory=lifespan_for_tests)) as c:
        yield c


@contextlib.asynccontextmanager
async def _serving(app) -> AsyncIterator[httpx.AsyncClient]:
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


async def _stopped(client: httpx.AsyncClient) -> tuple[str, str]:
    """A design run stopped at the architecture graph, its cause since mended."""
    component = client.app.state.c1
    component.fails.add("architecture-graph")
    project_id, run_id = await _start(client)
    await _advance(client, run_id)
    component.fails.clear()
    component.calls.clear()
    return project_id, run_id


async def _runs(client: httpx.AsyncClient, project_id: str) -> list[dict]:
    return (await client.get("/runs", params={"project": project_id})).json()


class TestContinuingAStoppedRun:
    async def test_it_goes_on_from_the_stage_that_stopped_it(self, client) -> None:
        project_id, run_id = await _stopped(client)

        answer = await client.post(f"/runs/{run_id}/continue")
        assert answer.status_code == 200, answer.text
        await _advance(client, run_id)

        design = (await client.get(f"/projects/{project_id}/design")).json()
        assert design["run"]["id"] == run_id
        assert design["run"]["state"] == "awaiting_gate"
        assert design["stages"]["architecture-graph"]["status"] == "complete"
        assert design["stages"]["design-review"]["status"] == "complete"
        calls = client.app.state.c1.calls
        assert calls[0] == "architecture-graph"
        assert "requirements" not in calls, "a stage that had finished was paid for again"

    async def test_the_snapshot_names_where_it_stopped(self, client) -> None:
        project_id, _ = await _stopped(client)

        design = (await client.get(f"/projects/{project_id}/design")).json()

        assert design["run"]["stoppedAt"] == "architecture-graph"

    async def test_try_again_on_that_stage_continues_the_same_run(self, client) -> None:
        project_id, run_id = await _stopped(client)
        before = await _runs(client, project_id)

        answer = await client.post(f"/projects/{project_id}/design/stages/architecture-graph/retry")
        assert answer.status_code == 200, answer.text
        await _advance(client, run_id)

        assert len(await _runs(client, project_id)) == len(before), "a second run was started"
        design = (await client.get(f"/projects/{project_id}/design")).json()
        assert design["run"]["state"] == "awaiting_gate"
        assert "requirements" not in client.app.state.c1.calls

    async def test_try_again_on_a_leaf_that_failed_earlier_is_still_one_stage(self, client) -> None:
        """A leaf that failed before the stage that stopped the run finished as
        far as the run is concerned, so continuing would not redo it: its Try
        again regenerates it alone, as before."""
        project_id = await _approved_tests(client)
        component = client.app.state.c4
        component.fails.update({"changelog-analysis", "risk-assessment"})
        started = await client.post(f"/projects/{project_id}/deployment/run")
        assert started.status_code == 200, started.text
        run_id = next(
            run["id"] for run in await _runs(client, project_id) if run["component"] == "c4"
        )
        await _advance(client, run_id)
        component.fails.clear()
        before = await _runs(client, project_id)

        answer = await client.post(
            f"/projects/{project_id}/deployment/stages/changelog-analysis/retry"
        )

        assert answer.status_code == 200, answer.text
        after = await _runs(client, project_id)
        assert len(after) == len(before) + 1
        assert after[0]["onlyStage"] == "changelog-analysis"


class TestWhatCannotBeContinued:
    async def test_a_run_that_did_not_stop(self, client) -> None:
        _, run_id = await _start(client)
        await _advance(client, run_id)

        answer = await client.post(f"/runs/{run_id}/continue")

        assert answer.status_code == 409
        assert "did not stop" in answer.json()["error"]

    async def test_a_run_a_newer_one_replaced(self, client) -> None:
        project_id, run_id = await _stopped(client)
        restarted = await client.post("/runs", json={"projectId": project_id, "component": "c1"})
        assert restarted.status_code == 201, restarted.text

        answer = await client.post(f"/runs/{run_id}/continue")

        assert answer.status_code == 409
        assert "newer run" in answer.json()["error"]

    async def test_the_same_run_twice(self, client) -> None:
        _, run_id = await _stopped(client)
        first = await client.post(f"/runs/{run_id}/continue")

        second = await client.post(f"/runs/{run_id}/continue")

        assert first.status_code == 200, first.text
        assert second.status_code == 409

    async def test_a_run_with_no_saved_progress_says_so(self, client) -> None:
        """A run that failed before its first step has nothing to go on from.
        Continuing it fails again with that reason, rather than starting it
        from the beginning under the name of continuing."""
        project_id, run_id = await _start(client)
        async with client.app.state.pool.connection() as conn:
            await store.set_run_state(conn, uuid.UUID(run_id), "failed", error="it never started")

        answer = await client.post(f"/runs/{run_id}/continue")
        assert answer.status_code == 200, answer.text
        await _advance(client, run_id)

        design = (await client.get(f"/projects/{project_id}/design")).json()
        assert design["run"]["state"] == "failed"
        assert "start it over" in design["run"]["error"]
        assert not client.app.state.c1.calls
