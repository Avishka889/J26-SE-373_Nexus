"""The design asks its questions before it builds the rest, and never blocks.

A run built every stage on the assumptions it stated, and applying the answers
then built every stage again as a new version: two whole designs, the first of
them reviewed and thrown away. Now a run whose analysis asks questions pauses
after Requirements Analysis. Continuing with the answers analyses the
requirements again with them, as the next version; continuing with the
assumptions builds the rest on what was assumed. One follow-up pause at most,
since a model can almost always find something more to ask.
"""

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.clients.canned import CannedC1
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.graph.runner import RunSupervisor
from orchestrator.main import create_app, lifespan_for_tests

from .conftest import needs_db

pytestmark = needs_db

QUESTIONS = ["Who uses the tracker?", "Where are the books kept?"]

#: The stages built after Requirements Analysis, which wait while it asks.
LATER = (
    "domain-model",
    "architecture-graph",
    "architecture-recommendation",
    "uml-diagrams",
    "wireframes",
    "sprint-plan",
)


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings, lifespan_factory=lifespan_for_tests)
    app.state.c1 = CannedC1(questions=list(QUESTIONS))
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


async def _advance(client: httpx.AsyncClient, run_id) -> None:
    supervisor: RunSupervisor = client.app.state.supervisor  # type: ignore[attr-defined]
    await supervisor.advance(uuid.UUID(str(run_id)))


async def _started(client: httpx.AsyncClient) -> tuple[str, str]:
    """A project whose first run has gone as far as it goes on its own."""
    created = await client.post("/projects", json={"name": "Shelf", "description": ""})
    project_id = created.json()["id"]
    client.created_projects.append(project_id)  # type: ignore[attr-defined]
    await client.patch(f"/projects/{project_id}", json={"requirementText": "A reader adds books."})
    runs = (await client.get("/runs", params={"project": project_id})).json()
    await _advance(client, runs[0]["id"])
    return project_id, runs[0]["id"]


async def _design(client: httpx.AsyncClient, project_id: str) -> dict:
    return (await client.get(f"/projects/{project_id}/design")).json()


async def _continue(client: httpx.AsyncClient, project_id: str, kind: str) -> httpx.Response:
    return await client.post(
        f"/projects/{project_id}/design/questions/continue", json={"kind": kind}
    )


async def _answer(client: httpx.AsyncClient, project_id: str, question_id: str, answer: str):
    answered = await client.post(
        f"/projects/{project_id}/design/questions/{question_id}/answer", json={"answer": answer}
    )
    assert answered.status_code == 200, answered.text


async def _actions(client: httpx.AsyncClient, project_id: str) -> list[str]:
    entries = (await client.get("/audit", params={"project": project_id})).json()
    return [entry["action"] for entry in entries]


class TestTheRunAsksFirst:
    async def test_a_run_whose_analysis_asks_pauses_before_building_the_rest(self, client) -> None:
        project_id, run_id = await _started(client)

        design = await _design(client, project_id)
        assert design["questionsPending"] is True
        assert design["stages"]["requirements"]["status"] == "complete"
        assert {stage: design["stages"][stage]["status"] for stage in LATER} == dict.fromkeys(
            LATER, "pending"
        ), "the rest waits rather than saying it generates"
        assert design["stages"]["design-review"]["status"] != "complete", "no review yet"
        assert client.app.state.c1.calls == ["requirements"], "nothing else was built"
        run = (await client.get(f"/runs/{run_id}")).json()
        assert run["state"] == "awaiting_gate"

    async def test_the_bell_and_the_record_say_what_waits(self, client) -> None:
        project_id, _ = await _started(client)

        waiting = [
            item
            for item in (await client.get("/attention")).json()
            if item["projectId"] == project_id
        ]
        assert [item["title"] for item in waiting] == ["Questions waiting"]
        assert "answers to its questions" in waiting[0]["message"]
        assert "Paused for the design's questions" in await _actions(client, project_id)

    async def test_a_run_whose_analysis_asks_nothing_does_not_pause(self, client) -> None:
        client.app.state.c1.questions = []  # type: ignore[attr-defined]

        project_id, _ = await _started(client)

        design = await _design(client, project_id)
        assert design["questionsPending"] is False
        assert design["stages"]["sprint-plan"]["status"] == "complete"


class TestContinuingWithTheAssumptions:
    async def test_the_rest_is_built_at_the_same_version_and_the_questions_stay_open(
        self, client
    ) -> None:
        project_id, run_id = await _started(client)

        continued = await _continue(client, project_id, "assumptions")
        assert continued.status_code == 200, continued.text
        assert continued.json()["questionsPending"] is False
        await _advance(client, run_id)

        design = await _design(client, project_id)
        assert design["requirementsVersion"] == 1
        assert design["stages"]["sprint-plan"]["status"] == "complete"
        assert design["stages"]["design-review"]["status"] == "complete", "the review is reached"
        # Still open, so they can be answered at the review and applied there.
        assert [question["answer"] for question in design["questions"]] == [None, None]
        assert "Continued with the assumptions" in await _actions(client, project_id)


