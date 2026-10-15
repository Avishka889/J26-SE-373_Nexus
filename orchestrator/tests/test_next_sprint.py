"""Planning the next sprint: the build grows by a sprint at a time.

The code phase built the sprint plan's first sprint, and a backlog story could
only be moved in one at a time, each move a whole regeneration. Planning the
next sprint takes the next stories from the backlog, divided as the sprint
plan divides one, and generates once for all of them; the stories already in
the build stay in it.
"""

from collections.abc import AsyncIterator

import httpx
import pytest
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.main import create_app, lifespan_for_tests

from .conftest import needs_db
from .test_code_routes import _advance_all, _design_moved_on, _generated

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
                async with app.state.pool.connection() as conn:
                    for project_id in created:
                        await store.delete_project(conn, project_id, owner_id=DEV_OWNER_ID)


async def _with_backlog(client: httpx.AsyncClient) -> tuple[str, dict]:
    """A project whose sprint plan leaves four 8 point stories in the backlog,
    against a 20 point velocity, with its first sprint generated."""
    client.app.state.c1.backlog = 4  # type: ignore[attr-defined]
    return await _generated(client)


async def _code(client: httpx.AsyncClient, project_id: str) -> dict:
    return (await client.get(f"/projects/{project_id}/code")).json()


async def _plan_next(client: httpx.AsyncClient, project_id: str) -> httpx.Response:
    """Plan the next sprint the way a person can: once the build before it is approved."""
    approved = await client.post(
        f"/projects/{project_id}/code/decision", json={"kind": "approved", "note": ""}
    )
    assert approved.status_code == 200, approved.text
    await _advance_all(client, project_id)
    return await client.post(f"/projects/{project_id}/code/sprints/next", json={"supersede": True})


def _stories(snapshot: dict) -> dict[str, dict]:
    return {story["id"]: story for story in snapshot["scope"]["stories"]}


class TestTheNextSprint:
    async def test_the_page_shows_what_it_would_add_before_anyone_asks(self, client) -> None:
        _, snapshot = await _with_backlog(client)

        preview = snapshot["nextSprint"]
        assert preview["number"] == 2
        assert [story["id"] for story in preview["stories"]] == ["US-2", "US-3"]
        assert preview["points"] == 16 and preview["velocity"] == 20

    async def test_planning_it_adds_its_stories_and_generates_once(self, client) -> None:
        project_id, snapshot = await _with_backlog(client)
        scoped = client.app.state.c2.calls.count("sprint-scope")

        answer = await _plan_next(client, project_id)
        assert answer.status_code == 200, answer.text
        await _advance_all(client, project_id)

        after = await _code(client, project_id)
        assert after["codeVersion"] == snapshot["codeVersion"] + 1
        assert client.app.state.c2.calls.count("sprint-scope") == scoped + 1, "one generation"
        stories = _stories(after)
        assert stories["US-1"]["inScope"] and stories["US-1"]["sprint"] == 1, "sprint 1 stays"
        assert stories["US-2"]["inScope"] and stories["US-2"]["sprint"] == 2
        assert stories["US-3"]["inScope"] and stories["US-3"]["sprint"] == 2
        assert not stories["US-4"]["inScope"] and stories["US-4"]["sprint"] == 0
        assert after["scope"]["sprintName"] == "Sprints 1 and 2"
        assert after["nextSprint"]["number"] == 3
        assert [story["id"] for story in after["nextSprint"]["stories"]] == ["US-4", "US-5"]

    async def test_planning_is_on_the_record_and_in_the_conversation(self, client) -> None:
        project_id, _ = await _with_backlog(client)

        await _plan_next(client, project_id)

        entries = (await client.get("/audit", params={"project": project_id})).json()
        [planned] = [row for row in entries if row["action"] == "Planned the next sprint"]
        assert planned["target"] == "sprint 2"
        thread = (await _code(client, project_id))["thread"]
        assert any(
            "Planned sprint 2: US-2, US-3, 16 points" in message["content"] for message in thread
        )

    async def test_with_every_story_in_the_build_there_is_nothing_to_plan(self, client) -> None:
        project_id, snapshot = await _generated(client)
        assert snapshot["nextSprint"]["stories"] == []

        answer = await client.post(f"/projects/{project_id}/code/sprints/next", json={})

        assert answer.status_code == 409
        assert "every story in the sprint plan is in the build already" in answer.text

    async def test_over_approved_code_it_asks_first_and_records_nothing(self, client) -> None:
        project_id, _ = await _with_backlog(client)
        await client.post(
            f"/projects/{project_id}/code/decision", json={"kind": "approved", "by": "you"}
        )
        await _advance_all(client, project_id)

        async def choices() -> list[tuple]:
            async with client.app.state.pool.connection() as conn:
                rows = await store.overlays(conn, project_id)
            return [
                (row["target_id"], row["version"], row["value"])
                for row in rows
                if row["kind"] == "story_scope"
            ]

        # Approving recorded what the build covers; refusing must change none of it.
        before = await choices()
        refused = await client.post(f"/projects/{project_id}/code/sprints/next", json={})

        assert refused.status_code == 409
        assert refused.json()["detail"]["supersede"] == "required"
        assert await choices() == before, "a refusal kept a choice"

        confirmed = await client.post(
            f"/projects/{project_id}/code/sprints/next", json={"supersede": True}
        )
        assert confirmed.status_code == 200, confirmed.text
        await _advance_all(client, project_id)
        assert _stories(await _code(client, project_id))["US-2"]["sprint"] == 2

    async def test_a_story_moved_in_on_its_own_joins_the_newest_sprint(self, client) -> None:
        project_id, _ = await _with_backlog(client)
        await _plan_next(client, project_id)
        await _advance_all(client, project_id)

        moved = await client.post(f"/projects/{project_id}/code/scope/US-5", json={"inScope": True})
        assert moved.status_code == 200, moved.text
        await _advance_all(client, project_id)

        stories = _stories(await _code(client, project_id))
        assert stories["US-5"]["inScope"] and stories["US-5"]["sprint"] == 2

    async def test_a_decision_stored_before_sprints_were_counted_is_the_first(self, client) -> None:
        project_id, _ = await _with_backlog(client)
        async with client.app.state.pool.connection() as conn:
            await store.put_overlay(
                conn,
                project_id=project_id,
                version=1,
                kind="story_scope",
                target_id="US-2",
                value=True,
                by="you",
            )

        await client.post(f"/projects/{project_id}/code/generate")
        await _advance_all(client, project_id)

        after = await _code(client, project_id)
        assert _stories(after)["US-2"]["sprint"] == 1
        assert after["nextSprint"]["number"] == 2
        assert [story["id"] for story in after["nextSprint"]["stories"]] == ["US-3", "US-4"]


