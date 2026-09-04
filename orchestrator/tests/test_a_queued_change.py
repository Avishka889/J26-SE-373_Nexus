"""A change queued behind a run that then stopped is not left behind.

A note that arrives while a design run is working is queued, not raced, and the
run takes it at its loop point. A run that stopped first never did. The next
change then opened a version without it, since only applied notes are a run's
input; and a later drain started a run at the queued version, below the newest,
whose review the page never showed.
"""

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


class TestAChangeQueuedBehindARunThatStopped:
    async def test_the_next_change_s_version_carries_it(self, client) -> None:
        component = client.app.state.c1  # type: ignore[attr-defined]
        project_id, run_id = await _start(client)
        # Queued: the first run has not finished.
        queued = await client.post(
            f"/projects/{project_id}/design/changes", json={"note": "Add a due date."}
        )
        assert queued.status_code == 200, queued.text
        component.fails.add("requirements")
        await _advance(client, run_id)
        component.fails.clear()

        changed = await client.post(
            f"/projects/{project_id}/design/changes", json={"note": "Add a priority."}
        )

        assert changed.status_code == 200, changed.text
        async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
            newest = await store.current_version(conn, project_id)
            assert await store.queued_notes(conn, project_id) == []
            notes = await store.applied_notes(conn, project_id, newest)
        assert notes == ["Add a due date.", "Add a priority."]


class TestADrainedQueue:
    async def test_never_starts_a_run_below_the_newest_version(self, client) -> None:
        created = await client.post("/projects", json={"name": "Queue case"})
        project_id = created.json()["id"]
        client.created_projects.append(project_id)  # type: ignore[attr-defined]
        async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
            await store.open_version(conn, project_id, note=None, by="you", applied=True)
            await store.open_version(
                conn, project_id, note="Add a due date.", by="you", applied=False
            )
            above = await store.open_version(
                conn, project_id, note="Add a tag.", by="you", applied=True
            )

            version, notes = await store.claim_next_version(conn, project_id, note=None, by="you")

        assert version > above, "a run below the newest version is one nobody sees"
        assert notes == ["Add a due date."]

    async def test_a_queue_at_the_newest_version_is_drained_there(self, client) -> None:
        created = await client.post("/projects", json={"name": "Queue case"})
        project_id = created.json()["id"]
        client.created_projects.append(project_id)  # type: ignore[attr-defined]
        async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
            await store.open_version(conn, project_id, note=None, by="you", applied=True)
            queued = await store.open_version(
                conn, project_id, note="Add a due date.", by="you", applied=False
            )

            version, _ = await store.claim_next_version(conn, project_id, note=None, by="you")

        assert version == queued
