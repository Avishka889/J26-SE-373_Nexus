"""Answers the design reads, when the reader applies them.

Answers were stored, shown in the thread, and read by nothing: C1 reads the
brief plus the applied change notes, so a design never moved when a person
answered its questions. The last answer then applied them all at once, which
regenerated the whole design (a model run) with no word beforehand and a
"Requested changes" the reader never asked for. Now answering records, and
applying the answers is the reader's own act. An answer belongs to the version
of the questions it answered.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import datetime

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


async def _at_the_review(client: httpx.AsyncClient) -> tuple[str, str]:
    created = await client.post("/projects", json={"name": "Shelf", "description": ""})
    project_id = created.json()["id"]
    client.created_projects.append(project_id)  # type: ignore[attr-defined]
    await client.patch(f"/projects/{project_id}", json={"requirementText": "A reader adds books."})
    runs = (await client.get("/runs", params={"project": project_id})).json()
    await _advance(client, runs[0]["id"])
    # The analysis asks its questions before the rest is built. These tests answer
    # them at the review, so they go on with the assumptions here
    # (test_design_questions covers answering at the pause).
    continued = await client.post(
        f"/projects/{project_id}/design/questions/continue", json={"kind": "assumptions"}
    )
    assert continued.status_code == 200, continued.text
    await _advance(client, runs[0]["id"])
    return project_id, runs[0]["id"]


async def _answer(client, project_id: str, question_id: str, answer: str) -> dict:
    answered = await client.post(
        f"/projects/{project_id}/design/questions/{question_id}/answer", json={"answer": answer}
    )
    assert answered.status_code == 200, answered.text
    return answered.json()


class TestAnswersReachTheDesign:
    async def test_an_answer_with_questions_still_open_changes_nothing_yet(self, client) -> None:
        project_id, _ = await _at_the_review(client)

        snapshot = await _answer(client, project_id, "Q-1", "Only me.")

        assert snapshot["requirementsVersion"] == 1
        assert snapshot["gate"]["decision"] is None, "the review is still waiting"
        assert [question["answer"] for question in snapshot["questions"]] == ["Only me.", None]

    async def test_the_last_answer_changes_nothing_until_applied(self, client) -> None:
        project_id, _ = await _at_the_review(client)
        await _answer(client, project_id, "Q-1", "Only me.")

        snapshot = await _answer(client, project_id, "Q-2", "In the browser, for now.")

        assert snapshot["requirementsVersion"] == 1
        assert snapshot["gate"]["history"] == [], "no change was requested"
        assert [question["answer"] for question in snapshot["questions"]] == [
            "Only me.",
            "In the browser, for now.",
        ]

    async def test_applying_the_answers_regenerates_the_design_with_every_answer(
        self, client
    ) -> None:
        project_id, run_id = await _at_the_review(client)
        await _answer(client, project_id, "Q-1", "Only me.")
        await _answer(client, project_id, "Q-2", "In the browser, for now.")

        applied = await client.post(f"/projects/{project_id}/design/answers/apply")
        assert applied.status_code == 200, applied.text
        snapshot = applied.json()

        # The review's own "request changes", carrying both answers. It decided
        # version 1, so it sits in the history of the version it opened.
        [decided] = [one for one in snapshot["gate"]["history"] if one["kind"] == "changes"]
        note = decided["note"]
        assert "Who uses the tracker? Only me." in note
        assert "Where are the books kept? In the browser, for now." in note
        assert any(
            "The design is regenerating with your answers." in message["content"]
            for message in snapshot["thread"]
        )

        await _advance(client, run_id)
        design = (await client.get(f"/projects/{project_id}/design")).json()
        texts = [requirement["text"] for requirement in design["requirements"]]
        assert design["requirementsVersion"] == 2
        assert any("Only me." in text for text in texts), texts
        assert design["questions"] == [], "the answered input asks nothing again"

    async def test_there_is_nothing_to_apply_before_an_answer(self, client) -> None:
        project_id, _ = await _at_the_review(client)

        refused = await client.post(f"/projects/{project_id}/design/answers/apply")

        assert refused.status_code == 409
        assert "no answers to apply" in refused.json()["error"]

    async def test_a_question_the_design_did_not_ask_is_refused(self, client) -> None:
        project_id, _ = await _at_the_review(client)

        refused = await client.post(
            f"/projects/{project_id}/design/questions/Q-99/answer", json={"answer": "Yes."}
        )

        assert refused.status_code == 404


class TestAnApprovalDoesNotLoseAnswers:
    """Answering records an answer; only applying it reaches the design and the
    code. An approval with answers given and never applied lost them, while the
    bar read "every question answered"."""

    async def test_approving_over_an_unapplied_answer_needs_a_note(self, client) -> None:
        project_id, _ = await _at_the_review(client)
        await _answer(client, project_id, "Q-1", "Only me.")

        refused = await client.post(
            f"/projects/{project_id}/design/decision", json={"kind": "approved", "by": "you"}
        )

        assert refused.status_code == 409
        assert "1 answer given and not applied to the design" in refused.json()["error"]
        note = "The answer only confirms what the brief says."
        approved = await client.post(
            f"/projects/{project_id}/design/decision",
            json={"kind": "approved", "by": "you", "note": note},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["gate"]["decision"]["note"] == note

    async def test_once_applied_the_answers_are_no_concern(self, client) -> None:
        project_id, run_id = await _at_the_review(client)
        await _answer(client, project_id, "Q-1", "Only me.")
        await _answer(client, project_id, "Q-2", "On one shelf.")
        applied = await client.post(f"/projects/{project_id}/design/answers/apply")
        assert applied.status_code == 200, applied.text
        await _advance(client, run_id)

        approved = await client.post(
            f"/projects/{project_id}/design/decision", json={"kind": "approved", "by": "you"}
        )

        assert approved.status_code == 200, approved.text


class TestADesignCodeGenerationCannotBuildFrom:
    """A failed Sprint Planning was approved with a note, and Code Generation then
    failed on "no sprint plan at the design version this run pinned", with no
    way on but requesting changes."""

    async def test_approving_without_a_sprint_plan_is_refused_whatever_the_note(
        self, client
    ) -> None:
        client.app.state.c1.fails.add("sprint-plan")  # type: ignore[attr-defined]
        project_id, _ = await _at_the_review(client)
        client.app.state.c1.fails.clear()  # type: ignore[attr-defined]

        refused = await client.post(
            f"/projects/{project_id}/design/decision",
            json={"kind": "approved", "note": "we will plan later"},
        )

        assert refused.status_code == 409
        assert (
            "has no Sprint Planning, which Code Generation builds from" in refused.json()["error"]
        )

    async def test_approving_while_a_stage_generates_is_refused(self, client) -> None:
        project_id, _ = await _at_the_review(client)
        async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
            await store.set_stage(conn, project_id, "wireframes", status="generating")

        refused = await client.post(
            f"/projects/{project_id}/design/decision", json={"kind": "approved", "note": "go"}
        )

        assert refused.status_code == 409
        assert "Wireframes is still generating" in refused.json()["error"]


class TestAnAnswerBelongsToItsVersion:
    async def test_a_new_versions_questions_arrive_unanswered(self, client) -> None:
        """Answers were matched by question id across versions, so a regenerated
        design's questions arrived answered with the previous version's answers."""
        project_id, run_id = await _at_the_review(client)
        await _answer(client, project_id, "Q-1", "Only me.")

        changed = await client.post(
            f"/projects/{project_id}/design/decision",
            json={"kind": "changes", "by": "you", "note": "Track due dates too."},
        )
        assert changed.status_code == 200, changed.text
        await _advance(client, run_id)

        design = (await client.get(f"/projects/{project_id}/design")).json()
        assert design["requirementsVersion"] == 2
        assert [question["id"] for question in design["questions"]] == ["Q-1", "Q-2"]
        assert [question["answer"] for question in design["questions"]] == [None, None]


class TestAnAnswerKeepsItsQuestion:
    """An answer reached the conversation as its words alone, and the question it
    answered left the conversation the moment it was answered: the reader saw
    "one user" and nothing saying what it answered."""

    async def test_the_answer_in_the_conversation_carries_its_question(self, client) -> None:
        project_id, _ = await _at_the_review(client)

        snapshot = await _answer(client, project_id, "Q-2", "In the browser, for now.")

        [answer] = [message for message in snapshot["thread"] if message["kind"] == "answer"]
        assert answer["content"] == "In the browser, for now."
        asked = answer["question"]
        assert asked is not None, "the answer says what it answers"
        assert (asked["id"], asked["question"], asked["traces"]) == (
            "Q-2",
            "Where are the books kept?",
            ["R-1"],
        )
        assert datetime.fromisoformat(asked["askedAt"]) <= datetime.fromisoformat(answer["at"])
        others = [message for message in snapshot["thread"] if message["kind"] != "answer"]
        assert others and all(message["question"] is None for message in others)

    async def test_two_answers_in_the_same_words_keep_their_own_questions(self, client) -> None:
        """Paired by time as well as words: "Yes." answers many questions."""
        project_id, _ = await _at_the_review(client)
        await _answer(client, project_id, "Q-1", "Yes.")

        snapshot = await _answer(client, project_id, "Q-2", "Yes.")

        answers = [message for message in snapshot["thread"] if message["kind"] == "answer"]
        assert [answer["question"]["id"] for answer in answers] == ["Q-1", "Q-2"]

    async def test_an_answer_keeps_the_question_of_the_version_it_answered(self, client) -> None:
        """A question's id is its place in the list, so version 2's Q-1 is
        another question, and the answer given at version 1 did not answer it."""
        project_id, run_id = await _at_the_review(client)
        await _answer(client, project_id, "Q-1", "Only me.")
        client.app.state.c1.questions = ["Which shelves count?"]  # type: ignore[attr-defined]

        changed = await client.post(
            f"/projects/{project_id}/design/decision",
            json={"kind": "changes", "by": "you", "note": "Track due dates too."},
        )
        assert changed.status_code == 200, changed.text
        await _advance(client, run_id)

        design = (await client.get(f"/projects/{project_id}/design")).json()
        assert design["requirementsVersion"] == 2
        assert [question["question"] for question in design["questions"]] == [
            "Which shelves count?"
        ]
        [answer] = [message for message in design["thread"] if message["kind"] == "answer"]
        assert answer["question"]["question"] == "Who uses the tracker?"


class TestTheWireframesReadTheRequirements:
    async def test_the_wireframe_stage_is_told_what_the_requirements_say(self, client) -> None:
        """It was given the graph and the requirement ids, and never what anybody
        asked for, so every journey came out as the same forms and lists."""
        project_id, _ = await _at_the_review(client)

        design = (await client.get(f"/projects/{project_id}/design")).json()
        told = client.app.state.c1.wireframes_read  # type: ignore[attr-defined]

        assert told == [requirement["text"] for requirement in design["requirements"]]
        assert "A reader adds books." in told
