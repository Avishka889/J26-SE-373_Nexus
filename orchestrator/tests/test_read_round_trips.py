"""A read pays for as few database round trips as it can.

Neon answers about 0.2 s after each round trip from where this is used, so a
round trip is the unit a page waits in. Every request paid three before its
first query (the connection check, BEGIN and COMMIT), and a snapshot made up to
twenty eight sequential reads: a deployment page took thirteen seconds.
"""

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from orchestrator.api import deps
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.main import create_app, lifespan_for_tests

from .conftest import needs_db

pytestmark = needs_db


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[Any]:
    app = create_app(settings, lifespan_factory=lifespan_for_tests)
    async with app.router.lifespan_context(app):
        yield app


async def _connection_for(app: Any, method: str) -> tuple[Any, Any]:
    requests = deps.db(SimpleNamespace(method=method, app=app))  # type: ignore[arg-type]
    return requests, await requests.__anext__()


class TestARead:
    async def test_runs_without_a_transaction(self, app) -> None:
        """No BEGIN and no COMMIT: two of the three round trips every request paid
        before its first query, and a read has nothing to commit."""
        requests, conn = await _connection_for(app, "GET")

        assert conn.autocommit is True
        await requests.aclose()
        assert conn.autocommit is False, "the pool gets the connection back as it lent it"

    async def test_a_write_keeps_its_transaction(self, app) -> None:
        """A change and its audit entry are written together or not at all."""
        requests, conn = await _connection_for(app, "POST")

        assert conn.autocommit is False
        await requests.aclose()


