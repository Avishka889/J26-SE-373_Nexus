"""One run at a time on each phase of a project.

A second click on Try again started a second run of the stage, each paying for
its own model calls, because no retry route asked whether a run was already
working. Where a route did ask, the question and the new run were separate
statements: two requests that arrived together both found nothing in flight and
both started one. And a Code Generation retry on an approved version rewrote the
version's files before the store refused its artefact, so the approved code was
no longer the code that had been approved.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator

import httpx
import pytest
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.main import create_app, lifespan_for_tests

from .conftest import needs_db
from .test_code_routes import _advance_all, _generated
from .test_code_routes import _project as _designed
from .test_deployment_routes import _approved_tests, _deploy_run
from .test_testing_routes import _advance, _through_code

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


async def _runs(client: httpx.AsyncClient, project_id: str) -> int:
    return len((await client.get("/runs", params={"project": project_id})).json())


async def _twice(client: httpx.AsyncClient, path: str) -> tuple[httpx.Response, httpx.Response]:
    return await client.post(path), await client.post(path)


async def _testing_at_its_review(client: httpx.AsyncClient) -> str:
    project_id = await _through_code(client)
    started = await client.post(f"/projects/{project_id}/testing/run")
    assert started.status_code == 200, started.text
    runs = (await client.get("/runs", params={"project": project_id})).json()
    await _advance(client, runs[0]["id"])
    return project_id


class TestASecondRetryWhileTheFirstIsWorking:
    async def test_design(self, client) -> None:
        project_id = await _designed(client, approve=False)
        before = await _runs(client, project_id)

        first, second = await _twice(
            client, f"/projects/{project_id}/design/stages/wireframes/retry"
        )

        assert first.status_code == 200, first.text
        assert second.status_code == 409
        assert "already" in second.json()["error"]
        assert await _runs(client, project_id) == before + 1

    async def test_code(self, client) -> None:
        project_id, _ = await _generated(client)
        before = await _runs(client, project_id)

        first, second = await _twice(client, f"/projects/{project_id}/code/stages/tech-stack/retry")

        assert first.status_code == 200, first.text
        assert second.status_code == 409
        assert "already" in second.json()["error"]
        assert await _runs(client, project_id) == before + 1

    async def test_testing(self, client) -> None:
        project_id = await _testing_at_its_review(client)
        before = await _runs(client, project_id)

        first, second = await _twice(
            client, f"/projects/{project_id}/testing/stages/security-scan/retry"
        )

        assert first.status_code == 200, first.text
        assert second.status_code == 409
        assert "already" in second.json()["error"]
        assert await _runs(client, project_id) == before + 1

    async def test_deployment(self, client) -> None:
        project_id = await _approved_tests(client)
        await _deploy_run(client, project_id)
        before = await _runs(client, project_id)

        first, second = await _twice(
            client, f"/projects/{project_id}/deployment/stages/risk-assessment/retry"
        )

        assert first.status_code == 200, first.text
        assert second.status_code == 409
        assert "already" in second.json()["error"]
        assert await _runs(client, project_id) == before + 1

    async def test_once_it_has_finished_the_stage_can_be_retried_again(self, client) -> None:
        project_id, _ = await _generated(client)
        path = f"/projects/{project_id}/code/stages/tech-stack/retry"
        await client.post(path)
        await _advance_all(client, project_id)

        again = await client.post(path)

        assert again.status_code == 200, again.text


class TestTwoRequestsAtOnce:
    async def test_two_retries_start_one_run(self, client) -> None:
        project_id, _ = await _generated(client)
        before = await _runs(client, project_id)
        path = f"/projects/{project_id}/code/stages/tech-stack/retry"

        answers = await asyncio.gather(client.post(path), client.post(path))

        assert sorted(answer.status_code for answer in answers) == [200, 409]
        assert await _runs(client, project_id) == before + 1

    async def test_the_first_requirement_text_twice_starts_one_design_run(self, client) -> None:
        created = await client.post("/projects", json={"name": "Records", "description": ""})
        project_id = created.json()["id"]
        client.created_projects.append(project_id)
        text = {"requirementText": "Someone creates a record."}

        await asyncio.gather(
            client.patch(f"/projects/{project_id}", json=text),
            client.patch(f"/projects/{project_id}", json=text),
        )

        assert await _runs(client, project_id) == 1
        async with client.app.state.pool.connection() as conn:
            assert await store.current_version(conn, project_id) == 1


class TestAnApprovedCodeVersion:
    async def _approved(self, client) -> tuple[str, int]:
        project_id, snapshot = await _generated(client)
        decided = await client.post(
            f"/projects/{project_id}/code/decision", json={"kind": "approved", "by": "you"}
        )
        assert decided.status_code == 200, decided.text
        await _advance_all(client, project_id)
        return project_id, snapshot["codeVersion"]

    async def test_a_retry_is_refused_before_anything_is_rewritten(self, client) -> None:
        project_id, version = await self._approved(client)
        async with client.app.state.pool.connection() as conn:
            files = await store.code_files(conn, project_id, version=version)
        before = await _runs(client, project_id)

        answer = await client.post(f"/projects/{project_id}/code/stages/backend-code/retry")

        assert answer.status_code == 409
        assert "was approved" in answer.json()["error"]
        assert await _runs(client, project_id) == before
        async with client.app.state.pool.connection() as conn:
            assert await store.code_files(conn, project_id, version=version) == files

    async def test_the_store_keeps_its_code_and_still_takes_its_tests(self, client) -> None:
        """The last line before the rows: a run already past the route, such as a
        retry that was running when the review approved, cannot rewrite the code.
        The tests the testing phase generates against the approved version are
        still written to it, because that is where they belong."""
        project_id, version = await self._approved(client)

        async with client.app.state.pool.connection() as conn:
            with pytest.raises(store.VersionAlreadyApproved):
                await store.put_code_files(
                    conn,
                    project_id,
                    version=version,
                    stage_id="backend-code",
                    files={"apps/api/src/index.ts": "rewritten"},
                )
        async with client.app.state.pool.connection() as conn:
            await store.put_code_files(
                conn,
                project_id,
                version=version,
                stage_id=store.TEST_FILE_STAGE,
                files={"apps/api/test/records.test.ts": "test('records', () => {});"},
            )
            files = await store.code_files(
                conn, project_id, version=version, stage_id=store.TEST_FILE_STAGE
            )
        assert "apps/api/test/records.test.ts" in files


class TestStartingADesignRun:
    async def test_not_over_an_approved_design(self, client) -> None:
        project_id = await _designed(client)
        before = await _runs(client, project_id)

        answer = await client.post("/runs", json={"projectId": project_id, "component": "c1"})

        assert answer.status_code == 409
        assert "was approved" in answer.json()["error"]
        assert await _runs(client, project_id) == before
