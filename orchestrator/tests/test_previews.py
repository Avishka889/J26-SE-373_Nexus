"""Running generated code, and the four things that keep it reasonable.

The environment allowlists are tested without a database or a process, because
they are the security property and a test of them should not be able to be
skipped for want of node. The rest needs both.
"""

import os
import shutil
import subprocess
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.main import create_app, lifespan_for_tests
from orchestrator.previews import (
    GLOBAL_CAP,
    PreviewRefused,
    _build_env,
    _server_env,
)

from .conftest import needs_db

#: Everything the platform holds that generated code must never see.
PLATFORM_SECRETS = (
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "GROQ_API_KEY",
    "OPENROUTER_API_KEY",
    "DATABASE_URL",
    "DATABASE_DIRECT_URL",
    "SECRET_KEY",
)


class TestTheEnvironmentTheChildGets:
    """No test here needs a database, because this is the property that must
    never be skipped."""

    def test_the_server_gets_four_variables_and_no_more(self) -> None:
        assert set(_server_env(4321)) == {"PATH", "HOST", "PORT", "NODE_ENV"}

    def test_the_server_is_told_to_bind_loopback(self) -> None:
        env = _server_env(4321)
        assert env["HOST"] == "127.0.0.1"
        assert env["PORT"] == "4321"

    def test_install_and_build_get_the_sandbox_allowlist(self) -> None:
        # HOME and the npm cache and nothing else: npm needs them, and a
        # preview that re-downloaded its dependencies every time would take
        # minutes rather than seconds.
        assert set(_build_env()) == {"PATH", "HOME", "CI", "npm_config_cache"}

    @pytest.mark.parametrize("secret", PLATFORM_SECRETS)
    def test_no_platform_secret_reaches_either_child(self, monkeypatch, secret) -> None:
        """Planted in this process, and absent from both children.

        The orchestrator holds provider keys, the database URL and the secret
        that encrypts stored tokens. A child that inherited `os.environ` would
        hand every one of them to code a language model wrote.
        """
        monkeypatch.setenv(secret, "planted-value-do-not-leak")
        for env in (_build_env(), _server_env(1)):
            assert secret not in env
            assert "planted-value-do-not-leak" not in "".join(env.values())


pytestmark_db = needs_db


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
                await app.state.previews.stop_all()
                async with app.state.pool.connection() as conn:
                    for project_id in created:
                        await store.delete_project(conn, project_id, owner_id=DEV_OWNER_ID)


async def _project(client: httpx.AsyncClient) -> str:
    created = await client.post("/projects", json={"name": "Preview case"})
    project_id = created.json()["id"]
    client.created_projects.append(project_id)  # type: ignore[attr-defined]
    return project_id


@needs_db
class TestWhatTheRouteRefuses:
    async def test_a_project_with_nothing_generated_is_refused(self, client) -> None:
        project_id = await _project(client)
        answer = await client.post(f"/projects/{project_id}/code/preview")
        assert answer.status_code == 409
        assert "nothing has been generated" in answer.text

    async def test_a_version_whose_build_failed_is_refused(self, client) -> None:
        """Previewing code that failed its own typecheck would be showing
        something that does not exist."""
        project_id = await _project(client)
        async with client.app.state.pool.connection() as conn:
            await store.put_artefact(
                conn,
                project_id=project_id,
                kind="code-repository",
                version=1,
                body={
                    "version": 1,
                    "manifest": [],
                    "build": {
                        "toolchain": "node",
                        "isolation": "a stub",
                        "steps": [
                            {"name": "install", "command": "npm i", "outcome": "passed"},
                            {"name": "typecheck", "command": "tsc", "outcome": "failed"},
                        ],
                    },
                    "repository": None,
                    "notPushedReason": None,
                },
            )
        answer = await client.post(f"/projects/{project_id}/code/preview")
        assert answer.status_code == 409
        assert "did not build" in answer.text

    async def test_a_version_a_fix_wrote_stands_on_the_build_of_the_version_it_patched(
        self, client
    ) -> None:
        """It was not built on its own, and its build report used to be the patched
        version's, copied. It no longer carries one, so the preview follows the fix
        back: here past the build check, to the supervisor, which has no files."""
        project_id = await _project(client)
        built = {
            "toolchain": "node",
            "isolation": "a stub",
            "steps": [{"name": "typecheck", "command": "tsc", "outcome": "passed"}],
        }
        async with client.app.state.pool.connection() as conn:
            for version, build in ((1, built), (2, None)):
                await store.put_artefact(
                    conn,
                    project_id=project_id,
                    kind="code-repository",
                    version=version,
                    body={"version": version, "manifest": [], "build": build},
                )
            await store.put_overlay(
                conn,
                project_id=project_id,
                version=1,
                kind="remediation_decision",
                target_id="fix-1",
                value={"decision": "accepted", "appliedCodeVersion": 2, "patchedCodeVersion": 1},
                by="you",
            )

        answer = await client.post(f"/projects/{project_id}/code/preview")

        assert answer.status_code == 409
        assert "did not build" not in answer.text
        assert "nothing has been generated" in answer.text

    async def test_nothing_running_reads_as_none_rather_than_an_error(self, client) -> None:
        project_id = await _project(client)
        answer = await client.get(f"/projects/{project_id}/code/preview")
        assert answer.status_code == 200
        assert answer.json() == {"status": "none"}


