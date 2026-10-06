"""The code phase's front door: what the browser calls, and what it gets back.

Every route answers with a whole snapshot, so these assert on the snapshot
rather than on rows. What they hold to account is the difference between the
two kinds of change: one costs a run because it changes what gets built, the
other is a decision about what already exists and costs nothing.
"""

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from orchestrator.api.code import contract_concern
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.clients.canned import CANNED_CONTRACT
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.graph.runner import RunSupervisor
from orchestrator.main import create_app, lifespan_for_tests
from sdlc_contracts import (
    CODE_STAGE_IDS,
    ApiContractArtefact,
    ArmComparison,
    ArmCounts,
    ContractRuleFinding,
)

from .conftest import needs_db

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


async def _advance_all(client: httpx.AsyncClient, project_id: str) -> None:
    """Drive whatever run is queued. Tests own the timing, not a poller."""
    supervisor: RunSupervisor = client.app.state.supervisor  # type: ignore[attr-defined]
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        run = await store.latest_run(conn, project_id)
    if run is not None and run["state"] in {"queued", "running"}:
        await supervisor.advance(uuid.UUID(str(run["id"])))


async def _project(client: httpx.AsyncClient, *, approve: bool = True) -> str:
    created = await client.post("/projects", json={"name": "Records", "description": ""})
    project_id = created.json()["id"]
    client.created_projects.append(project_id)  # type: ignore[attr-defined]
    await client.patch(
        f"/projects/{project_id}", json={"requirementText": "Someone creates a record."}
    )
    await _advance_all(client, project_id)
    if approve:
        await client.post(
            f"/projects/{project_id}/design/decision", json={"kind": "approved", "by": "you"}
        )
        await _advance_all(client, project_id)
    return project_id


async def _generated(client: httpx.AsyncClient) -> tuple[str, dict]:
    """An approved project with one code run walked to its gate."""
    project_id = await _project(client)
    started = await client.post(f"/projects/{project_id}/code/generate")
    assert started.status_code == 200, started.text
    await _advance_all(client, project_id)
    snapshot = (await client.get(f"/projects/{project_id}/code")).json()
    return project_id, snapshot


class TestTheContractReadsTheCriteria:
    async def test_the_contract_stage_hands_c2_the_criteria_of_the_stories_in_the_build(
        self, client
    ) -> None:
        """Their bounds were words the contract never carried, and the app took any
        value: the Movie Tracker took release years 1999 and 2027."""
        project_id, snapshot = await _generated(client)

        async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
            design = await store.artefacts_at(
                conn,
                project_id,
                version=snapshot["generatedFromDesignVersion"],
                kinds=("sprint-plan",),
            )
            built = await store.artefacts_at(
                conn, project_id, version=snapshot["codeVersion"], kinds=("sprint-scope",)
            )
        in_build = {
            story["id"] for story in built["sprint-scope"]["body"]["stories"] if story["inScope"]
        }
        plan = design["sprint-plan"]["body"]
        expected = [
            f"Given {criterion['given']}. When {criterion['when']}. Then {criterion['then']}."
            for story in [*plan["proposed"], *plan["backlog"]]
            if story["id"] in in_build
            for criterion in story["acceptance"]
        ]
        assert expected, "the canned plan's stories in the build have criteria"
        assert client.app.state.c2.contract_criteria == expected  # type: ignore[attr-defined]


class TestReadingBeforeAnythingExists:
    async def test_a_project_with_no_code_still_answers_a_whole_snapshot(self, client) -> None:
        project_id = await _project(client, approve=False)
        answer = await client.get(f"/projects/{project_id}/code")
        assert answer.status_code == 200
        body = answer.json()
        assert body["codeVersion"] == 0
        assert body["generatedFromDesignVersion"] == 0
        # All eight present and pending: the client indexes them with no guard.
        assert set(body["stages"]) == set(CODE_STAGE_IDS)
        assert {stage["status"] for stage in body["stages"].values()} == {"pending"}
        assert body["scope"] is None and body["contract"] is None
        assert body["diff"] is None
        assert body["gate"]["decision"] is None


class TestStartingAGeneration:
    async def test_an_unapproved_design_refuses_with_a_reason(self, client) -> None:
        project_id = await _project(client, approve=False)
        answer = await client.post(f"/projects/{project_id}/code/generate")
        assert answer.status_code == 409
        assert "has not been approved" in answer.text

    async def test_generating_flips_the_stages_and_answers_the_snapshot(self, client) -> None:
        project_id = await _project(client)
        answer = await client.post(f"/projects/{project_id}/code/generate")
        assert answer.status_code == 200
        body = answer.json()
        generating = [
            stage for stage, state in body["stages"].items() if state["status"] == "generating"
        ]
        assert set(generating) == set(CODE_STAGE_IDS) - {"code-review"}

    async def test_a_second_generation_while_one_is_in_flight_refuses(self, client) -> None:
        project_id = await _project(client)
        await client.post(f"/projects/{project_id}/code/generate")
        again = await client.post(f"/projects/{project_id}/code/generate")
        assert again.status_code == 409
        assert "already in flight" in again.text

    async def test_a_finished_run_leaves_a_snapshot_with_every_artefact(self, client) -> None:
        _project_id, snapshot = await _generated(client)
        assert snapshot["codeVersion"] == 1
        assert snapshot["generatedFromDesignVersion"] == 1
        assert snapshot["scope"]["sprintName"]
        assert snapshot["techStack"]["recommendedId"]
        assert snapshot["contract"]["contract"]["endpoints"]
        assert snapshot["agreement"]["counts"]["endpointsTotal"] >= 1
        assert snapshot["repository"]["manifest"]
        assert snapshot["repository"]["build"]["steps"]
        assert snapshot["stages"]["code-review"]["status"] == "complete"
        # The thread carries the code conversation and nothing else.
        assert snapshot["thread"]
        assert all(message["stageId"] in CODE_STAGE_IDS for message in snapshot["thread"])