class TestAnApprovedBuildKeepsItsStories:
    """C1-4: a story's place in the build was a default until somebody moved it.

    So a design regenerated after the code was approved, whose new plan put an
    already built story in the backlog, took that story out of the next build,
    and a backlog story the new plan proposed joined it unplanned. Approving the
    code makes what the build covers a decision, story by story.
    """

    async def _replanned_after_approval(self, client) -> tuple[str, dict]:
        project_id, _ = await _with_backlog(client)
        approved = await client.post(
            f"/projects/{project_id}/code/decision", json={"kind": "approved", "note": ""}
        )
        assert approved.status_code == 200, approved.text
        await _advance_all(client, project_id)

        client.app.state.c1.replanned = True  # type: ignore[attr-defined]
        await _design_moved_on(client, project_id)
        started = await client.post(
            f"/projects/{project_id}/code/generate", json={"supersede": True}
        )
        assert started.status_code == 200, started.text
        await _advance_all(client, project_id)
        return project_id, await _code(client, project_id)

    async def test_a_story_already_built_stays_in_its_sprint(self, client) -> None:
        _, after = await self._replanned_after_approval(client)
        stories = _stories(after)
        assert stories["US-1"]["inScope"] and stories["US-1"]["sprint"] == 1

    async def test_a_story_the_new_plan_proposes_waits_to_be_planned(self, client) -> None:
        _, after = await self._replanned_after_approval(client)
        assert not _stories(after)["US-2"]["inScope"]
        assert "US-2" in [story["id"] for story in after["nextSprint"]["stories"]]

    async def test_a_story_somebody_decided_keeps_that_decision(self, client) -> None:
        """Approving records only what nobody had decided: sprint 2's stories
        were planned, and that decision, with who made it, is the one kept."""
        project_id, _ = await _with_backlog(client)
        planned = await _plan_next(client, project_id)
        assert planned.status_code == 200, planned.text
        await _advance_all(client, project_id)
        approved = await client.post(
            f"/projects/{project_id}/code/decision", json={"kind": "approved", "note": ""}
        )
        assert approved.status_code == 200, approved.text

        async with client.app.state.pool.connection() as conn:
            rows = await store.overlays(conn, project_id)
        decisions = [row for row in rows if row["kind"] == "story_scope"]
        assert [row["target_id"] for row in decisions].count("US-2") == 1
        assert {row["target_id"] for row in decisions} >= {"US-1", "US-2", "US-3", "US-4"}


class TestTheNextSprintWaitsForTheReview:
    """C2-10: planning the next sprint while this build's review was open
    resolved the review as requested changes, against the new version, so the
    record said a person asked for changes they never asked for. The next
    sprint goes on top of a build that has been reviewed."""

    async def test_while_the_review_is_open_it_is_refused_and_decides_nothing(self, client) -> None:
        project_id, _ = await _with_backlog(client)

        refused = await client.post(
            f"/projects/{project_id}/code/sprints/next", json={"supersede": True}
        )

        assert refused.status_code == 409
        assert "the code review of version 1 is still open" in refused.json()["error"]
        async with client.app.state.pool.connection() as conn:
            gate = await store.pending_gate(conn, project_id=project_id, kind="c2-code-review")
            rows = await store.overlays(conn, project_id)
        assert gate is not None, "planning decided the review"
        assert not [row for row in rows if row["kind"] == "story_scope"]
        trail = (await client.get("/audit", params={"project": project_id})).json()
        assert not any(entry["action"] == "Requested code changes" for entry in trail)