class TestContinuingWithTheAnswers:
    async def test_nothing_to_continue_with_is_refused(self, client) -> None:
        project_id, _ = await _started(client)

        refused = await _continue(client, project_id, "answers")

        assert refused.status_code == 409
        assert "answer a question first" in refused.json()["error"]

    async def test_the_requirements_are_analysed_again_with_the_answers(self, client) -> None:
        project_id, run_id = await _started(client)
        await _answer(client, project_id, "Q-1", "Only me.")

        continued = await _continue(client, project_id, "answers")
        assert continued.status_code == 200, continued.text
        await _advance(client, run_id)

        design = await _design(client, project_id)
        assert design["requirementsVersion"] == 2
        assert any("Only me." in requirement["text"] for requirement in design["requirements"])
        assert design["questions"] == [], "the answered input asks nothing again"
        assert design["stages"]["sprint-plan"]["status"] == "complete"
        assert client.app.state.c1.calls.count("requirements") == 2
        # Version 1 keeps its question, which the answer still shows above it.
        [answer] = [message for message in design["thread"] if message["kind"] == "answer"]
        assert answer["question"]["question"] == "Who uses the tracker?"
        assert "Continued with the answers" in await _actions(client, project_id)

    async def test_a_note_written_during_the_pause_is_read_with_the_answers(self, client) -> None:
        project_id, run_id = await _started(client)
        await _answer(client, project_id, "Q-1", "Only me.")
        noted = await client.post(
            f"/projects/{project_id}/design/changes",
            json={"note": "Track due dates too.", "by": "you"},
        )
        assert noted.status_code == 200, noted.text

        await _continue(client, project_id, "answers")
        await _advance(client, run_id)

        texts = [
            requirement["text"]
            for requirement in (await _design(client, project_id))["requirements"]
        ]
        assert any("Track due dates too." in text for text in texts), texts

    async def test_applying_the_answers_during_the_pause_continues_the_same_run(
        self, client
    ) -> None:
        project_id, run_id = await _started(client)
        await _answer(client, project_id, "Q-1", "Only me.")

        applied = await client.post(f"/projects/{project_id}/design/answers/apply")
        assert applied.status_code == 200, applied.text
        await _advance(client, run_id)

        design = await _design(client, project_id)
        assert design["requirementsVersion"] == 2
        assert design["stages"]["sprint-plan"]["status"] == "complete"
        runs = (await client.get("/runs", params={"project": project_id})).json()
        assert len(runs) == 1, "the paused run went on; no second run was started"


class TestAFollowUp:
    async def test_it_may_ask_once_more_and_then_goes_on(self, client) -> None:
        client.app.state.c1.follow_ups = ["How many books at most?"]  # type: ignore[attr-defined]
        project_id, run_id = await _started(client)
        await _answer(client, project_id, "Q-1", "Only me.")
        await _continue(client, project_id, "answers")
        await _advance(client, run_id)

        design = await _design(client, project_id)
        assert design["questionsPending"] is True, "the follow-up pauses once more"
        assert [question["question"] for question in design["questions"]] == [
            "How many books at most?"
        ]

        await _answer(client, project_id, "Q-1", "A hundred.")
        await _continue(client, project_id, "answers")
        await _advance(client, run_id)

        design = await _design(client, project_id)
        assert design["questionsPending"] is False, "a third pause never comes"
        assert design["stages"]["sprint-plan"]["status"] == "complete"
        # Asked again by the third analysis, and left open rather than blocking.
        assert [question["answer"] for question in design["questions"]] == [None]


class TestEachGeneration:
    async def test_changes_at_the_review_may_ask_again(self, client) -> None:
        """The pause count is per generation: one that used both of its pauses
        does not stop the next one from asking."""
        client.app.state.c1.follow_ups = ["How many books at most?"]  # type: ignore[attr-defined]
        project_id, run_id = await _started(client)
        for answer in ("Only me.", "A hundred."):
            await _answer(client, project_id, "Q-1", answer)
            await _continue(client, project_id, "answers")
            await _advance(client, run_id)
        assert (await _design(client, project_id))["questionsPending"] is False, "both used"

        changed = await client.post(
            f"/projects/{project_id}/design/decision",
            json={"kind": "changes", "by": "you", "note": "Track due dates too."},
        )
        assert changed.status_code == 200, changed.text
        await _advance(client, run_id)

        design = await _design(client, project_id)
        assert design["requirementsVersion"] == 4
        assert design["questionsPending"] is True

    async def test_a_stage_retried_alone_never_pauses(self, client) -> None:
        project_id, run_id = await _started(client)
        await _continue(client, project_id, "assumptions")
        await _advance(client, run_id)

        retried = await client.post(f"/projects/{project_id}/design/stages/requirements/retry")
        assert retried.status_code == 200, retried.text
        retry = (await client.get("/runs", params={"project": project_id})).json()[0]
        await _advance(client, retry["id"])

        assert (await _design(client, project_id))["questionsPending"] is False
        assert (await client.get(f"/runs/{retry['id']}")).json()["state"] == "done"


class TestThePauseIsNotTheReview:
    async def test_the_review_decision_route_has_nothing_to_decide(self, client) -> None:
        project_id, _ = await _started(client)

        refused = await client.post(
            f"/projects/{project_id}/design/decision",
            json={"kind": "approved", "by": "you", "note": "fine"},
        )

        assert refused.status_code == 409

    async def test_continuing_when_nothing_waits_is_refused(self, client) -> None:
        client.app.state.c1.questions = []  # type: ignore[attr-defined]
        project_id, _ = await _started(client)

        refused = await _continue(client, project_id, "assumptions")

        assert refused.status_code == 409
        assert "not waiting on its questions" in refused.json()["error"]
