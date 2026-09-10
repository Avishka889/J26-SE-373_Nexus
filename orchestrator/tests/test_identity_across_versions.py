"""An id means the same thing in version two as it did in version one.

This is the defect the definition of done walk found on the calculator project,
and it is one of the ones a canned component cannot show. A change note saying
"add a history screen, everything else stays as it is" came back with six user
stories replaced by three carrying the same ids, and with R-1 to R-6 renumbered
into R-1 to R-5. Nothing failed. Every read model composed, every trace resolved
inside its own version, and the phase looked right on screen.

What it cost is two versions away. `diff_requirements` joins the two versions on
the id and is the self healing classifier's first signal: a failing test tracing
to something that changed is a brittleness candidate, one tracing only to
unchanged artefacts is a regression candidate, and a regression is never healed.
Join on a reallocated id and every requirement reads as changed, so every failing
test reads as brittle, so the honesty guard is asked to approve repairs to tests
that were catching real breakage. The headline contribution rests on this.

`CannedC1` cannot show it, and that is worth saying rather than working around.
It reads one requirement per line, so appending a note appends a requirement and
the ones above it keep their numbers by luck. The double here scripts what the
component returns on each reading instead, because that is the part that matters:
a model asked to read the same brief again composes the list afresh rather than
appending to the one it gave last time.
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
from sdlc_contracts import (
    AcceptanceCriterion,
    ParsedRequirement,
    RequirementsArtefact,
    SprintPlan,
    UserStory,
    VelocityAssumption,
    diff_requirements,
)

from .conftest import needs_db

pytestmark = needs_db

ADD = "The calculator adds two numbers."
SUBTRACT = "The calculator subtracts two numbers."
MULTIPLY = "The calculator multiplies two numbers."
DIVIDE = "The calculator divides two numbers and refuses zero."
CLEAR = "The calculator clears the current entry."
REMEMBER = "The calculator keeps the last answer."

CLEAR_REWORDED = "The calculator clears the current entry and the history."
HISTORY = "The calculator shows a history of past answers."

#: What the component returns each time it reads the brief, and every id below
#: is decided by the differences between consecutive rows.
#:
#: Two: the note asked for history, so the model folded it into the clear entry
#: sentence, stopped reporting the last answer sentence at all, and listed what
#: was left in the other order. Nothing was added, which is the case that makes
#: the version before last load bearing: the highest id in the project is now
#: retired, and the next version must not reach back for it.
#:
#: Three: one genuinely new requirement, on top of a version whose own highest
#: id is below the project's.
READINGS: list[list[str]] = [
    [ADD, SUBTRACT, MULTIPLY, DIVIDE, CLEAR, REMEMBER],
    [CLEAR_REWORDED, DIVIDE, MULTIPLY, SUBTRACT, ADD],
    [HISTORY, CLEAR_REWORDED, DIVIDE, MULTIPLY, SUBTRACT, ADD],
]


class RereadingC1(CannedC1):
    """A component that reads the same brief differently each time.

    Not a caricature. A model given a brief and a change note returns a list it
    composed afresh: the sentences it considers requirements shift, the order
    shifts, some are reworded, and it numbers whatever it returns from one.
    """

    def __init__(self) -> None:
        super().__init__()
        self.readings = 0

    async def parse_requirements(self, text: str) -> object:
        self.readings += 1
        assert self.readings <= len(READINGS), "the fixture has no reading for this version"
        outcome = await super().parse_requirements(text)
        return type(outcome)(
            artefact=RequirementsArtefact(
                requirements=[
                    ParsedRequirement(
                        id=f"R-{number}",
                        text=line,
                        type="functional",
                        priority="must",
                        confidence=70,
                        sourceQuote=line,
                    )
                    # Numbered from one down the list it returned, which is what
                    # C1 does and what makes an id positional.
                    for number, line in enumerate(READINGS[self.readings - 1], start=1)
                ]
            ),
            summary=outcome.summary,
            notes=outcome.notes,
        )

    async def plan_sprint(self, requirements, graph) -> object:  # type: ignore[no-untyped-def]
        """Two stories, ranked the other way round after the first reading.

        C1 numbers stories down the priority ranking, so a story nobody touched
        is renumbered when the story above it moves. A test traces to a story id,
        so the reader's question is "why is US-1 a different story than it was",
        and there was no answer.
        """
        outcome = await super().plan_sprint(requirements, graph)

        def traces(opening: str) -> list[str]:
            found = [r.id for r in requirements if r.text.startswith(opening)]
            return found or [requirements[0].id]

        stories = [
            (traces("The calculator adds"), "As someone, I can add two numbers"),
            (traces("The calculator clears"), "As someone, I can clear the entry"),
        ]
        if self.readings > 1:
            stories.reverse()
        planned = [
            UserStory(
                id=f"US-{number}",
                title=title,
                epic="Arithmetic",
                points=3,
                priority="must",
                traces=traced,
                # Two criteria, one of which the model rewords after the first
                # reading. The stable one proves a criterion keeps the id it had;
                # the reworded one is a new criterion of a story that kept its
                # id, so its number has to come from the id the story kept
                # rather than the one C1 wrote it under.
                acceptance=[
                    AcceptanceCriterion(
                        id=f"AC-{number}-1",
                        given="the calculator is open",
                        when="they use it",
                        then="the answer is shown",
                    ),
                    AcceptanceCriterion(
                        id=f"AC-{number}-2",
                        given="the calculator is open",
                        when="they use it twice",
                        then=(
                            "the previous answer is kept"
                            if self.readings > 1
                            else "the last answer is kept"
                        ),
                    ),
                ],
            )
            for number, (traced, title) in enumerate(stories, start=1)
        ]
        return type(outcome)(
            artefact=SprintPlan(
                sprintName="Sprint 1 (proposed)",
                goal="Arithmetic works.",
                velocityAssumption=VelocityAssumption(points=20, basis="assumed, not measured"),
                estimatedPoints=sum(one.points for one in planned),
                proposed=planned,
            ),
            summary=outcome.summary,
            notes=outcome.notes,
        )


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings, lifespan_factory=lifespan_for_tests)
    app.state.c1 = RereadingC1()
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


async def _advance(client: httpx.AsyncClient, run_id: str) -> None:
    supervisor: RunSupervisor = client.app.state.supervisor  # type: ignore[attr-defined]
    await supervisor.advance(uuid.UUID(run_id))


async def _note(client: httpx.AsyncClient, project_id: str, run_id: str, note: str) -> None:
    decided = await client.post(
        f"/projects/{project_id}/design/decision",
        json={"kind": "changes", "by": "A. Chen", "note": note},
    )
    assert decided.status_code == 200, decided.text
    await _advance(client, run_id)


async def _versions(client: httpx.AsyncClient, *, upto: int) -> str:
    """A design regenerated by a change note, `upto` times over."""
    created = await client.post("/projects", json={"name": "Calculator", "description": ""})
    project_id = created.json()["id"]
    client.created_projects.append(project_id)  # type: ignore[attr-defined]
    await client.patch(f"/projects/{project_id}", json={"requirementText": "\n".join(READINGS[0])})
    run_id = (await client.get("/runs", params={"project": project_id})).json()[0]["id"]

    await _advance(client, run_id)
    notes = [
        "Add a history screen, everything else stays as it is",
        "Show the past answers on the history screen",
    ]
    for note in notes[: upto - 1]:
        await _note(client, project_id, run_id, note)

    snapshot = (await client.get(f"/projects/{project_id}/design")).json()
    assert snapshot["requirementsVersion"] == upto, "the design did not reach that version"
    return project_id


async def _requirements_at(
    client: httpx.AsyncClient, project_id: str, version: int
) -> RequirementsArtefact:
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        rows = await store.artefacts_at(conn, project_id, version=version, kinds=("requirements",))
    return RequirementsArtefact.model_validate(rows["requirements"]["body"])


async def _sprint_at(client: httpx.AsyncClient, project_id: str, version: int) -> SprintPlan:
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        rows = await store.artefacts_at(conn, project_id, version=version, kinds=("sprint-plan",))
    return SprintPlan.model_validate(rows["sprint-plan"]["body"])


def _by_text(artefact: RequirementsArtefact) -> dict[str, str]:
    return {one.text: one.id for one in artefact.requirements}


class TestARegeneratedDesignKeepsItsRequirementIds:
    async def test_a_requirement_nobody_touched_has_the_id_it_had(self, client) -> None:
        project_id = await _versions(client, upto=2)

        was = _by_text(await _requirements_at(client, project_id, 1))
        now = _by_text(await _requirements_at(client, project_id, 2))

        assert [now[text] for text in (ADD, SUBTRACT, MULTIPLY, DIVIDE)] == [
            was[text] for text in (ADD, SUBTRACT, MULTIPLY, DIVIDE)
        ]
        # And the one the model reworded is the same requirement reworded, which
        # is what lets the diff say `changed` rather than removed and added.
        assert now[CLEAR_REWORDED] == was[CLEAR]

    async def test_the_diff_reports_what_the_note_did_and_not_everything(self, client) -> None:
        """The assertion the classifier's first signal actually rests on."""
        project_id = await _versions(client, upto=2)
        first = await _requirements_at(client, project_id, 1)

        diff = diff_requirements(
            first,
            await _requirements_at(client, project_id, 2),
            from_version=1,
            to_version=2,
        )

        assert [change.requirement_id for change in diff.changed] == [_by_text(first)[CLEAR]]
        assert diff.removed == [_by_text(first)[REMEMBER]]
        assert diff.added == []
        # Before this, `touched` was every requirement in the project, so no
        # failing test could be classified as a regression and the guard was
        # asked to approve repairs to tests that were catching real breakage.
        assert len(diff.touched) == 2

    async def test_a_retired_id_is_not_reissued_by_a_later_version(self, client) -> None:
        """Identity is decided against every version, not just the last one.

        Version two retired the highest id in the project and added nothing, so
        its own highest is below the project's. A version three that only looked
        at version two would hand the new requirement the id that named the last
        answer requirement in version one, and the reuse would be two versions
        apart and invisible.
        """
        project_id = await _versions(client, upto=3)

        was = _by_text(await _requirements_at(client, project_id, 1))
        third = await _requirements_at(client, project_id, 3)

        retired = was[REMEMBER]
        assert _by_text(third)[HISTORY] != retired, f"{retired} was handed out again"
        assert retired not in {one.id for one in third.requirements}

    async def test_and_what_version_two_carried_is_still_carried(self, client) -> None:
        project_id = await _versions(client, upto=3)

        second = _by_text(await _requirements_at(client, project_id, 2))
        third = _by_text(await _requirements_at(client, project_id, 3))

        assert all(third[text] == second[text] for text in second), (
            "a third version renumbered what the second had already settled"
        )


