"""What waits on a person, in one list for the bell.

The bell said "Nothing needs you right now" while thirty seven reviews waited:
its two invented demo lines were removed and nothing real replaced them. A
review waiting, a rollback waiting for its decision, and a run that stopped in
the phase a project is in are each something only a person can move.
"""

import contextlib
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
                app.state.c1.fails.clear()
                async with app.state.pool.connection() as conn:
                    for project_id in created:
                        await store.delete_project(conn, project_id, owner_id=DEV_OWNER_ID)


async def _waiting(client: httpx.AsyncClient, project_id: str) -> list[dict]:
    items = (await client.get("/attention")).json()
    return [item for item in items if item["projectId"] == project_id]


class TestWhatWaits:
    async def test_a_review_waiting_until_it_is_decided(self, client) -> None:
        project_id, run_id = await _start(client)
        await _advance(client, run_id)

        waiting = await _waiting(client, project_id)

        assert [(item["kind"], item["phase"]) for item in waiting] == [("review", "design")]
        assert waiting[0]["projectName"]
        assert "review" in waiting[0]["title"].lower()

        await client.post(
            f"/projects/{project_id}/design/decision", json={"kind": "approved", "by": "you"}
        )
        assert await _waiting(client, project_id) == []

    async def test_a_run_that_stopped(self, client) -> None:
        client.app.state.c1.fails.add("architecture-graph")
        project_id, run_id = await _start(client)
        await _advance(client, run_id)

        waiting = await _waiting(client, project_id)

        assert [(item["kind"], item["phase"]) for item in waiting] == [("stopped", "design")]

    async def test_a_rollback_waiting_for_its_decision(self, client) -> None:
        project_id = await _approved_tests(client)
        async with client.app.state.pool.connection() as conn:
            row, _ = await store.create_deployment(
                conn,
                project_id=project_id,
                deploy_version=1,
                kind="release",
                target="local",
                plan_id=f"{project_id}-deploy-v1",
                candidate_hash="c" * 64,
                idempotency_key=f"{project_id}-attention",
                authorised={"kind": "gate", "by": "you", "gateId": "g-1"},
                requested_by="you",
            )
            await store.finish_deployment(conn, row["id"], state="awaiting-rollback-approval")

        waiting = await _waiting(client, project_id)

        assert ("rollback", "deployment") in [(item["kind"], item["phase"]) for item in waiting]
        assert waiting[0]["kind"] == "rollback", "a release that stopped serving comes first"
