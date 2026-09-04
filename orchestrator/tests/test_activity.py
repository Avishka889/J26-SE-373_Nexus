"""What the activity log says each event was, and which phase it belongs to.

The timeline drew failures and change requests with the green success check,
because it read success off the category, and every run event was filed under
Design, because the runner never said which phase a run belonged to.
"""

import contextlib
from collections.abc import AsyncIterator

import httpx
import pytest
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.api.process import outcome_of
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.main import create_app, lifespan_for_tests

from .conftest import needs_db
from .test_deployment_routes import _approved_tests
from .test_testing_routes import _advance


@pytest.mark.parametrize(
    ("action", "outcome"),
    [
        ("Run failed", "failed"),
        ("Run abandoned", "failed"),
        ("Run retired", "failed"),
        ("Requested code changes", "changes"),
        ("Requested a change", "changes"),
        ("Requested changes", "changes"),
        ("Approved the design", "done"),
        ("Re-verified a security fix", "done"),
        ("Released again", "done"),
        ("Started a code run", "info"),
        ("Updated profile settings", "info"),
    ],
)
def test_each_event_says_what_it_was(action: str, outcome: str) -> None:
    assert outcome_of(action) == outcome


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
                app.state.c4.fails.clear()
                async with app.state.pool.connection() as conn:
                    for project_id in created:
                        await store.delete_project(conn, project_id, owner_id=DEV_OWNER_ID)


@needs_db
class TestARunEventsPhase:
    async def test_a_deployment_run_that_fails_is_filed_under_deployment(self, client) -> None:
        """Not Design, which every run event was filed under."""
        project_id = await _approved_tests(client)
        client.app.state.c4.fails.add("risk-assessment")
        started = await client.post(f"/projects/{project_id}/deployment/run")
        assert started.status_code == 200, started.text
        runs = (await client.get("/runs", params={"project": project_id})).json()
        await _advance(client, next(run["id"] for run in runs if run["component"] == "c4"))

        entries = (await client.get("/activity", params={"project": project_id})).json()

        failed = next(entry for entry in entries if entry["title"] == "Run failed")
        assert failed["category"] == "deployment"
        assert failed["outcome"] == "failed"