class TestARegeneratedSprintKeepsItsStoryIds:
    async def test_a_story_reranked_by_the_note_keeps_its_id(self, client) -> None:
        project_id = await _versions(client, upto=2)

        first = await _sprint_at(client, project_id, 1)
        second = await _sprint_at(client, project_id, 2)

        was = {one.title: one.id for one in (*first.proposed, *first.backlog)}
        now = {one.title: one.id for one in (*second.proposed, *second.backlog)}
        assert set(was) == set(now), "the fixture has to plan the same two stories"
        assert now == was, "a story was renumbered when the ranking moved"

    async def test_its_acceptance_criteria_are_numbered_for_the_id_it_kept(self, client) -> None:
        """Otherwise the fix leaves a story called US-2 holding AC-1-3."""
        project_id = await _versions(client, upto=2)

        for story in (await _sprint_at(client, project_id, 2)).proposed:
            number = story.id.split("-")[1]
            assert all(one.id.startswith(f"AC-{number}-") for one in story.acceptance), (
                f"{story.id} holds criteria numbered for a different story: "
                f"{[one.id for one in story.acceptance]}"
            )

    async def test_a_criterion_that_says_the_same_thing_keeps_its_id(self, client) -> None:
        """C3 derives one test per criterion, so this is the finest trace there is."""
        project_id = await _versions(client, upto=2)

        first = await _sprint_at(client, project_id, 1)
        second = await _sprint_at(client, project_id, 2)

        def by_wording(plan: SprintPlan) -> dict[tuple[str, str], str]:
            return {
                (story.title, one.then): one.id
                for story in (*plan.proposed, *plan.backlog)
                for one in story.acceptance
            }

        was, now = by_wording(first), by_wording(second)
        shared = set(was) & set(now)
        assert len(shared) == 2, "one unchanged criterion per story"
        assert all(now[key] == was[key] for key in shared)