class TestServingOneFile:
    async def test_a_generated_file_comes_back_by_path(self, client) -> None:
        project_id, snapshot = await _generated(client)
        path = snapshot["repository"]["manifest"][0]["path"]
        answer = await client.get(f"/projects/{project_id}/code/files/{path}")
        assert answer.status_code == 200
        body = answer.json()
        assert body["path"] == path
        assert body["content"]
        assert body["version"] == snapshot["codeVersion"]

    async def test_a_path_that_was_never_generated_is_a_404(self, client) -> None:
        project_id, _ = await _generated(client)
        answer = await client.get(f"/projects/{project_id}/code/files/apps/web/nope.tsx")
        assert answer.status_code == 404

    async def test_the_snapshot_never_carries_a_file_body(self, client) -> None:
        """It is polled every 1.2 seconds while generating; a run writes tens
        of files. The manifest is what it carries."""
        _project_id, snapshot = await _generated(client)
        assert all("content" not in row for row in snapshot["repository"]["manifest"])


class TestChoosingWithoutRegenerating:
    async def test_selecting_a_stack_records_the_choice_and_starts_no_run(self, client) -> None:
        project_id, snapshot = await _generated(client)
        async with client.app.state.pool.connection() as conn:
            before = await store.latest_run(conn, project_id)

        answer = await client.post(
            f"/projects/{project_id}/code/stack/select",
            json={"stackId": "react-spring-postgres", "by": "you"},
        )
        assert answer.status_code == 200
        assert answer.json()["techStack"]["selectedId"] == "react-spring-postgres"
        assert answer.json()["techStack"]["selectedBy"] == "Local development"

        async with client.app.state.pool.connection() as conn:
            after = await store.latest_run(conn, project_id)
        assert str(after["id"]) == str(before["id"]), "choosing a stack must cost no run"
        assert answer.json()["codeVersion"] == snapshot["codeVersion"]

    async def test_the_newest_selection_is_the_one_shown(self, client) -> None:
        """Overlays come oldest first, and the first selection found was the one
        shown: after a regeneration, Select appeared to do nothing."""
        project_id, _ = await _generated(client)
        await client.post(
            f"/projects/{project_id}/code/stack/select",
            json={"stackId": "react-spring-postgres", "by": "you"},
        )
        await client.post(f"/projects/{project_id}/code/arm", json={"arm": "llm", "by": "you"})
        await _advance_all(client, project_id)

        answer = await client.post(
            f"/projects/{project_id}/code/stack/select", json={"stackId": "mern", "by": "you"}
        )

        assert answer.status_code == 200, answer.text
        assert answer.json()["techStack"]["selectedId"] == "mern"

    async def test_a_stack_that_is_not_a_candidate_is_ignored_rather_than_shown(
        self, client
    ) -> None:
        project_id, _ = await _generated(client)
        answer = await client.post(
            f"/projects/{project_id}/code/stack/select",
            json={"stackId": "cobol-on-cogs", "by": "you"},
        )
        assert answer.status_code == 200
        assert answer.json()["techStack"]["selectedId"] != "cobol-on-cogs"


class TestChangingWhatGetsBuilt:
    async def test_choosing_an_arm_regenerates_at_a_new_code_version(self, client) -> None:
        project_id, snapshot = await _generated(client)
        answer = await client.post(
            f"/projects/{project_id}/code/arm", json={"arm": "llm", "by": "you"}
        )
        assert answer.status_code == 200
        assert answer.json()["codeVersion"] == snapshot["codeVersion"]  # not written yet

        await _advance_all(client, project_id)
        after = (await client.get(f"/projects/{project_id}/code")).json()
        assert after["codeVersion"] == snapshot["codeVersion"] + 1
        assert after["contract"]["chosen"] == "llm"
        # The receipt for the change: a diff between the two contract versions.
        assert after["diff"] is not None
        assert after["diff"]["fromVersion"] == 1 and after["diff"]["toVersion"] == 2

    async def test_taking_a_story_out_of_scope_regenerates(self, client) -> None:
        project_id, snapshot = await _generated(client)
        story_id = snapshot["scope"]["stories"][0]["id"]
        answer = await client.post(
            f"/projects/{project_id}/code/scope/{story_id}",
            json={"inScope": False, "by": "you"},
        )
        assert answer.status_code == 200
        await _advance_all(client, project_id)

        after = (await client.get(f"/projects/{project_id}/code")).json()
        assert after["codeVersion"] == snapshot["codeVersion"] + 1
        story = next(s for s in after["scope"]["stories"] if s["id"] == story_id)
        assert story["inScope"] is False
        assert story["decidedBy"] == "Local development"


class TestRetryingOneStage:
    async def test_a_retry_regenerates_only_that_stage(self, client) -> None:
        project_id, snapshot = await _generated(client)
        canned = client.app.state.c2
        canned.calls.clear()

        answer = await client.post(f"/projects/{project_id}/code/stages/tech-stack/retry")
        assert answer.status_code == 200
        await _advance_all(client, project_id)

        assert canned.calls == ["tech-stack"]
        after = (await client.get(f"/projects/{project_id}/code")).json()
        assert after["codeVersion"] == snapshot["codeVersion"], "a retry allocates no version"
        assert after["stages"]["tech-stack"]["status"] == "complete"

    async def test_the_gate_stage_cannot_be_retried(self, client) -> None:
        project_id, _ = await _generated(client)
        answer = await client.post(f"/projects/{project_id}/code/stages/code-review/retry")
        assert answer.status_code == 409
        assert "the gate" in answer.text

    async def test_a_stage_that_is_not_a_code_stage_is_a_404(self, client) -> None:
        project_id, _ = await _generated(client)
        answer = await client.post(f"/projects/{project_id}/code/stages/wireframes/retry")
        assert answer.status_code == 404


