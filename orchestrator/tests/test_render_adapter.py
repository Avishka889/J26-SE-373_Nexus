"""The backend on Render, deployed by the orchestrator, against a fake Render API and origin.

What is proved is the step as the saga runs it: the commit is deployed by id,
followed until Render says it is live, and done only once the backend serves the
candidate's fingerprint. A deploy that ends before going live says it moved
nothing, so the release is undone rather than left for a rollback; a failure
after that is a person's. The key never appears in what a failure says.
"""

import json
import uuid
from datetime import UTC, datetime

import httpx
import pytest
from orchestrator.crypto import encrypt
from orchestrator.db import store
from orchestrator.deploy.adapters.render import RenderDeploys
from orchestrator.saga.executor import Plan, StepContext, StepFailed
from sdlc_contracts import (
    CloudResources,
    DeployStep,
    RenderService,
    VercelProject,
    VerifiedRelease,
)

from .conftest import DATABASE_URL, needs_db, refuse_the_developers_store

pytestmark = needs_db

SECRET_KEY = "a test secret with enough entropy to stand in for a real one"
OWNER = "u_test_render_deploys"
KEY = "rnd_not_a_real_key_for_deploys_1e2f"
ORIGIN = "https://tt-api.onrender.com"
COMMIT, CANDIDATE, OLD = "2" * 40, "c" * 64, "a" * 64
NOW = datetime(2026, 9, 29, tzinfo=UTC)


class FakeRender:
    """Render's deploys for one service, and the backend's address serving a fingerprint."""

    def __init__(self, statuses: list[str], *, serves: list[str] | None = None) -> None:
        self.statuses = statuses
        self.serves = serves or [CANDIDATE]
        self.requests: list[tuple[str, str, object]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        method, url = request.method, str(request.url)
        self.requests.append((method, url, body))
        if url == f"{ORIGIN}/release.json":
            served = self.serves.pop(0) if len(self.serves) > 1 else self.serves[0]
            return httpx.Response(200, json={"candidateHash": served})
        if method == "POST" and url.endswith("/services/srv-1/deploys"):
            return httpx.Response(201, json={"id": "dep-1", "status": "created"})
        if method == "GET" and url.endswith("/services/srv-1/deploys/dep-1"):
            status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
            return httpx.Response(200, json={"id": "dep-1", "status": status})
        return httpx.Response(404, json={"message": f"{method} {url} is not faked"})


@pytest.fixture
async def pool(settings):
    from orchestrator.db.pool import create_app_pool

    pool = create_app_pool(DATABASE_URL, max_size=2)
    await pool.open(wait=True)
    try:
        yield pool
    finally:
        await pool.close()


@pytest.fixture
async def project(pool):
    owner = refuse_the_developers_store(OWNER)
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO app.users (id, email, name) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (owner, "render-deploys-test@example.invalid", "Render deploys test"),
        )
        row = await store.create_project(conn, name="Render deploys case", owner_id=owner)
        await store.put_secret(conn, f"{owner}:render", encrypt(SECRET_KEY, KEY))
        made = CloudResources(
            vercel=VercelProject(
                project_id="prj_1", org_id="team_1", name="tt", origin="https://tt.vercel.app"
            ),
            render=RenderService(service_id="srv-1", name="tt-api", origin=ORIGIN, owner_id="t"),
            created_at=NOW,
        )
        await store.put_settings_section(
            conn, owner, ("cloud", row["id"]), made.model_dump(by_alias=True, mode="json")
        )
    try:
        yield row["id"]
    finally:
        async with pool.connection() as conn:
            await store.delete_project(conn, row["id"], owner_id=owner)
            await store.delete_secret(conn, f"{owner}:render")
            body = await store.settings_body(conn, owner)
            body.pop("cloud", None)
            await store.put_settings_body(conn, owner, body)
            await conn.execute("DELETE FROM app.users WHERE id = %s", (owner,))