class TestAHumanCorrectionStaysOnTheRequirementTheyCorrected:
    """The product consequence, and the one a reader would actually notice.

    A correction is stored as an overlay against a requirement id and laid over
    every version, so that the artefact keeps what the machine produced and the
    correction rate stays measurable. That is only safe if the id means the same
    requirement in both versions.

    It did not. Observed on this fixture with the carry removed: the correction
    written against the subtraction requirement at version one was laid over the
    division requirement at version two, and the subtraction requirement came
    back with the model's original wording. The person who corrected it sees
    their words on something they never touched, and nothing anywhere says so.
    """

    async def test_it_does_not_land_on_a_different_requirement_at_the_next_version(
        self, client
    ) -> None:
        created = await client.post("/projects", json={"name": "Calculator", "description": ""})
        project_id = created.json()["id"]
        client.created_projects.append(project_id)  # type: ignore[attr-defined]
        await client.patch(
            f"/projects/{project_id}", json={"requirementText": "\n".join(READINGS[0])}
        )
        run_id = (await client.get("/runs", params={"project": project_id})).json()[0]["id"]
        await _advance(client, run_id)

        first = (await client.get(f"/projects/{project_id}/design")).json()["requirements"]
        subtraction = next(one["id"] for one in first if one["text"] == SUBTRACT)
        correction = "The calculator subtracts two numbers and may return a negative."
        edited = await client.patch(
            f"/projects/{project_id}/design/requirements/{subtraction}",
            json={"text": correction, "by": "A. Chen"},
        )
        assert edited.status_code == 200, edited.text

        await _note(client, project_id, run_id, "Add a history screen")

        second = (await client.get(f"/projects/{project_id}/design")).json()["requirements"]
        corrected = [one for one in second if one["adjusted"]]
        assert len(corrected) == 1, "one correction was made, so one requirement is adjusted"
        assert corrected[0]["id"] == subtraction
        assert corrected[0]["text"] == correction
        # Which requirement carries it is the whole question, and the id alone
        # cannot answer it: the id is the same either way. What says the
        # correction went to the right place is that the requirement holding it
        # is the one it was written against.
        texts = {one["text"] for one in second}
        assert DIVIDE in texts, "the correction was laid over the division requirement"
        assert SUBTRACT not in texts, (
            "the subtraction requirement came back with the model's own wording, so the "
            "correction was applied to something the person never touched"
        )
        assert texts == {correction, ADD, MULTIPLY, DIVIDE, CLEAR_REWORDED}


