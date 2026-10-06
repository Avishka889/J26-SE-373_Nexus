# ruff: noqa: F811 - `client` is the deployment routes' fixture, imported to be used by name
"""The loop closes (M5): what production taught, sent by a person, is in C1's next run.

A verified release is watched by the supervisor with a scripted prober, and C4
(the canned one, which answers from what the window found) suggests what the
window implies for requirements. A person sends the suggestion, and it takes the
path a person's own design change takes: a new design version with the
suggestion as its note, and a run at that version whose input holds it. The
canned C1 turns each line of its input into a requirement, so the requirement
C1 produced is the proof the suggestion reached it.
"""

from orchestrator.db import store
from orchestrator.deploy.supervisor import MonitorSupervisor
from sdlc_contracts import FeedbackReport

from .conftest import needs_db
from .test_deployment_routes import client  # noqa: F401
from .test_monitoring import Release, _verified_release, instant
from .test_testing_spine import _advance

pytestmark = needs_db


def _supervisor(client, release: Release) -> MonitorSupervisor:
    return MonitorSupervisor(
        pool=client.app.state.pool,
        rounds=3,
        interval=1,
        c4=client.app.state.c4,
        prober=release,
        sleep=instant,
    )


async def _watched(client, release: Release) -> tuple[str, dict]:
    """A verified release, watched for one window: the project and its snapshot after."""
    project_id, deployment_id = await _verified_release(client)
    monitor = _supervisor(client, release)
    assert monitor.open(deployment_id)
    await monitor.wait()
    return project_id, (await client.get(f"/projects/{project_id}/deployment")).json()


async def _two_suggestions(client) -> tuple[str, list[dict]]:
    """A watched release whose feedback holds two suggestions, as a degraded window's can."""
    project_id, _ = await _watched(client, Release(failing={0, 1, 2}))
    async with client.app.state.pool.connection() as conn:
        found = await store.newest_artefact(conn, project_id, "feedback")
        report = FeedbackReport.model_validate(found["body"])
        [first] = report.items
        second = first.model_copy(
            update={
                "id": "fb-slow-tasks",
                "summary": "GET /tasks was slow on deploy version 1.",
                "evidence_ref": "monitoring-report@1#slow:GET /tasks",
                "suggested_requirement": "GET /tasks shall answer within 2 s at the 95th percentile.",
            }
        )
        await store.put_artefact(
            conn,
            project_id=project_id,
            kind="feedback",
            version=int(found["version"]),
            body=report.model_copy(update={"items": [first, second]}).model_dump(
                by_alias=True, mode="json"
            ),
        )
    snapshot = (await client.get(f"/projects/{project_id}/deployment")).json()
    return project_id, snapshot["feedback"]["items"]


async def _design_runs(conn, project_id: str) -> int:
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT count(*) FROM app.runs WHERE project_id = %s AND component = 'c1'",
            (project_id,),
        )
        (count,) = await cur.fetchone()
    return count


def _decide(client, project_id: str, item_id: str, **body):
    return client.post(
        f"/projects/{project_id}/deployment/feedback/{item_id}/decision",
        json={"by": "you", **body},
    )


class TestWhatAWindowSuggests:
    async def test_a_release_found_down_suggests_a_requirement(self, client) -> None:
        _, snapshot = await _watched(client, Release(failing={0, 1, 2}))

        [item] = snapshot["feedback"]["items"]
        assert item["evidenceRef"] == "monitoring-report@1#down"
        assert any(
            "suggests 1 requirement change(s)" in message["content"]
            for message in snapshot["thread"]
        )
        assert snapshot["feedbackDecisions"] == []

    async def test_a_healthy_window_suggests_nothing(self, client) -> None:
        _, snapshot = await _watched(client, Release())

        assert snapshot["feedback"]["items"] == []
        assert not any("suggests" in message["content"] for message in snapshot["thread"])