class Statements:
    """Every statement sent through any cursor, counted, for a while."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import psycopg

        self.count = 0
        original = psycopg.AsyncCursor.execute

        async def counted(cursor: Any, query: Any, params: Any = None, **kwargs: Any) -> Any:
            self.count += 1
            return await original(cursor, query, params, **kwargs)

        monkeypatch.setattr(psycopg.AsyncCursor, "execute", counted)


async def _project(app: Any) -> str:
    async with app.state.pool.connection() as conn:
        project = await store.create_project(conn, name="Round trips", owner_id=DEV_OWNER_ID)
    return str(project["id"])


class TestTheReadsOfOneRequest:
    async def test_a_read_asked_twice_is_answered_once(self, app, monkeypatch) -> None:
        project_id = await _project(app)
        try:
            requests, conn = await _connection_for(app, "GET")
            sent = Statements(monkeypatch)

            first = await store.overlays(conn, project_id)
            again = await store.overlays(conn, project_id)

            assert first == again
            assert sent.count == 1
            await requests.aclose()
        finally:
            async with app.state.pool.connection() as conn:
                await store.delete_project(conn, project_id, owner_id=DEV_OWNER_ID)

    async def test_prefetched_reads_share_one_round_trip(self, app, monkeypatch) -> None:
        project_id = await _project(app)
        try:
            requests, conn = await _connection_for(app, "GET")
            sent = Statements(monkeypatch)

            await store.prefetch(
                conn,
                store.stage_states_query(project_id),
                store.thread_query(project_id),
                store.overlays_query(project_id),
            )
            stages = await store.stage_states(conn, project_id)
            await store.thread(conn, project_id)
            await store.overlays(conn, project_id)

            assert sent.count == 1
            assert {row["stage_id"] for row in stages}, "the batch answered with real rows"
            await requests.aclose()
        finally:
            async with app.state.pool.connection() as conn:
                await store.delete_project(conn, project_id, owner_id=DEV_OWNER_ID)

    async def test_a_request_that_writes_reads_fresh(self, app, monkeypatch) -> None:
        """A write may change what an earlier read answered, in its own transaction."""
        project_id = await _project(app)
        try:
            requests, conn = await _connection_for(app, "POST")
            sent = Statements(monkeypatch)

            await store.prefetch(conn, store.overlays_query(project_id))
            await store.overlays(conn, project_id)
            await store.overlays(conn, project_id)

            assert sent.count == 2
            await requests.aclose()
        finally:
            async with app.state.pool.connection() as conn:
                await store.delete_project(conn, project_id, owner_id=DEV_OWNER_ID)

    async def test_an_answer_cannot_be_changed_by_whoever_reads_it(self, app) -> None:
        project_id = await _project(app)
        try:
            requests, conn = await _connection_for(app, "GET")

            stages = await store.stage_states(conn, project_id)
            stages.clear()

            assert await store.stage_states(conn, project_id), "the cache was emptied by a reader"
            await requests.aclose()
        finally:
            async with app.state.pool.connection() as conn:
                await store.delete_project(conn, project_id, owner_id=DEV_OWNER_ID)


@pytest.fixture
async def client(app) -> AsyncIterator[Any]:
    import httpx

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        c.app = app  # type: ignore[attr-defined]
        c.created_projects = []  # type: ignore[attr-defined]
        try:
            yield c
        finally:
            async with app.state.pool.connection() as conn:
                for project_id in c.created_projects:  # type: ignore[attr-defined]
                    await store.delete_project(conn, project_id, owner_id=DEV_OWNER_ID)


async def _asked(client: Any, monkeypatch: pytest.MonkeyPatch, path: str) -> int:
    """How many statements one read sent: each one a round trip to the database."""
    sent = Statements(monkeypatch)
    answer = await client.get(path)
    assert answer.status_code == 200, answer.text
    return sent.count


class TestAPageReadsInAFewRoundTrips:
    """Measured at 100 ms per round trip before and after: the deployment page went
    from 31 round trips to 4, the code page from 19 to 3, the design page from 12
    to 2, and the list from 8 to 2. Each count is the connection check plus one
    batch per step the reads depend on; a read model that starts asking one by
    one again fails here, not on a slow page."""

    async def test_the_list_and_the_bell(self, client, monkeypatch) -> None:
        from .test_spine import _advance, _start

        project_id, run_id = await _start(client)
        await _advance(client, run_id)

        assert await _asked(client, monkeypatch, "/projects") <= 2
        assert await _asked(client, monkeypatch, f"/projects/{project_id}") <= 2
        assert await _asked(client, monkeypatch, "/attention") <= 2

    async def test_the_design_review(self, client, monkeypatch) -> None:
        from .test_spine import _advance, _start

        project_id, run_id = await _start(client)
        await _advance(client, run_id)

        assert await _asked(client, monkeypatch, f"/projects/{project_id}/design") <= 2

    async def test_the_code_and_testing_reviews(self, client, monkeypatch) -> None:
        from .test_deployment_routes import _approved_tests

        project_id = await _approved_tests(client)

        assert await _asked(client, monkeypatch, f"/projects/{project_id}/code") <= 3
        assert await _asked(client, monkeypatch, f"/projects/{project_id}/testing") <= 3

    async def test_the_deployment_review(self, client, monkeypatch) -> None:
        from .test_deployment_routes import _approved_tests, _deploy_run

        project_id = await _approved_tests(client)
        await _deploy_run(client, project_id)

        assert await _asked(client, monkeypatch, f"/projects/{project_id}/deployment") <= 4


class TestAChangeAnswersInAFewRoundTrips:
    """A change answers with the whole snapshot, composed after its writes. It read
    one query at a time: choosing a deployment's target sent 32 statements, six
    seconds at Neon for one click."""

    async def test_choosing_the_release_target(self, client, monkeypatch) -> None:
        from .test_deployment_routes import _approved_tests, _deploy_run

        project_id = await _approved_tests(client)
        await _deploy_run(client, project_id)
        sent = Statements(monkeypatch)

        answer = await client.post(
            f"/projects/{project_id}/deployment/target", json={"target": "local", "by": "you"}
        )

        assert answer.status_code == 200, answer.text
        assert answer.json()["releaseTarget"] == "local", "the snapshot sees its own write"
        assert sent.count <= 12
