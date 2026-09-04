"""A project is created in one request, with the text that starts its design.

It was a POST and then a PATCH carrying the requirement text: a PATCH that
failed left a project with no requirements in the list, which the reader's
retry then duplicated.
"""

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.main import create_app, lifespan_for_tests

from .conftest import needs_db

pytestmark = needs_db


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings, lifespan_factory=lifespan_for_tests)
    async with app.router.lifespan_context(app):
        # An unexpected error answers 500 to the browser and is raised on for
        # the server's log; this client reads the answer.
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            c.app = app  # type: ignore[attr-defined]
            try:
                yield c
            finally:
                async with app.state.pool.connection() as conn:
                    for project in await store.list_projects(conn, owner_id=DEV_OWNER_ID):
                        if project["name"].startswith("One request "):
                            await store.delete_project(conn, project["id"], owner_id=DEV_OWNER_ID)


async def _named(client: httpx.AsyncClient, name: str) -> list[dict]:
    return [p for p in (await client.get("/projects")).json() if p["name"] == name]


class TestCreatingAProject:
    async def test_the_text_on_the_create_starts_the_design(
        self, client: httpx.AsyncClient
    ) -> None:
        answer = await client.post(
            "/projects",
            json={
                "name": "One request ledger",
                "description": "Books",
                "requirementText": "Track the books.",
                "files": ["brief.md"],
            },
        )

        assert answer.status_code == 201, answer.text
        project = answer.json()
        assert project["requirementText"] == "Track the books."
        assert project["files"] == ["brief.md"]
        runs = (await client.get("/runs", params={"project": project["id"]})).json()
        assert len(runs) == 1

    async def test_a_create_that_fails_leaves_no_project_behind(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def broken(*args, **kwargs):
            raise RuntimeError("the run could not be queued")

        monkeypatch.setattr(store, "create_run", broken)

        answer = await client.post(
            "/projects", json={"name": "One request orphan", "requirementText": "Track the books."}
        )

        assert answer.status_code == 500
        assert await _named(client, "One request orphan") == []

    async def test_a_create_with_no_text_starts_nothing(self, client: httpx.AsyncClient) -> None:
        answer = await client.post("/projects", json={"name": "One request draft"})

        assert answer.status_code == 201, answer.text
        runs = (await client.get("/runs", params={"project": answer.json()["id"]})).json()
        assert runs == []


class TestDeletingAProject:
    """Delete removed a project's whole audit trail with it, and did not check
    for a run or a release still going."""

    async def test_it_is_refused_while_a_run_is_going(self, client: httpx.AsyncClient) -> None:
        created = await client.post(
            "/projects", json={"name": "One request busy", "requirementText": "Track the books."}
        )
        project_id = created.json()["id"]

        answer = await client.delete(f"/projects/{project_id}")

        assert answer.status_code == 409
        assert "Requirements and Design run is in progress" in answer.json()["error"]
        assert await _named(client, "One request busy") != []

    async def test_its_record_outlives_it(self, client: httpx.AsyncClient) -> None:
        created = await client.post(
            "/projects", json={"name": "One request gone", "requirementText": "Track the books."}
        )
        project_id = created.json()["id"]
        supervisor = client.app.state.supervisor  # type: ignore[attr-defined]
        run = (await client.get("/runs", params={"project": project_id})).json()[0]
        await supervisor.advance(uuid.UUID(run["id"]))  # to its review, where it waits

        answer = await client.delete(f"/projects/{project_id}")

        assert answer.status_code == 204, answer.text
        assert await _named(client, "One request gone") == []
        trail = (await client.get("/audit")).json()
        deleted = next(e for e in trail if e["action"] == "Deleted a project")
        assert deleted["target"] == "One request gone"
        assert "GitHub repository" in deleted["detail"]
        # What was done before it, kept.
        assert any(e["action"] == "Queued a run" and e["target"] == run["id"] for e in trail)

    async def test_its_containers_on_this_machine_go_with_it(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A deleted project's release kept its port from every project after it."""
        from orchestrator.deploy.adapters import local_docker

        asked: list[list[str]] = []

        async def scripted(args: list[str], **_: object) -> tuple[int, str]:
            asked.append(args)
            return (0, "c00000000001\nc00000000002") if args[0] == "ps" else (0, args[-1])

        monkeypatch.setattr(local_docker, "docker", scripted)
        created = await client.post("/projects", json={"name": "One request released"})
        project_id = created.json()["id"]

        answer = await client.delete(f"/projects/{project_id}")

        assert answer.status_code == 204, answer.text
        assert asked == [
            ["ps", "-aq", "--filter", f"label=sdlc.c4.project={project_id}"],
            ["rm", "-f", "c00000000001"],
            ["rm", "-f", "c00000000002"],
        ]


class TestStartingADesignThatNeverStarted:
    async def test_text_sent_to_a_project_that_never_started_starts_its_design(
        self, client: httpx.AsyncClient
    ) -> None:
        """The start screen's submit sent text to a project that already had some,
        so text never went from empty to written: the brief was replaced and no run
        started. A project with no design version yet starts one."""
        created = await client.post("/projects", json={"name": "One request unstarted"})
        project_id = created.json()["id"]
        async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
            await store.patch_project(conn, project_id, {"requirement_text": "An old brief."})

        answer = await client.patch(
            f"/projects/{project_id}", json={"requirementText": "Track the books."}
        )

        assert answer.status_code == 200, answer.text
        runs = (await client.get("/runs", params={"project": project_id})).json()
        assert len(runs) == 1