@needs_db
class TestTheCap:
    async def test_the_fourth_preview_is_refused_by_name_not_evicted(self, client) -> None:
        """Killing something a person is looking at, to make room, is the kind
        of quiet behaviour this codebase avoids everywhere else."""
        supervisor = client.app.state.previews
        projects = [await _project(client) for _ in range(GLOBAL_CAP + 1)]
        async with client.app.state.pool.connection() as conn:
            for index, project_id in enumerate(projects[:GLOBAL_CAP]):
                await store.put_preview(
                    conn,
                    project_id,
                    code_version=1,
                    port=40000 + index,
                    # Pid 0 means nothing to kill, which is what a test wants:
                    # the cap is arithmetic over rows, not over processes.
                    pid=0,
                    workdir="/tmp/does-not-exist",
                    status="running",
                )

        with pytest.raises(PreviewRefused) as refused:
            await supervisor.start(projects[-1], code_version=1, sources={"a": "b"})

        message = str(refused.value)
        assert f"{GLOBAL_CAP} previews are already running" in message
        # Named, so the reader knows which one to stop.
        for project_id in projects[:GLOBAL_CAP]:
            assert project_id in message

        # And none of them was stopped to make room.
        async with client.app.state.pool.connection() as conn:
            still = {row["project_id"] for row in await store.live_previews(conn)}
        assert set(projects[:GLOBAL_CAP]) <= still

    async def test_one_per_project_replaces_rather_than_adds(self, client) -> None:
        project_id = await _project(client)
        async with client.app.state.pool.connection() as conn:
            await store.put_preview(
                conn,
                project_id,
                code_version=1,
                port=40100,
                pid=0,
                workdir="/tmp/does-not-exist",
                status="running",
            )
            await store.put_preview(
                conn,
                project_id,
                code_version=2,
                port=40101,
                pid=0,
                workdir="/tmp/does-not-exist",
                status="running",
            )
            rows = [r for r in await store.live_previews(conn) if r["project_id"] == project_id]
        assert len(rows) == 1
        assert rows[0]["code_version"] == 2


@needs_db
class TestReaping:
    async def test_a_row_left_by_an_earlier_process_is_killed_not_adopted(self, client) -> None:
        """A row saying running at startup describes a server this orchestrator
        did not spawn and cannot supervise."""
        project_id = await _project(client)
        # A real child, in its own group, so the reaper has something to kill.
        child = subprocess.Popen(
            ["sleep", "300"], start_new_session=True, stdout=subprocess.DEVNULL
        )
        workdir = f"/tmp/c2-preview-test-{uuid.uuid4().hex[:8]}"
        os.makedirs(workdir, exist_ok=True)
        try:
            async with client.app.state.pool.connection() as conn:
                await store.put_preview(
                    conn,
                    project_id,
                    code_version=1,
                    port=40200,
                    pid=child.pid,
                    workdir=workdir,
                    status="running",
                )

            await client.app.state.previews.reap_orphans()

            assert child.poll() is not None, "the orphaned process is still running"
            assert not os.path.exists(workdir), "the orphaned tree was left behind"
            async with client.app.state.pool.connection() as conn:
                row = await store.get_preview(conn, project_id)
            assert row is not None and row["status"] == "stopped"
            assert "restarted" in (row["error"] or "")
        finally:
            if child.poll() is None:  # pragma: no cover - the reaper failed
                child.kill()
                child.wait(timeout=5)
            shutil.rmtree(workdir, ignore_errors=True)