class TestTheGate:
    async def test_approving_moves_the_project_to_testing(self, client) -> None:
        project_id, _ = await _generated(client)
        answer = await client.post(
            f"/projects/{project_id}/code/decision", json={"kind": "approved", "by": "you"}
        )
        assert answer.status_code == 200
        body = answer.json()
        assert body["gate"]["decision"]["kind"] == "approved"

        project = (await client.get(f"/projects/{project_id}")).json()
        assert project["status"] == "testing"
        # Design and code finished, testing and deployment not started: half.
        assert project["progress"] == 50

    async def test_approving_over_a_failed_build_needs_a_note(self, client) -> None:
        """A code version was approved with its typecheck failing, in one click."""
        client.app.state.c2.typecheck_outcome = "failed"  # type: ignore[attr-defined]
        project_id, snapshot = await _generated(client)
        assert snapshot["stages"]["code-review"]["status"] == "complete"

        refused = await client.post(
            f"/projects/{project_id}/code/decision", json={"kind": "approved", "by": "you"}
        )
        assert refused.status_code == 409
        assert "a build that did not pass" in refused.json()["error"]

        note = "The typecheck failure is in a test helper the next sprint replaces."
        approved = await client.post(
            f"/projects/{project_id}/code/decision",
            json={"kind": "approved", "by": "you", "note": note},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["gate"]["decision"]["note"] == note

    async def test_approving_over_an_error_in_the_contract_needs_a_note(self, client) -> None:
        """The clinic project (2026-10-13) was approved over a contract with no
        way to create a doctor or a patient: the rule arm's own check had said
        "'Book Appointment' is a form with 5 fields and no write endpoint traces
        to it", and nothing at the review asked about it."""
        client.app.state.c2.rule_findings = [BOOK_APPOINTMENT]  # type: ignore[attr-defined]
        try:
            project_id, _ = await _generated(client)
        finally:
            client.app.state.c2.rule_findings = []  # type: ignore[attr-defined]

        refused = await client.post(
            f"/projects/{project_id}/code/decision", json={"kind": "approved", "by": "you"}
        )
        assert refused.status_code == 409
        assert "1 error in the API contract it was built from" in refused.json()["error"]

        note = "The booking form is next sprint's; this one only records doctors and patients."
        approved = await client.post(
            f"/projects/{project_id}/code/decision",
            json={"kind": "approved", "by": "you", "note": note},
        )
        assert approved.status_code == 200, approved.text

    async def test_a_warning_in_the_contract_needs_no_note(self, client) -> None:
        client.app.state.c2.rule_findings = [  # type: ignore[attr-defined]
            BOOK_APPOINTMENT.model_copy(update={"severity": "warning"})
        ]
        try:
            project_id, _ = await _generated(client)
        finally:
            client.app.state.c2.rule_findings = []  # type: ignore[attr-defined]

        approved = await client.post(
            f"/projects/{project_id}/code/decision", json={"kind": "approved", "by": "you"}
        )
        assert approved.status_code == 200, approved.text

    async def test_requesting_changes_without_a_note_refuses(self, client) -> None:
        project_id, _ = await _generated(client)
        answer = await client.post(
            f"/projects/{project_id}/code/decision", json={"kind": "changes", "by": "you"}
        )
        assert answer.status_code == 409
        assert "needs a note" in answer.text

    async def test_requesting_changes_regenerates_at_a_new_version(self, client) -> None:
        project_id, snapshot = await _generated(client)
        answer = await client.post(
            f"/projects/{project_id}/code/decision",
            json={"kind": "changes", "by": "you", "note": "narrow the contract"},
        )
        assert answer.status_code == 200
        await _advance_all(client, project_id)

        after = (await client.get(f"/projects/{project_id}/code")).json()
        assert after["codeVersion"] == snapshot["codeVersion"] + 1
        # The decision was about the version before this one, so this version
        # is undecided and the earlier decision is history. Asserted the other
        # way round until a reader found the consequence: a phase that had been
        # decided once reported that decision for ever, so the page drew no
        # decision bar and the run at the new version's gate waited for good.
        assert after["gate"]["decision"] is None
        assert [(h["kind"], h["version"]) for h in after["gate"]["history"]] == [
            ("changes", snapshot["codeVersion"])
        ]
        assert after["stages"]["code-review"]["status"] == "complete"

    async def test_a_decision_with_no_gate_waiting_refuses(self, client) -> None:
        project_id = await _project(client)
        answer = await client.post(
            f"/projects/{project_id}/code/decision", json={"kind": "approved", "by": "you"}
        )
        assert answer.status_code == 409
        assert "no code decision waiting" in answer.text


class TestTheDesignMovingOn:
    async def test_the_two_axes_are_reported_separately(self, client) -> None:
        """The staleness fact is arithmetic over two numbers, not a flag."""
        project_id, snapshot = await _generated(client)
        assert snapshot["designVersion"] == snapshot["generatedFromDesignVersion"]

        submitted = await client.post(
            f"/projects/{project_id}/design/changes",
            json={"note": "add a second entity", "by": "you"},
        )
        assert submitted.status_code == 200

        after = (await client.get(f"/projects/{project_id}/code")).json()
        assert after["designVersion"] == snapshot["designVersion"] + 1
        assert after["generatedFromDesignVersion"] == snapshot["generatedFromDesignVersion"]


class TestTheOpenApiExport:
    """The api-contract, served as OpenAPI.

    A translation of a stored artefact rather than a stored document, so it
    cannot drift from the contract it describes. C3 reads this to derive API
    test skeletons, which is why it is on the front door rather than passed
    between services some other way.
    """

    async def test_it_serves_a_document_that_validates(self, client) -> None:
        from openapi_spec_validator import validate

        project_id, snapshot = await _generated(client)
        answer = await client.get(f"/projects/{project_id}/code/openapi")

        assert answer.status_code == 200, answer.text
        document = answer.json()
        validate(document)
        assert document["openapi"] == "3.1.0"
        # The project's own name, so a reader opening it knows what it is.
        assert document["info"]["title"] == "Records"
        endpoints = snapshot["contract"]["contract"]["endpoints"]
        assert len(document["paths"]) >= 1
        served = {
            operation["operationId"]
            for methods in document["paths"].values()
            for operation in methods.values()
        }
        assert served == {endpoint["id"] for endpoint in endpoints}

    async def test_an_older_version_can_still_be_read(self, client) -> None:
        """The self healing classifier compares two of these, so both have to
        be reachable rather than only the newest."""
        project_id, snapshot = await _generated(client)
        at = snapshot["codeVersion"]
        answer = await client.get(f"/projects/{project_id}/code/openapi", params={"version": at})
        assert answer.status_code == 200, answer.text
        assert answer.json()["info"]["version"] == f"{at}.0.0"

    async def test_a_project_with_no_contract_says_so(self, client) -> None:
        project_id = await _project(client, approve=False)
        answer = await client.get(f"/projects/{project_id}/code/openapi")
        assert answer.status_code == 404
        assert "api-contract" in answer.text


class TestThePageWriter:
    async def test_the_frontend_stage_asks_for_it_with_what_the_design_says(self, client) -> None:
        """On, because the rule pages alone made every app the same form, and told
        what the requirements say, which is what tells a calculator from a form."""
        project_id, _ = await _generated(client)

        asked = client.app.state.c2.frontend_asked  # type: ignore[attr-defined]
        design = (await client.get(f"/projects/{project_id}/design")).json()

        assert asked["fill"] is True
        assert asked["requirements"] == [one["text"] for one in design["requirements"]]
        assert asked["requirements"], "the design has requirements to pass on"


class TestAnApprovedVersionIsNotReplacedUnasked:
    """Approved code is not replaced by a click that did not say so.

    "Generate again", a scope toggle and an arm choice all regenerated at a new
    code version whatever state the code was in: Cold Chain's approved v8 became
    v9, v10 and v11, and Testing and Deployment were left with nothing approved
    to run against. The server now refuses unless the request says to supersede
    the approved version, which the page asks for behind a confirmation.
    """

    async def _approved(self, client) -> tuple[str, int]:
        project_id, snapshot = await _generated(client)
        approved = await client.post(
            f"/projects/{project_id}/code/decision", json={"kind": "approved"}
        )
        assert approved.status_code == 200, approved.text
        # The approval resumes the run to its end; until then any new run is
        # refused as one in flight, which is not the refusal under test.
        await _advance_all(client, project_id)
        return project_id, snapshot["codeVersion"]

    async def test_generating_again_is_refused_and_says_why(self, client) -> None:
        project_id, version = await self._approved(client)

        answer = await client.post(f"/projects/{project_id}/code/generate")

        assert answer.status_code == 409
        assert answer.json()["detail"] == {"approvedVersion": version, "supersede": "required"}
        assert "Testing and Deployment" in answer.json()["error"]
        after = (await client.get(f"/projects/{project_id}/code")).json()
        assert after["codeVersion"] == version
        assert after["approvedThrough"] is None, "its own review approved it"

    async def test_a_version_a_fix_wrote_over_it_is_asked_about_too(self, client) -> None:
        """It has no review of its own and counts as approved when the version it
        patched was: Generate again over it replaced it unasked."""
        project_id, version = await self._approved(client)
        fixed = await _apply_a_fix(
            client, project_id, version, "apps/web/src/pages/FlowListPage.tsx"
        )

        answer = await client.post(f"/projects/{project_id}/code/generate")
        retried = await client.post(f"/projects/{project_id}/code/stages/frontend-code/retry")
        snapshot = (await client.get(f"/projects/{project_id}/code")).json()

        assert answer.status_code == 409
        assert answer.json()["detail"] == {"approvedVersion": fixed, "supersede": "required"}
        assert retried.status_code == 409
        assert f"code version {fixed} was approved, so its stages are settled" in retried.text
        # And the page is told, rather than reading it as undecided.
        assert snapshot["gate"]["decision"] is None
        assert snapshot["approvedThrough"] == version

    async def test_superseding_it_on_purpose_starts_a_new_version(self, client) -> None:
        project_id, version = await self._approved(client)

        answer = await client.post(
            f"/projects/{project_id}/code/generate", json={"supersede": True}
        )

        assert answer.status_code == 200
        await _advance_all(client, project_id)
        after = (await client.get(f"/projects/{project_id}/code")).json()
        assert after["codeVersion"] == version + 1

    async def test_a_scope_change_and_an_arm_choice_are_refused_too(self, client) -> None:
        project_id, version = await self._approved(client)
        story_id = (await client.get(f"/projects/{project_id}/code")).json()["scope"]["stories"][0][
            "id"
        ]

        scope = await client.post(
            f"/projects/{project_id}/code/scope/{story_id}", json={"inScope": False}
        )
        arm = await client.post(f"/projects/{project_id}/code/arm", json={"arm": "llm"})

        assert scope.status_code == arm.status_code == 409
        after = (await client.get(f"/projects/{project_id}/code")).json()
        assert after["codeVersion"] == version


class TestCodeComesFromTheApprovedDesign:
    """Code is generated from the current design version, approved and settled.

    The check asked whether the last design decision was an approval, and the
    run then read the newest design version: a change made after approval
    opened version 2 and a run that stopped at its own review, and "Generate
    again" built code from that version, which nobody had reviewed.
    """

    async def test_a_design_regenerating_after_approval_refuses_and_says_why(self, client) -> None:
        project_id = await _project(client)
        await client.post(
            f"/projects/{project_id}/design/changes", json={"note": "add a second entity"}
        )

        answer = await client.post(f"/projects/{project_id}/code/generate")
        snapshot = (await client.get(f"/projects/{project_id}/code")).json()

        assert answer.status_code == 409
        assert "the design is being regenerated at version 2" in answer.json()["error"]
        assert snapshot["designBlocker"] == answer.json()["error"]

    async def test_it_is_refused_until_the_new_version_is_approved(self, client) -> None:
        project_id = await _project(client)
        await client.post(
            f"/projects/{project_id}/design/changes", json={"note": "add a second entity"}
        )
        await _advance_all(client, project_id)

        waiting = await client.post(f"/projects/{project_id}/code/generate")
        await client.post(f"/projects/{project_id}/design/decision", json={"kind": "approved"})
        await _advance_all(client, project_id)
        approved = await client.post(f"/projects/{project_id}/code/generate")

        assert waiting.status_code == 409
        assert approved.status_code == 200, approved.text
        snapshot = (await client.get(f"/projects/{project_id}/code")).json()
        assert snapshot["designBlocker"] is None

    async def test_an_approval_still_settling_is_not_a_regeneration(self, client) -> None:
        """The run resumed with the approval stays active a few seconds while it
        finishes, and the page read that as a regeneration for up to a minute."""
        project_id = await _project(client)
        await client.post(
            f"/projects/{project_id}/design/changes", json={"note": "add a second entity"}
        )
        await _advance_all(client, project_id)
        await client.post(f"/projects/{project_id}/design/decision", json={"kind": "approved"})

        snapshot = (await client.get(f"/projects/{project_id}/code")).json()

        assert snapshot["designBlocker"] is None

    async def test_a_settled_approved_design_has_nothing_in_the_way(self, client) -> None:
        project_id = await _project(client)

        snapshot = (await client.get(f"/projects/{project_id}/code")).json()

        assert snapshot["designBlocker"] is None


class TestTheChosenArchitectureReachesTheCode:
    """The reviewer's architecture choice is what the code is built from.

    The choice is an overlay beside the stored recommendation, which carries
    none, and the code run read the stored one: the stack was proposed from the
    machine's pick whatever the reviewer chose. And the design snapshot read the
    first choice across every version, so after a regeneration a new choice was
    hidden behind the old one.
    """

    async def test_the_stack_is_proposed_from_the_chosen_architecture(self, client) -> None:
        project_id = await _project(client, approve=False)
        await client.post(
            f"/projects/{project_id}/design/architecture/select",
            json={"candidateId": "microservices"},
        )
        await client.post(f"/projects/{project_id}/design/decision", json={"kind": "approved"})
        await _advance_all(client, project_id)

        await client.post(f"/projects/{project_id}/code/generate")
        await _advance_all(client, project_id)

        asked = client.app.state.c2.stack_recommendation  # type: ignore[attr-defined]
        assert asked is not None
        assert asked.selected_candidate_id == "microservices"

    async def test_a_choice_belongs_to_the_version_it_was_made_at(self, client) -> None:
        project_id = await _project(client, approve=False)
        await client.post(
            f"/projects/{project_id}/design/architecture/select",
            json={"candidateId": "microservices"},
        )
        await client.post(
            f"/projects/{project_id}/design/decision",
            json={"kind": "changes", "note": "add a second entity"},
        )
        await _advance_all(client, project_id)

        regenerated = (await client.get(f"/projects/{project_id}/design")).json()
        await client.post(
            f"/projects/{project_id}/design/architecture/select",
            json={"candidateId": "monolith"},
        )
        chosen = (await client.get(f"/projects/{project_id}/design")).json()

        assert regenerated["requirementsVersion"] == 2
        assert regenerated["architecture"]["selectedCandidateId"] is None
        assert chosen["architecture"]["selectedCandidateId"] == "monolith"


class TestTheReviewersEditsReachTheCode:
    """A corrected requirement and a renamed node changed the page and nothing that
    was built: Code Generation read the artefacts as generated."""

    async def test_the_code_reads_the_corrected_requirement_and_the_renamed_node(
        self, client
    ) -> None:
        project_id = await _project(client, approve=False)
        design = (await client.get(f"/projects/{project_id}/design")).json()
        requirement = design["requirements"][0]["id"]
        node = design["graph"]["nodes"][0]["id"]
        corrected = await client.patch(
            f"/projects/{project_id}/design/requirements/{requirement}",
            json={"text": "Someone creates a record and names it."},
        )
        assert corrected.status_code == 200, corrected.text
        renamed = await client.patch(
            f"/projects/{project_id}/design/graph/nodes/{node}", json={"label": "Ledger Entry"}
        )
        assert renamed.status_code == 200, renamed.text
        await client.post(
            f"/projects/{project_id}/design/decision", json={"kind": "approved", "by": "you"}
        )
        await _advance_all(client, project_id)

        started = await client.post(f"/projects/{project_id}/code/generate")
        assert started.status_code == 200, started.text
        await _advance_all(client, project_id)

        c2 = client.app.state.c2  # type: ignore[attr-defined]
        assert "Someone creates a record and names it." in c2.frontend_asked["requirements"]
        assert "Ledger Entry" in c2.contract_graph_labels

    async def test_an_approved_design_is_not_edited(self, client) -> None:
        """An edit after the approval was kept, silently rewriting what was approved."""
        project_id = await _project(client)
        design = (await client.get(f"/projects/{project_id}/design")).json()
        requirement = design["requirements"][0]["id"]

        refused = await client.patch(
            f"/projects/{project_id}/design/requirements/{requirement}",
            json={"text": "Changed after the approval."},
        )

        assert refused.status_code == 409
        assert "is approved" in refused.json()["error"]
        again = (await client.get(f"/projects/{project_id}/design")).json()
        assert again["requirements"][0]["text"] == design["requirements"][0]["text"]


class TestTheProjectCard:
    """Every project was one blue, and none showed a stack: nothing wrote one."""

    async def test_a_project_shows_the_stack_its_code_phase_chose(self, client) -> None:
        project_id, _ = await _generated(client)

        listed = next(p for p in (await client.get("/projects")).json() if p["id"] == project_id)
        single = (await client.get(f"/projects/{project_id}")).json()

        assert listed["techStack"] == ["React", "Express", "MongoDB"]
        assert single["techStack"] == listed["techStack"]

        await client.post(
            f"/projects/{project_id}/code/stack/select",
            json={"stackId": "react-spring-postgres", "by": "you"},
        )
        chosen = (await client.get(f"/projects/{project_id}")).json()["techStack"]
        assert chosen == ["Spring Boot"], "the newest selection, as the code page reads it"

    async def test_each_project_has_a_colour_of_its_own_and_keeps_it(self, client) -> None:
        project_id = await _project(client, approve=False)
        async with client.app.state.pool.connection() as conn:
            await conn.execute(
                "UPDATE app.projects SET color = %s WHERE id = %s",
                (store.LEGACY_PROJECT_COLOR, project_id),
            )

        first = (await client.get(f"/projects/{project_id}")).json()["color"]
        again = (await client.get(f"/projects/{project_id}")).json()["color"]

        assert first == again == store.colour_for(project_id)
        assert first in store.PROJECT_PALETTE
        created = await _stored_colour(client, await _project(client, approve=False))
        assert created in store.PROJECT_PALETTE


async def _stored_colour(client, project_id: str) -> str:
    async with client.app.state.pool.connection() as conn:
        row = await store.get_project(conn, project_id, owner_id=DEV_OWNER_ID)
    return row["color"]


class TestRequestedChangesKeepTheTests:
    """Requesting changes at the code review regenerates at a new code version,
    and the tests written against this one come with it, as they do when the code
    is generated again. They were left behind, so the next testing run wrote
    every acceptance test from scratch and the healing loop had no earlier test
    to call stale."""

    async def test_the_tests_come_forward_to_the_regenerated_version(self, client) -> None:
        project_id, snapshot = await _generated(client)
        written = {"apps/api/src/__tests__/us-1.criteria.test.ts": "// a written test\n"}
        async with client.app.state.pool.connection() as conn:
            await store.put_code_files(
                conn,
                project_id,
                version=snapshot["codeVersion"],
                stage_id=store.TEST_FILE_STAGE,
                files=written,
            )

        decided = await client.post(
            f"/projects/{project_id}/code/decision",
            json={"kind": "changes", "by": "you", "note": "split the order endpoints"},
        )

        assert decided.status_code == 200, decided.text
        async with client.app.state.pool.connection() as conn:
            run = await store.latest_run(conn, project_id)
            assert run is not None
            following = run["requirements_version"]
            assert following > snapshot["codeVersion"]
            carried = await store.code_files(
                conn, project_id, version=following, stage_id=store.TEST_FILE_STAGE
            )
        assert carried == written
        trail = (await client.get("/audit", params={"project": project_id})).json()
        requested = next(e for e in trail if e["action"] == "Requested code changes")
        assert requested["detail"].endswith("1 test file came forward to the next version.")


async def _design_moved_on(client: httpx.AsyncClient, project_id: str) -> int:
    """A newer design version, approved while the code review waits on the older one."""
    changed = await client.post(
        f"/projects/{project_id}/design/changes",
        json={"note": "Add a second record type.", "by": "you"},
    )
    assert changed.status_code == 200, changed.text
    await _advance_all(client, project_id)
    decided = await client.post(
        f"/projects/{project_id}/design/decision", json={"kind": "approved", "by": "you"}
    )
    assert decided.status_code == 200, decided.text
    await _advance_all(client, project_id)
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        return await store.current_version(conn, project_id)


class TestAReviewTheDesignMovedPast:
    """A code review waiting while a newer design is approved is of code that
    no longer follows the design. Generating again resumed the waiting run,
    which reads the design version it began from, so the code came out of the
    older design while the page said generating again reads the newer one.
    Neither decision there helps: changes regenerate from the older design, and
    an approval sends code that no longer follows the design on."""

    async def test_generating_again_closes_it_and_reads_the_newer_design(self, client) -> None:
        project_id, snapshot = await _generated(client)
        async with client.app.state.pool.connection() as conn:
            waiting = await store.latest_run(conn, project_id)
        assert waiting is not None and waiting["component"] == "c2"
        newer = await _design_moved_on(client, project_id)
        assert newer > snapshot["generatedFromDesignVersion"]

        started = await client.post(f"/projects/{project_id}/code/generate")
        assert started.status_code == 200, started.text
        await _advance_all(client, project_id)

        after = (await client.get(f"/projects/{project_id}/code")).json()
        assert after["codeVersion"] > snapshot["codeVersion"]
        assert after["generatedFromDesignVersion"] == newer == after["designVersion"]
        async with client.app.state.pool.connection() as conn:
            closed = await store.get_run(conn, waiting["id"])
            history = await store.gate_history(conn, project_id, kind="c2-code-review")
        assert closed is not None and closed["state"] == "superseded"
        assert history[-1]["decision"] == "changes"
        assert f"design version {newer} has been approved since" in history[-1]["note"]
        trail = (await client.get("/audit", params={"project": project_id})).json()
        assert any(e["action"] == "Closed a review the phase moved past" for e in trail)

    async def test_requesting_changes_there_is_refused_and_says_what_to_do(self, client) -> None:
        """Changes would regenerate from the older design: generating again is the way on."""
        project_id, _ = await _generated(client)
        await _design_moved_on(client, project_id)

        refused = await client.post(
            f"/projects/{project_id}/code/decision",
            json={"kind": "changes", "by": "you", "note": "split the order endpoints"},
        )

        assert refused.status_code == 409
        assert "Generate again instead" in refused.text
        async with client.app.state.pool.connection() as conn:
            still = await store.pending_gate(conn, project_id=project_id, kind="c2-code-review")
        assert still is not None, "a refused change closed the review"

    async def test_approving_there_is_refused_too_and_says_what_to_do(self, client) -> None:
        """Approving announced "Testing and Security can start" and landed code that
        no longer follows the design on the default branch, while the project's
        status, which counts code only from the current design, ignored it."""
        project_id, _ = await _generated(client)
        newer = await _design_moved_on(client, project_id)

        refused = await client.post(
            f"/projects/{project_id}/code/decision",
            json={"kind": "approved", "by": "you", "note": "good enough to test"},
        )

        assert refused.status_code == 409
        assert "approving it would send code that no longer follows the design" in refused.text
        assert f"generates the code from version {newer}" in refused.text
        async with client.app.state.pool.connection() as conn:
            still = await store.pending_gate(conn, project_id=project_id, kind="c2-code-review")
        assert still is not None, "a refused approval closed the review"


class TestAnUnchangedPageIsKept:
    """Each regeneration hands C2 what the previous one made of each page, so a
    page whose inputs have not changed keeps it instead of being rewritten."""

    async def test_a_regeneration_is_handed_the_previous_generations_pages(self, client) -> None:
        project_id, snapshot = await _generated(client)
        assert client.app.state.c2.frontend_asked["earlier"] == [], "the first has none"

        decided = await client.post(
            f"/projects/{project_id}/code/decision",
            json={"kind": "changes", "by": "you", "note": "tidy the list"},
        )
        assert decided.status_code == 200, decided.text
        await _advance_all(client, project_id)

        [page] = client.app.state.c2.frontend_asked["earlier"]
        assert page.path == "apps/web/src/pages/FlowListPage.tsx"
        assert page.written_from == "canned-page" and page.generator == "rule"
        assert page.version == snapshot["codeVersion"]
        assert page.content.startswith("// screen: flow/list")

    async def test_a_version_a_fix_wrote_passes_on_the_pages_it_patched(self, client) -> None:
        """A fix version holds the patched files, not the pages as the generator
        wrote them, so the pages offered are those of the version it patched."""
        project_id, snapshot = await _generated(client)
        generated = snapshot["codeVersion"]
        await client.post(
            f"/projects/{project_id}/code/decision", json={"kind": "approved", "by": "you"}
        )
        await _advance_all(client, project_id)
        await _apply_a_fix(client, project_id, generated, "apps/web/src/pages/FlowListPage.tsx")

        # Approved through the version it patched, so replacing it is on purpose.
        again = await client.post(f"/projects/{project_id}/code/generate", json={"supersede": True})
        assert again.status_code == 200, again.text
        await _advance_all(client, project_id)

        [page] = client.app.state.c2.frontend_asked["earlier"]
        assert page.version == generated
        assert "patched" not in page.content, "the fix version's file was offered"


class TestAFixWhoseProposalCannotBeRead:
    async def test_it_is_said_not_carried_rather_than_guessed_at(self, client) -> None:
        """Which files a fix changed is read from its proposal. Without one, the
        files are left as generated and the review is told why."""
        project_id, snapshot = await _generated(client)
        await client.post(
            f"/projects/{project_id}/code/decision", json={"kind": "approved", "by": "you"}
        )
        await _advance_all(client, project_id)
        fixed = await _apply_a_fix(
            client, project_id, snapshot["codeVersion"], "apps/web/src/pages/FlowListPage.tsx"
        )

        await client.post(f"/projects/{project_id}/code/generate", json={"supersede": True})
        await _advance_all(client, project_id)

        async with client.app.state.pool.connection() as conn:
            said = [row["content"] for row in await store.thread(conn, project_id)]
        assert any(
            f"applied as code version {fixed} was not carried" in line
            and "its proposal could not be read at test version 1" in line
            for line in said
        ), said


async def _apply_a_fix(client, project_id: str, version: int, path: str) -> int:
    """What applying an accepted fix writes, as `apply_proposal` writes it: every
    file under one stage at the next version, the version's artefacts carried
    forward, and the decision naming both versions."""
    async with client.app.state.pool.connection() as conn:
        files = await store.code_files(conn, project_id, version=version)
        fixed = await store.next_code_version(conn, project_id)
        await store.put_code_files(
            conn,
            project_id,
            version=fixed,
            stage_id="backend-code",
            files={**files, path: files[path] + "// patched\n"},
        )
        found = await store.artefacts_at(
            conn, project_id, version=version, kinds=("code-repository", "api-contract")
        )
        for kind, row in found.items():
            body = dict(row["body"])
            if "version" in body:
                body["version"] = fixed
            await store.put_artefact(
                conn, project_id=project_id, kind=kind, version=fixed, body=body
            )
        await store.put_overlay(
            conn,
            project_id=project_id,
            version=1,
            kind="remediation_decision",
            target_id="fix-1",
            value={
                "decision": "accepted",
                "appliedCodeVersion": fixed,
                "patchedCodeVersion": version,
            },
            by="you",
        )
    return fixed


class TestWhatChangedSinceTheVersionBefore:
    """The code review showed no diff: nothing said what a new version changed
    (review item C2-8)."""

    async def test_the_first_version_has_nothing_before_it(self, client) -> None:
        project_id, snapshot = await _generated(client)

        changes = (await client.get(f"/projects/{project_id}/code/changes")).json()

        assert changes["version"] == snapshot["codeVersion"]
        assert changes["againstVersion"] is None and changes["files"] == []

    async def test_a_later_version_is_compared_with_the_one_before(self, client) -> None:
        project_id, snapshot = await _generated(client)
        version = snapshot["codeVersion"]
        async with client.app.state.pool.connection() as conn:
            files = await store.code_files(conn, project_id, version=version)
            path = sorted(files)[0]
            later = {**files, path: files[path] + "// changed\n", "apps/api/src/new.ts": "x\n"}
            await store.put_code_files(
                conn, project_id, version=version + 1, stage_id="backend-code", files=later
            )

        changes = (
            await client.get(
                f"/projects/{project_id}/code/changes", params={"version": version + 1}
            )
        ).json()

        assert (changes["version"], changes["againstVersion"]) == (version + 1, version)
        assert [(one["path"], one["status"]) for one in changes["files"]] == sorted(
            [(path, "changed"), ("apps/api/src/new.ts", "added")]
        )
        changed = next(one for one in changes["files"] if one["path"] == path)
        assert "+// changed" in changed["diff"]


class TestTheBuildIsOfTheGeneratedCode:
    """Testing's tests come forward to a regenerated version, beside the code.
    Code Generation's build read every file at the version, so it ran them and
    pushed them, though Push and Download leave them out (review item C2-11)."""

    async def test_the_build_neither_runs_nor_pushes_the_tests_testing_wrote(self, client) -> None:
        project_id, snapshot = await _generated(client)
        written = "apps/api/src/__tests__/us-1.criteria.test.ts"
        async with client.app.state.pool.connection() as conn:
            await store.put_code_files(
                conn,
                project_id,
                version=snapshot["codeVersion"],
                stage_id=store.TEST_FILE_STAGE,
                files={written: "// a written test\n"},
            )
        decided = await client.post(
            f"/projects/{project_id}/code/decision",
            json={"kind": "changes", "by": "you", "note": "split the order endpoints"},
        )
        assert decided.status_code == 200, decided.text

        await _advance_all(client, project_id)

        c2 = client.app.state.c2  # type: ignore[attr-defined]
        assert c2.calls.count("build") == 2
        assert written not in c2.built_paths
        assert written not in c2.pushed_paths[-1]
        # The build still has the code, and the tests are still the version's.
        assert any(path.startswith("apps/api/src/") for path in c2.built_paths)
        async with client.app.state.pool.connection() as conn:
            following = (await store.latest_run(conn, project_id))["requirements_version"]
            carried = await store.code_files(
                conn, project_id, version=following, stage_id=store.TEST_FILE_STAGE
            )
        assert written in carried


#: The rule arm's finding on the clinic project's contract, as it was recorded.
BOOK_APPOINTMENT = ContractRuleFinding(
    rule_id="screen-action-has-an-endpoint",
    severity="error",
    reason="screen flow-a1/s2 ('Book Appointment') is a form with 5 fields and no write endpoint traces to it",
    subject="flow-a1/s2",
)


def _artefact(*, chosen: str, rule_errors: int, llm_errors: int | None) -> ApiContractArtefact:
    """A contract artefact with this many errors in each arm; `None` for a failed model arm."""
    return ApiContractArtefact(
        version=1,
        rule_arm=CANNED_CONTRACT,
        llm_arm=CANNED_CONTRACT if llm_errors is not None else None,
        llm_failure=None if llm_errors is not None else "the model answered nothing usable",
        chosen=chosen,  # type: ignore[arg-type]
        contract=CANNED_CONTRACT,
        comparison=ArmComparison(
            rule=ArmCounts(endpoints=6, errors=rule_errors),
            llm=ArmCounts(endpoints=13, errors=llm_errors or 0),
        ),
        rule_findings=[BOOK_APPOINTMENT] * rule_errors,
    )


class TestWhatTheContractAsksOfAnApproval:
    """The errors in the arm the code was built from, said as the review says it."""

    def test_the_rule_arm_s_errors_are_named_with_the_first_reason(self) -> None:
        said = contract_concern(_artefact(chosen="rule", rule_errors=1, llm_errors=0))

        assert said is not None
        assert said.startswith("1 error in the API contract it was built from")
        assert "('Book Appointment') is a form with 5 fields" in said

    def test_it_says_when_the_other_contract_has_none(self) -> None:
        said = contract_concern(_artefact(chosen="rule", rule_errors=2, llm_errors=0))

        assert said is not None
        assert said.startswith("2 errors in the API contract it was built from")
        assert said.endswith("the AI model's contract has none")

    def test_it_says_nothing_of_a_model_arm_that_failed(self) -> None:
        said = contract_concern(_artefact(chosen="rule", rule_errors=1, llm_errors=None))

        assert said is not None
        assert "AI model's contract" not in said

    def test_the_model_arm_s_errors_count_when_it_was_chosen(self) -> None:
        said = contract_concern(_artefact(chosen="llm", rule_errors=0, llm_errors=3))

        assert said == (
            "3 errors in the API contract it was built from; the rule-based contract has none"
        )

    def test_a_contract_without_errors_asks_nothing(self) -> None:
        assert contract_concern(_artefact(chosen="rule", rule_errors=0, llm_errors=2)) is None
        assert contract_concern(None) is None

    def test_a_merged_contract_is_not_judged_by_either_arm(self) -> None:
        # Its endpoints are a person's pick from both, and neither arm's count is about it.
        assert contract_concern(_artefact(chosen="merged", rule_errors=2, llm_errors=2)) is None