def _context(project_id: str, step_id: str, *, previous: VerifiedRelease | None = None):
    step = DeployStep(
        id=step_id,
        label=step_id,
        provider="render",
        compensation="a person decides",
        moves_traffic=True,
    )
    return StepContext(
        deployment={
            "id": uuid.uuid4(),
            "project_id": project_id,
            "candidate_hash": CANDIDATE,
            "kind": "release" if step_id == "backend" else "rollback",
        },
        plan=Plan("plan-1", [step]),
        step=step,
        seq=1,
        key="k",
        candidate=None,
        previous=previous,
        earlier={"commit": {"commit": COMMIT}},
    )


async def _execute(pool, ctx, render: FakeRender, **timeouts):
    client = httpx.AsyncClient(transport=httpx.MockTransport(render.handle))

    async def instant(seconds):
        return None

    try:
        adapter = RenderDeploys(
            pool=pool,
            secret_key=SECRET_KEY,
            client=client,
            poll_seconds=0,
            sleep=instant,
            deploy_timeout=timeouts.get("deploy", 5),
            fingerprint_timeout=timeouts.get("fingerprint", 5),
        )
        return await adapter.execute(ctx)
    finally:
        await client.aclose()


class TestARelease:
    async def test_it_deploys_the_commit_and_waits_for_the_fingerprint(self, pool, project) -> None:
        render = FakeRender(
            ["build_in_progress", "update_in_progress", "live"], serves=[OLD, CANDIDATE]
        )
        result = await _execute(pool, _context(project, "backend"), render)

        [(_, url, body)] = [r for r in render.requests if r[0] == "POST"]
        assert url.endswith("/services/srv-1/deploys") and body == {"commitId": COMMIT}
        assert result.resource == {"service": "srv-1", "deploy": "dep-1", "commit": COMMIT}
        served = [r for r in render.requests if r[1] == f"{ORIGIN}/release.json"]
        assert len(served) == 2, "done only once the backend serves the candidate"

    async def test_a_build_that_fails_says_it_moved_nothing(self, pool, project) -> None:
        with pytest.raises(StepFailed) as failed:
            await _execute(pool, _context(project, "backend"), FakeRender(["build_failed"]))
        assert failed.value.moved is False
        assert "the previous deploy still serves" in str(failed.value)

    async def test_a_failure_after_going_live_is_left_for_a_person(self, pool, project) -> None:
        with pytest.raises(StepFailed) as failed:
            await _execute(pool, _context(project, "backend"), FakeRender(["update_failed"]))
        assert failed.value.moved is None

    async def test_live_but_not_serving_the_candidate_is_not_done(self, pool, project) -> None:
        render = FakeRender(["live"], serves=[OLD])
        with pytest.raises(StepFailed, match="did not serve candidate"):
            await _execute(pool, _context(project, "backend"), render, fingerprint=0.05)


class TestARollback:
    async def test_it_deploys_the_verified_commit(self, pool, project) -> None:
        previous = VerifiedRelease(
            deployment_id="d-0",
            deploy_version=1,
            candidate_hash=OLD,
            target="cloud",
            commit_sha="3" * 40,
            verified_at=NOW,
        )
        render = FakeRender(["live"], serves=[OLD])
        await _execute(pool, _context(project, "restore-backend", previous=previous), render)
        [(_, _, body)] = [r for r in render.requests if r[0] == "POST"]
        assert body == {"commitId": "3" * 40}


class TestWhatAFailureSays:
    async def test_the_key_never_appears(self, pool, project) -> None:
        def echoing(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text=f"bad key {KEY}")

        client = httpx.AsyncClient(transport=httpx.MockTransport(echoing))
        try:
            adapter = RenderDeploys(pool=pool, secret_key=SECRET_KEY, client=client)
            with pytest.raises(StepFailed) as failed:
                await adapter.execute(_context(project, "backend"))
        finally:
            await client.aclose()
        assert KEY not in str(failed.value) and "401" in str(failed.value)