class TestTheRunSaysHowEachIdWasDecided:
    async def test_the_audit_note_counts_what_was_observed_and_what_was_inferred(
        self, client
    ) -> None:
        """An identity read off identical text and one inferred from similarity
        are not the same evidence, so the run records them apart.

        In the audit note rather than the artefact, for the reason every other
        honesty metric is: how an id was decided is a fact about this run, and
        putting it in the artefact would make two runs that produced the same
        design compare as different.
        """
        project_id = await _versions(client, upto=2)

        events = (await client.get("/audit", params={"project": project_id})).json()
        generated = [e for e in events if e["action"] == "Generated Requirements Analysis"]
        assert len(generated) == 2, "one per version"
        second = next(e for e in generated if e["target"] == "version 2")

        assert "ids kept: 4" in second["detail"]
        assert "ids matched: 1" in second["detail"], "the reworded requirement was recognised"
        assert "ids new: 0" in second["detail"]
        assert "ids retired: 1" in second["detail"]

    async def test_the_first_version_has_nothing_to_carry_and_says_so(self, client) -> None:
        project_id = await _versions(client, upto=2)

        events = (await client.get("/audit", params={"project": project_id})).json()
        first = next(
            e
            for e in events
            if e["action"] == "Generated Requirements Analysis" and e["target"] == "version 1"
        )

        assert "ids kept: 0" in first["detail"]
        assert "ids new: 6" in first["detail"]
