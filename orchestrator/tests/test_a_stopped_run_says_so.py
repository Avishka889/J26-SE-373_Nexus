"""A run that stops short of its review says so, on the phase it belongs to.

A failed run left nothing on the page: the stages it never reached went back to
pending and said they would start once the stage before them finished, the
review stayed empty, and the reason was written only to the audit log. A draft
whose first run failed read as a draft nobody had started.
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
                app.state.c1.fails.clear()
                async with app.state.pool.connection() as conn:
                    for project_id in created:
                        await store.delete_project(conn, project_id, owner_id=DEV_OWNER_ID)


async def _stopped(client: httpx.AsyncClient) -> tuple[str, str]:
    """A design run that stops at the architecture graph, a stage it cannot pass."""
    client.app.state.c1.fails.add("architecture-graph")
    project_id, run_id = await _start(client)
    await _advance(client, run_id)
    return project_id, run_id


class TestTheSnapshotSaysTheRunStopped:
    async def test_with_its_reason(self, client) -> None:
        project_id, run_id = await _stopped(client)

        design = (await client.get(f"/projects/{project_id}/design")).json()

        assert design["run"]["id"] == run_id
        assert design["run"]["state"] == "failed"
        assert "architecture-graph stage was told to fail" in design["run"]["error"]
        assert design["stages"]["architecture-graph"]["status"] == "failed"
        assert design["stages"]["uml-diagrams"]["status"] == "pending"

    async def test_a_retry_finished_after_it_does_not_hide_it(self, client) -> None:
        project_id, run_id = await _stopped(client)
        await client.post(f"/projects/{project_id}/design/stages/uml-diagrams/retry")
        retry = (await client.get("/runs", params={"project": project_id})).json()[0]
        await _advance(client, retry["id"])

        design = (await client.get(f"/projects/{project_id}/design")).json()

        assert retry["id"] != run_id
        assert design["run"]["id"] == run_id
        assert design["run"]["state"] == "failed"

    async def test_a_phase_that_never_ran_has_no_run(self, client) -> None:
        project_id, _ = await _start(client)
        code = (await client.get(f"/projects/{project_id}/code")).json()
        testing = (await client.get(f"/projects/{project_id}/testing")).json()
        deployment = (await client.get(f"/projects/{project_id}/deployment")).json()

        assert code["run"] is None
        assert testing["run"] is None
        assert deployment["run"] is None


class TestTheConversationSaysItToo:
    async def test_at_the_stage_where_it_stopped(self, client) -> None:
        project_id, _ = await _stopped(client)

        thread = (await client.get(f"/projects/{project_id}/design")).json()["thread"]

        said = [message for message in thread if message["content"].startswith("The run stopped")]
        assert len(said) == 1
        assert said[0]["stageId"] == "architecture-graph"
        assert "architecture-graph stage was told to fail" in said[0]["content"]


class TestNothingIsLeftSpinning:
    async def test_a_resume_that_cannot_find_its_run_puts_the_stages_back(self, client) -> None:
        """A decision recorded for a run whose checkpoint is gone fails the run.
        The stages the decision flipped to generating were left spinning, and
        the page asks again for as long as anything is generating."""
        project_id, run_id = await _start(client)
        async with client.app.state.pool.connection() as conn:
            await store.set_run_state(
                conn, uuid.UUID(run_id), "queued", resume_payload={"kind": "approved"}
            )

        await _advance(client, run_id)

        design = (await client.get(f"/projects/{project_id}/design")).json()
        assert design["run"]["state"] == "failed"
        assert not [
            stage for stage, state in design["stages"].items() if state["status"] == "generating"
        ]
