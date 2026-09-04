"""A project's status names the phase it waits in now.

The status read "approved, ever": a project whose design had moved on to a
version waiting on its review still read Testing because an older design had
been approved (Cold Chain), one whose newest test version waited read Deploy
(Task Tracker), and one read Complete with a test review waiting (Calculator).
The list and the project page derived it two ways and disagreed, and a project
whose first run stopped read as a Draft nobody had started.

Each phase now counts only when its current version is approved, and the
phases agree with each other: the code was generated from the current design,
and the tests measured the current code.
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
from .test_checkpoint3 import _with_proposal
from .test_code_routes import _advance_all, _generated
from .test_deployment_routes import _approved_tests
from .test_spine import _advance, _start
from .test_testing_routes import _advance as _advance_test

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


async def _both(client: httpx.AsyncClient, project_id: str) -> tuple[dict, dict]:
    """The project as the list shows it, and as its own page does."""
    listed = next(p for p in (await client.get("/projects")).json() if p["id"] == project_id)
    alone = (await client.get(f"/projects/{project_id}")).json()
    return listed, alone


async def _status(client: httpx.AsyncClient, project_id: str) -> str:
    listed, alone = await _both(client, project_id)
    fields = ("status", "runStopped", "progress", "phaseProgress", "reqPhase")
    assert {k: listed[k] for k in fields} == {k: alone[k] for k in fields}, (
        "the list and the project page disagree"
    )
    return alone["status"]


class TestTheCurrentVersionDecides:
    async def test_a_design_change_waiting_puts_the_project_back_in_design(self, client) -> None:
        project_id, _ = await _generated(client)
        await client.post(
            f"/projects/{project_id}/code/decision", json={"kind": "approved", "by": "you"}
        )
        await _advance_all(client, project_id)
        assert await _status(client, project_id) == "testing"

        changed = await client.post(
            f"/projects/{project_id}/design/changes", json={"note": "add a due date"}
        )
        assert changed.status_code == 200, changed.text
        await _advance_all(client, project_id)

        assert await _status(client, project_id) == "design"

    async def test_a_new_test_version_waiting_reads_testing(self, client) -> None:
        project_id = await _approved_tests(client)
        assert await _status(client, project_id) == "deploy"

        started = await client.post(f"/projects/{project_id}/testing/run")
        assert started.status_code == 200, started.text
        runs = (await client.get("/runs", params={"project": project_id})).json()
        await _advance_test(client, runs[0]["id"])

        assert await _status(client, project_id) == "testing"

    async def test_an_applied_fix_sends_the_project_back_to_testing(self, client) -> None:
        """The approved tests measured the code before the fix. The fix is a new
        code version, approved through the patch, that nothing has tested yet."""
        project_id, _ = await _with_proposal(client)
        decided = await client.post(
            f"/projects/{project_id}/testing/decision", json={"kind": "approved", "by": "you"}
        )
        assert decided.status_code == 200, decided.text
        runs = (await client.get("/runs", params={"project": project_id})).json()
        await _advance_test(client, runs[0]["id"])
        assert await _status(client, project_id) == "deploy"

        await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/decision",
            json={"decision": "accepted", "by": "you"},
        )
        applied = await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/apply", json={"by": "you"}
        )
        assert applied.status_code == 200, applied.text

        assert await _status(client, project_id) == "testing"


class TestARunThatStopped:
    async def test_a_first_run_that_stopped_is_not_a_draft(self, client) -> None:
        client.app.state.c1.fails.add("architecture-graph")
        project_id, run_id = await _start(client)
        await _advance(client, run_id)

        listed, alone = await _both(client, project_id)

        assert await _status(client, project_id) == "design"
        assert listed["runStopped"] is True and alone["runStopped"] is True

    async def test_a_project_nobody_started_is_a_draft(self, client) -> None:
        created = await client.post("/projects", json={"name": "Blank", "description": ""})
        project_id = created.json()["id"]
        client.created_projects.append(project_id)

        assert await _status(client, project_id) == "draft"
