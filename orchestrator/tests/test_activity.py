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
from orchestrator.components import spec_for
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.main import create_app, lifespan_for_tests
from orchestrator.wording import phase_category

from .conftest import needs_db
from .test_deployment_routes import _approved_tests
from .test_testing_routes import _advance


@pytest.mark.parametrize(
    ("action", "outcome"),
    [
        ("Run failed", "failed"),
        ("Run abandoned", "failed"),
        ("Run retired", "failed"),
        ("Run stopped by a restart", "failed"),
        ("Failed to generate Wireframes", "failed"),
        # A person's own act, which only mentions a stop: they were drawn as
        # failures, because the word "stopped" anywhere marked one.
        ("Continued a stopped run", "info"),
        ("Stopped the preview", "info"),
        ("Requested code changes", "changes"),
        ("Requested a change", "changes"),
        ("Requested changes", "changes"),
        ("Approved the design", "done"),
        ("Re-verified a security fix", "done"),
        # How a release or a rollback ended, which nothing recorded (review item X-7).
        ("Released deploy version 2", "done"),
        ("Restored deploy version 1", "done"),
        ("Release failed", "failed"),
        ("Release failed after traffic moved", "failed"),
        ("Release undone before traffic moved", "failed"),
        ("Rollback failed", "failed"),
        ("Rollback failed after traffic moved", "failed"),
        ("Rollback undone before traffic moved", "failed"),
        ("Release finished without verification", "info"),
        ("Monitoring found the release down", "failed"),
        ("Monitoring found the release degraded", "info"),
        # Queued, not released: it read as Succeeded while it waited.
        ("Queued the release again", "info"),
        ("Started a code run", "info"),
        ("Updated profile settings", "info"),
    ],
)
def test_each_event_says_what_it_was(action: str, outcome: str) -> None:
    assert outcome_of(action) == outcome


@pytest.mark.parametrize("component", ["c1", "c2", "c3", "c4"])
def test_a_runs_entries_go_under_its_components_phase(component: str) -> None:
    """The store files a queued run by this map, and the runner by the spec."""
    assert phase_category(component) == spec_for(component).audit_category


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

    async def test_queuing_and_continuing_a_deployment_run_are_filed_under_deployment(
        self, client
    ) -> None:
        """ "Queued a run" and "Continued a stopped run" still went under Design."""
        project_id = await _approved_tests(client)
        client.app.state.c4.fails.add("risk-assessment")
        started = await client.post(f"/projects/{project_id}/deployment/run")
        assert started.status_code == 200, started.text
        runs = (await client.get("/runs", params={"project": project_id})).json()
        run_id = next(run["id"] for run in runs if run["component"] == "c4")
        await _advance(client, run_id)
        client.app.state.c4.fails.clear()

        continued = await client.post(f"/runs/{run_id}/continue")
        assert continued.status_code == 200, continued.text

        entries = (await client.get("/activity", params={"project": project_id})).json()
        queued = next(
            entry
            for entry in entries
            if entry["title"] == "Queued a run" and entry["description"].startswith("Deployment")
        )
        assert queued["category"] == "deployment"
        again = next(entry for entry in entries if entry["title"] == "Continued a stopped run")
        assert again["category"] == "deployment"