class TestSendingIt:
    async def test_a_sent_suggestion_is_in_the_next_design_runs_input(self, client) -> None:
        project_id, snapshot = await _watched(client, Release(failing={0, 1, 2}))
        [item] = snapshot["feedback"]["items"]
        pool = client.app.state.pool
        async with pool.connection() as conn:
            before = await store.current_version(conn, project_id)

        answer = await _decide(client, project_id, item["id"], decision="sent")

        assert answer.status_code == 200, answer.text
        async with pool.connection() as conn:
            version = await store.current_version(conn, project_id)
            run = await store.latest_run(conn, project_id, component="c1")
        assert version == before + 1 and run["requirements_version"] == version
        await _advance(client, run["id"])
        async with pool.connection() as conn:
            found = await store.artefacts_at(
                conn, project_id, version=version, kinds=("requirements",)
            )
        texts = [entry["text"] for entry in found["requirements"]["body"]["requirements"]]
        assert any(text.startswith(item["suggestedRequirement"]) for text in texts), texts
        [decision] = answer.json()["feedbackDecisions"]
        assert (decision["itemId"], decision["decision"], decision["designVersion"]) == (
            item["id"],
            "sent",
            version,
        )

    async def test_several_sent_together_are_one_design_version_and_one_run(self, client) -> None:
        """One at a time, each suggestion opened a design version and a run of
        Requirements and Design of its own."""
        project_id, items = await _two_suggestions(client)
        pool = client.app.state.pool
        async with pool.connection() as conn:
            before = await store.current_version(conn, project_id)
            runs_before = await _design_runs(conn, project_id)

        answer = await client.post(
            f"/projects/{project_id}/deployment/feedback/send",
            json={"itemIds": [one["id"] for one in items]},
        )

        assert answer.status_code == 200, answer.text
        async with pool.connection() as conn:
            assert await store.current_version(conn, project_id) == before + 1
            assert await _design_runs(conn, project_id) == runs_before + 1
            note = (await store.applied_notes(conn, project_id, before + 1))[-1]
        assert all(one["suggestedRequirement"] in note for one in items), note
        decisions = answer.json()["feedbackDecisions"]
        assert {one["itemId"] for one in decisions} == {one["id"] for one in items}
        assert {one["designVersion"] for one in decisions} == {before + 1}

    async def test_a_batch_with_a_decided_suggestion_sends_none_of_it(self, client) -> None:
        project_id, items = await _two_suggestions(client)
        await _decide(client, project_id, items[0]["id"], decision="dismissed", note="planned")
        pool = client.app.state.pool
        async with pool.connection() as conn:
            before = await store.current_version(conn, project_id)

        answer = await client.post(
            f"/projects/{project_id}/deployment/feedback/send",
            json={"itemIds": [one["id"] for one in items]},
        )

        assert answer.status_code == 409 and "was dismissed already" in answer.text
        async with pool.connection() as conn:
            assert await store.current_version(conn, project_id) == before

    async def test_a_suggestion_is_sent_once(self, client) -> None:
        project_id, snapshot = await _watched(client, Release(failing={0, 1, 2}))
        [item] = snapshot["feedback"]["items"]
        await _decide(client, project_id, item["id"], decision="sent")

        again = await _decide(client, project_id, item["id"], decision="sent")

        assert again.status_code == 409
        assert "was sent already, as design version" in again.text

    async def test_dismissing_needs_a_note_and_opens_no_design_version(self, client) -> None:
        project_id, snapshot = await _watched(client, Release(failing={0, 1, 2}))
        [item] = snapshot["feedback"]["items"]
        pool = client.app.state.pool
        async with pool.connection() as conn:
            before = await store.current_version(conn, project_id)

        bare = await _decide(client, project_id, item["id"], decision="dismissed")
        noted = await _decide(
            client, project_id, item["id"], decision="dismissed", note="a planned outage"
        )

        assert bare.status_code == 409 and "needs a note" in bare.text
        assert noted.status_code == 200, noted.text
        async with pool.connection() as conn:
            assert await store.current_version(conn, project_id) == before
        [decision] = noted.json()["feedbackDecisions"]
        assert decision["designVersion"] is None and decision["note"] == "a planned outage"

    async def test_an_item_that_does_not_exist_is_not_found(self, client) -> None:
        project_id, _ = await _watched(client, Release(failing={0, 1, 2}))
        answer = await _decide(client, project_id, "fb-nothing", decision="sent")
        assert answer.status_code == 404

    async def test_there_is_nothing_to_decide_before_any_window(self, client) -> None:
        project_id, _ = await _verified_release(client)
        answer = await _decide(client, project_id, "fb-canned-down", decision="sent")
        assert answer.status_code == 409 and "no feedback" in answer.text
