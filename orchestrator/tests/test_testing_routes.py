"""The testing routes: the read model, the guards, and the two decision tiers.

The spine test proves the graph walks. This proves what the browser can reach:
that a snapshot is composed from the rows without leaking another phase's, that
a run cannot be started on a build nobody approved, and that decisions at both
levels are recorded as overlays rather than as edits to the machine's output.

The decision tiers are this phase's own. C1 and C2 have one gate each; this one
has per finding and per proposal decisions inside the stage as well, because
the phase's output is a list of things that may still be wrong and a reader has
to be able to act on them one at a time.
"""

import contextlib
import re
import uuid
from collections.abc import AsyncIterator
from urllib.parse import quote

import httpx
import pytest
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.clients.canned import CANNED_TEST, CANNED_TEST_PATH, HONEST_REPAIR, CannedC3
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.graph.runner import RunSupervisor
from orchestrator.main import create_app, lifespan_for_tests
from orchestrator.patching import apply_to
from sdlc_contracts import CODE_GENERATING_STAGE_IDS, TEST_STAGE_IDS

from .conftest import needs_db
from .test_testing_spine import (
    _approve_test_review,
    _generated_code,
    _regenerated_code,
    _start_testing_run,
)

pytestmark = needs_db


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    async with _serving(create_app(settings, lifespan_factory=lifespan_for_tests)) as c:
        yield c


@pytest.fixture
async def red_client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    """A client whose canned suite fails when it runs, as Book Tracker's did."""
    app = create_app(settings, lifespan_factory=lifespan_for_tests)
    app.state.c3 = CannedC3(outcome="failed")
    async with _serving(app) as c:
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


async def _advance(client: httpx.AsyncClient, run_id) -> None:
    supervisor: RunSupervisor = client.app.state.supervisor  # type: ignore[attr-defined]
    await supervisor.advance(uuid.UUID(str(run_id)))


async def _project(client: httpx.AsyncClient) -> str:
    created = await client.post("/projects", json={"name": "Records", "description": ""})
    project_id = created.json()["id"]
    client.created_projects.append(project_id)  # type: ignore[attr-defined]
    return project_id


async def _through_code(client: httpx.AsyncClient, *, approve: bool = True) -> str:
    """A project with a code version, optionally approved."""
    project_id = await _project(client)
    await client.patch(
        f"/projects/{project_id}", json={"requirementText": "Someone creates a record."}
    )
    runs = (await client.get("/runs", params={"project": project_id})).json()
    await _advance(client, runs[0]["id"])
    await client.post(
        f"/projects/{project_id}/design/decision", json={"kind": "approved", "by": "you"}
    )
    await _advance(client, runs[0]["id"])

    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        design_version = await store.current_version(conn, project_id)
        code_version = await store.next_code_version(conn, project_id)
        await store.seed_code_stages(conn, project_id)
        await store.set_stages(
            conn, project_id, list(CODE_GENERATING_STAGE_IDS), status="generating"
        )
        code_run = await store.create_run(
            conn,
            project_id=project_id,
            requirements_version=code_version,
            component="c2",
            source_version=design_version,
        )
    await _advance(client, code_run["id"])

    if approve:
        decided = await client.post(
            f"/projects/{project_id}/code/decision", json={"kind": "approved", "by": "you"}
        )
        assert decided.status_code == 200, decided.text
        await _advance(client, code_run["id"])
    return project_id


class TestTheSnapshotBeforeAnythingHasRun:
    async def test_a_new_project_has_every_stage_pending(self, client) -> None:
        """The client indexes `stages[id]` for all seven with no null guard, so
        a project that has never reached this phase still answers with seven."""
        project_id = await _project(client)

        answer = await client.get(f"/projects/{project_id}/testing")

        assert answer.status_code == 200, answer.text
        body = answer.json()
        assert set(body["stages"]) == set(TEST_STAGE_IDS)
        assert all(stage["status"] == "pending" for stage in body["stages"].values())
        assert body["testVersion"] == 0

    async def test_nothing_is_claimed_before_it_exists(self, client) -> None:
        project_id = await _project(client)

        body = (await client.get(f"/projects/{project_id}/testing")).json()

        assert body["tests"] is None
        assert body["validation"] is None
        assert body["heal"] is None
        assert body["remediation"] is None
        assert body["openFindings"] == 0
        assert body["refusedRepairs"] == 0

    async def test_the_gate_starts_pending_rather_than_absent(self, client) -> None:
        project_id = await _project(client)

        body = (await client.get(f"/projects/{project_id}/testing")).json()

        assert body["gate"]["decision"] is None, "nobody has decided yet"
        assert body["gate"]["history"] == []

    async def test_another_project_s_testing_is_not_readable(self, client) -> None:
        answer = await client.get(f"/projects/{uuid.uuid4()}/testing")

        assert answer.status_code == 404


class TestStartingARun:
    async def test_untested_code_must_be_approved_first(self, client) -> None:
        """Testing an unapproved build measures something nobody agreed to
        ship, and the run costs minutes."""
        project_id = await _through_code(client, approve=False)

        answer = await client.post(f"/projects/{project_id}/testing/run")

        assert answer.status_code == 409
        assert "has not been approved" in answer.text

    async def test_an_approved_build_can_be_tested(self, client) -> None:
        project_id = await _through_code(client)

        answer = await client.post(f"/projects/{project_id}/testing/run")

        assert answer.status_code == 200, answer.text
        body = answer.json()
        # The version counter tracks artefacts written, not runs started, so a
        # run that has only just begun reports zero. Saying otherwise would
        # have the snapshot claim a version that nothing has been stored at.
        assert body["testVersion"] == 0
        assert body["stages"]["test-generation"]["status"] == "generating"

    async def test_the_version_appears_once_the_run_has_written_something(self, client) -> None:
        project_id = await _through_code(client)
        await client.post(f"/projects/{project_id}/testing/run")
        runs = (await client.get("/runs", params={"project": project_id})).json()
        await _advance(client, runs[0]["id"])

        body = (await client.get(f"/projects/{project_id}/testing")).json()

        assert body["testVersion"] == 1
        assert body["testedCodeVersion"] == 1
        assert body["codeMovedOn"] is False

    async def test_a_second_run_is_refused_while_one_is_in_flight(self, client) -> None:
        """Two graphs on one project's testing axis would write the same
        artefacts from two directions."""
        project_id = await _through_code(client)
        await client.post(f"/projects/{project_id}/testing/run")

        answer = await client.post(f"/projects/{project_id}/testing/run")

        assert answer.status_code == 409
        assert "already in flight" in answer.text

    async def test_a_project_with_no_code_cannot_be_tested(self, client) -> None:
        project_id = await _project(client)

        answer = await client.post(f"/projects/{project_id}/testing/run")

        assert answer.status_code == 409


class TestRetryingOneStage:
    async def test_the_gate_is_not_a_stage_to_re_run(self, client) -> None:
        project_id = await _through_code(client)
        await client.post(f"/projects/{project_id}/testing/run")

        answer = await client.post(f"/projects/{project_id}/testing/stages/test-review/retry")

        assert answer.status_code == 409
        assert "Decide it instead" in answer.text

    async def test_a_stage_that_does_not_exist_is_not_found(self, client) -> None:
        project_id = await _through_code(client)

        answer = await client.post(f"/projects/{project_id}/testing/stages/invented/retry")

        assert answer.status_code == 404

    async def test_nothing_to_retry_before_the_first_run(self, client) -> None:
        project_id = await _through_code(client)

        answer = await client.post(f"/projects/{project_id}/testing/stages/test-run/retry")

        assert answer.status_code == 409
        assert "nothing has been tested yet" in answer.text


async def _healed(client: httpx.AsyncClient, *, case_kind: str = "unit") -> tuple[str, int]:
    """A project tested at two code versions, so the second run's healing loop ran.

    The canned loop accepts one repair (`c1`: the expected total moved on
    purpose) and refuses one (`c2`: it asserts nothing that could fail).
    Returns the project and the code version the second run tested.
    """
    project_id, first_code = await _generated_code(client)
    first, _ = await _start_testing_run(client, project_id, first_code)
    await _advance(client, first["id"])
    await _approve_test_review(client, project_id)
    second_code = await _regenerated_code(client, project_id)
    client.app.state.c3.case_kind = case_kind  # type: ignore[attr-defined]
    second, _ = await _start_testing_run(client, project_id, second_code)
    await _advance(client, second["id"])
    return project_id, second_code


async def _stored_test(client: httpx.AsyncClient, project_id: str, code_version: int) -> str | None:
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        return await store.code_file(conn, project_id, version=code_version, path=CANNED_TEST_PATH)


class TestTheDecisionTierInsideTheStage:
    async def _tested(self, client) -> str:
        project_id = await _through_code(client)
        started = await client.post(f"/projects/{project_id}/testing/run")
        assert started.status_code == 200, started.text
        runs = (await client.get("/runs", params={"project": project_id})).json()
        await _advance(client, runs[0]["id"])
        return project_id

    async def test_dismissing_a_finding_needs_a_reason(self, client) -> None:
        """A security finding overruled without a note is the decision most
        worth reviewing and the one nobody can review."""
        project_id = await self._tested(client)

        answer = await client.post(
            f"/projects/{project_id}/testing/findings/CWE-89:a:1/decision",
            json={"decision": "dismissed", "by": "you"},
        )

        assert answer.status_code == 409
        assert "does not apply here" in answer.text

    async def test_accepting_a_finding_does_not(self, client) -> None:
        """Accepting is agreeing with the machine, whose reasoning is already
        on the artefact."""
        project_id = await self._tested(client)

        answer = await client.post(
            f"/projects/{project_id}/testing/findings/CWE-89:a:1/decision",
            json={"decision": "accepted", "by": "you"},
        )

        assert answer.status_code == 200, answer.text

    async def test_a_decision_is_an_overlay_not_an_edit(self, client) -> None:
        """The validation report stays exactly as the arms produced it. A
        precision computed over a report somebody edited measures the editing."""
        project_id = await self._tested(client)
        await client.post(
            f"/projects/{project_id}/testing/findings/CWE-89:a:1/decision",
            json={"decision": "dismissed", "by": "you", "note": "test fixture only"},
        )

        async with client.app.state.pool.connection() as conn:
            rows = await store.overlays(conn, project_id)

        decisions = [row for row in rows if row["kind"] == "finding_decision"]
        assert len(decisions) == 1
        assert decisions[0]["target_id"] == "CWE-89:a:1"
        assert decisions[0]["value"]["note"] == "test fixture only"
        # Recorded under the signed-in account, whatever the request said.
        assert decisions[0]["by"] == "Local development"

    async def test_dismissing_a_proposal_needs_a_reason_too(self, client) -> None:
        project_id = await self._tested(client)

        answer = await client.post(
            f"/projects/{project_id}/testing/remediation/fix-1/decision",
            json={"decision": "dismissed", "by": "you"},
        )

        assert answer.status_code == 409

    async def test_a_heal_can_be_kept_or_reverted_by_a_person(self, client) -> None:
        """The guard decides mechanically whether a repair may be accepted.
        This is what a person decides afterwards, and the two are different
        facts about the same repair."""
        project_id, _ = await _healed(client)

        answer = await client.post(
            f"/projects/{project_id}/testing/heals/c1/decision",
            json={"decision": "reverted", "by": "you", "note": "prefer to fix the code"},
        )

        assert answer.status_code == 200, answer.text
        async with client.app.state.pool.connection() as conn:
            rows = await store.overlays(conn, project_id)
        assert any(row["kind"] == "heal_decision" for row in rows)
        # And it is read back: the page changed nothing when it was not.
        [decided] = answer.json()["healDecisions"]
        assert decided["testId"] == "c1"
        assert decided["decision"] == "reverted"
        assert decided["note"] == "prefer to fix the code"

    async def test_the_report_lists_this_phases_audit_entries(self, client) -> None:
        """The report's audit section was the chat thread, which held few of the
        decisions; the snapshot now carries this phase's audit entries."""
        project_id, _ = await _healed(client)
        await client.post(
            f"/projects/{project_id}/testing/heals/c1/decision",
            json={"decision": "kept", "by": "you"},
        )

        snapshot = (await client.get(f"/projects/{project_id}/testing")).json()

        actions = [entry["action"] for entry in snapshot["audit"]]
        assert actions[0] == "Kept a healed test", "newest first"
        assert "Healed a stale test" in actions
        assert not any(action.startswith("Approved the design") for action in actions)

    async def test_the_same_heal_decision_twice_is_recorded_once(self, client) -> None:
        """Repeated clicks each wrote another audit entry saying the same thing."""
        project_id, _ = await _healed(client)
        decide = {"decision": "kept", "by": "you"}
        path = f"/projects/{project_id}/testing/heals/c1/decision"

        first = await client.post(path, json=decide)
        second = await client.post(path, json=decide)

        assert first.status_code == 200 and second.status_code == 200
        trail = (await client.get("/audit", params={"project": project_id})).json()
        assert [entry["action"] for entry in trail].count("Kept a healed test") == 1

    async def test_a_decision_before_anything_ran_is_refused(self, client) -> None:
        project_id = await _through_code(client)

        answer = await client.post(
            f"/projects/{project_id}/testing/findings/x/decision",
            json={"decision": "accepted", "by": "you"},
        )

        assert answer.status_code == 409
        assert "nothing has been scanned yet" in answer.text


class TestASecondRunWaitsForTheReview:
    """Running the tests again closes only a review the code has moved past; a
    review of the current code is decided first."""

    async def test_a_second_run_waits_for_the_first_review(self, client) -> None:
        project_id = await _through_code(client)
        started = await client.post(f"/projects/{project_id}/testing/run")
        assert started.status_code == 200, started.text
        runs = (await client.get("/runs", params={"project": project_id})).json()
        await _advance(client, runs[0]["id"])

        answer = await client.post(f"/projects/{project_id}/testing/run")

        assert answer.status_code == 409
        assert "testing review is waiting" in answer.text


class TestAKeptRepair:
    """Keeping a repair writes it into the test file the suite runs from.

    Until 2026-10-04 Keep and Revert were only recorded: the stored test file
    stayed the one that failed, so the next run, and Deployment's staging build,
    ran the stale test again whatever the reader had decided.
    """

    async def test_keeping_a_repair_writes_it_into_the_stored_test_file(self, client) -> None:
        project_id, code_version = await _healed(client)
        assert await _stored_test(client, project_id, code_version) == CANNED_TEST

        answer = await client.post(
            f"/projects/{project_id}/testing/heals/c1/decision",
            json={"decision": "kept", "by": "you"},
        )

        assert answer.status_code == 200, answer.text
        repaired = apply_to(CANNED_TEST, HONEST_REPAIR.diff)
        assert await _stored_test(client, project_id, code_version) == repaired
        trail = (await client.get("/audit", params={"project": project_id})).json()
        kept = next(entry for entry in trail if entry["action"] == "Kept a healed test")
        assert f"code version {code_version} now carries the repair" in kept["detail"]
        # And it outlives the version: the next code version starts from it.
        async with client.app.state.pool.connection() as conn:
            following = await store.next_code_version(conn, project_id)
            await store.carry_tests_forward(conn, project_id, to_version=following)
        assert await _stored_test(client, project_id, following) == repaired

    async def test_a_repair_cannot_be_kept_once_the_review_approved_the_tests(self, client) -> None:
        project_id, code_version = await _healed(client)
        await _approve_test_review(client, project_id)

        answer = await client.post(
            f"/projects/{project_id}/testing/heals/c1/decision",
            json={"decision": "kept", "by": "you"},
        )

        assert answer.status_code == 409
        assert "is approved with these tests" in answer.text
        assert await _stored_test(client, project_id, code_version) == CANNED_TEST

    async def test_reverting_a_kept_repair_puts_the_test_back(self, client) -> None:
        project_id, code_version = await _healed(client)
        path = f"/projects/{project_id}/testing/heals/c1/decision"
        await client.post(path, json={"decision": "kept", "by": "you"})

        answer = await client.post(
            path, json={"decision": "reverted", "by": "you", "note": "fix the code instead"}
        )

        assert answer.status_code == 200, answer.text
        assert await _stored_test(client, project_id, code_version) == CANNED_TEST

    async def test_reverting_a_repair_never_kept_changes_no_file(self, client) -> None:
        project_id, code_version = await _healed(client)

        answer = await client.post(
            f"/projects/{project_id}/testing/heals/c1/decision",
            json={"decision": "reverted", "by": "you"},
        )

        assert answer.status_code == 200, answer.text
        assert await _stored_test(client, project_id, code_version) == CANNED_TEST

    async def test_a_repair_the_guard_refused_cannot_be_kept(self, client) -> None:
        """A refusal is evidence about the model; writing it in would undo it."""
        project_id, code_version = await _healed(client)

        answer = await client.post(
            f"/projects/{project_id}/testing/heals/c2/decision",
            json={"decision": "kept", "by": "you"},
        )

        assert answer.status_code == 409
        assert "the guard refused this repair (kills-no-mutant)" in answer.text
        assert await _stored_test(client, project_id, code_version) == CANNED_TEST

    async def test_a_repair_to_an_api_test_cannot_be_kept(self, client) -> None:
        """Every run writes the API tests again from the contract, so a repair to
        one would not last, and its failure is the code's to answer for."""
        project_id, code_version = await _healed(client, case_kind="api")

        answer = await client.post(
            f"/projects/{project_id}/testing/heals/c1/decision",
            json={"decision": "kept", "by": "you"},
        )

        assert answer.status_code == 409
        assert "is an API test, which every run writes again from the contract" in answer.text
        assert await _stored_test(client, project_id, code_version) == CANNED_TEST

    async def test_a_repair_that_no_longer_applies_is_refused(self, client) -> None:
        """Exactly or not at all: a file that moved on is never patched near enough."""
        project_id, code_version = await _healed(client)
        moved = CANNED_TEST.replace("toBe(5)", "toBe(7)")
        async with client.app.state.pool.connection() as conn:
            await store.put_code_files(
                conn,
                project_id,
                version=code_version,
                stage_id=store.TEST_FILE_STAGE,
                files={CANNED_TEST_PATH: moved},
            )

        answer = await client.post(
            f"/projects/{project_id}/testing/heals/c1/decision",
            json={"decision": "kept", "by": "you"},
        )

        assert answer.status_code == 409
        assert "the repair no longer applies to" in answer.text
        assert await _stored_test(client, project_id, code_version) == moved

    async def test_a_test_the_loop_never_touched_has_nothing_to_decide(self, client) -> None:
        project_id, _ = await _healed(client)

        answer = await client.post(
            f"/projects/{project_id}/testing/heals/no-such-test/decision",
            json={"decision": "kept", "by": "you"},
        )

        assert answer.status_code == 404


#: The canned test as a real run names it: its file's path, then its name.
REAL_ID = f"{CANNED_TEST_PATH}::US-1 a person sees the result"


async def _red_review(client: httpx.AsyncClient) -> str:
    """A project waiting at a test review whose one generated test fails."""
    project_id = await _through_code(client)
    started = await client.post(f"/projects/{project_id}/testing/run")
    assert started.status_code == 200, started.text
    runs = (await client.get("/runs", params={"project": project_id})).json()
    await _advance(client, runs[0]["id"])
    return project_id


async def _passed_then_failed(client: httpx.AsyncClient) -> tuple[str, int, int]:
    """A project whose test passed at one code version and fails at the next."""
    project_id, first_code = await _generated_code(client)
    first, _ = await _start_testing_run(client, project_id, first_code)
    await _advance(client, first["id"])
    await _approve_test_review(client, project_id)
    second_code = await _regenerated_code(client, project_id)
    client.app.state.c3.outcome = "failed"  # type: ignore[attr-defined]
    second, _ = await _start_testing_run(client, project_id, second_code)
    await _advance(client, second["id"])
    return project_id, first_code, second_code


def _about(test_id: str) -> str:
    """A test id as the browser sends it: one encoded segment, slashes and all."""
    return quote(test_id, safe="")


class TestAFailingTestSetAside:
    """A model-written test that asserts what the code does not do failed for good.

    The review refuses approval while it fails, healing leaves a regression
    alone and has nothing to compare on a first run, and the generator keeps
    every written body, so one wrong test made a project unreleasable. A person
    now quarantines it with a reason, or sends a test that never passed back to
    be written again, and the file every later run and the staging build read
    says so.
    """

    async def test_quarantining_skips_it_in_its_file_and_lets_the_review_through(
        self, red_client
    ) -> None:
        project_id = await _red_review(red_client)

        answer = await red_client.post(
            f"/projects/{project_id}/testing/tests/c1/decision",
            json={"decision": "quarantined", "note": "asserts a total the design dropped"},
        )

        assert answer.status_code == 200, answer.text
        stored = await _stored_test(red_client, project_id, 1)
        assert stored is not None
        assert re.search(
            r"  // Quarantined by Local development on \d{4}-\d{2}-\d{2}: asserts a total the "
            r'design dropped\n  it\.skip\("a person sees the result"',
            stored,
        ), stored
        decided = answer.json()["healDecisions"]
        assert [(one["testId"], one["decision"]) for one in decided] == [("c1", "quarantined")]
        approved = await red_client.post(
            f"/projects/{project_id}/testing/decision", json={"kind": "approved"}
        )
        assert approved.status_code == 200, approved.text
        trail = (await red_client.get("/audit", params={"project": project_id})).json()
        assert any(entry["action"] == "Quarantined a test" for entry in trail)

    async def test_once_the_review_approves_the_tests_stay_as_approved(self, red_client) -> None:
        """A decision after the approval edited the file the approval covered, which
        Deployment's staging build reads (review item X-2): what shipped was not what
        a person approved."""
        project_id = await _red_review(red_client)
        path = f"/projects/{project_id}/testing/tests/c1/decision"
        await red_client.post(path, json={"decision": "quarantined", "note": "wrong total"})
        approved = await red_client.post(
            f"/projects/{project_id}/testing/decision", json={"kind": "approved"}
        )
        assert approved.status_code == 200, approved.text
        stored = await _stored_test(red_client, project_id, 1)

        answer = await red_client.post(path, json={"decision": "restored"})

        assert answer.status_code == 409
        assert "test version 1 is approved with these tests" in answer.text
        assert await _stored_test(red_client, project_id, 1) == stored

    async def test_a_quarantine_needs_a_reason(self, red_client) -> None:
        project_id = await _red_review(red_client)

        answer = await red_client.post(
            f"/projects/{project_id}/testing/tests/c1/decision",
            json={"decision": "quarantined"},
        )

        assert answer.status_code == 409
        assert "needs a note saying why" in answer.text
        assert await _stored_test(red_client, project_id, 1) == CANNED_TEST

    async def test_restoring_it_puts_the_file_back_and_holds_the_review_again(
        self, red_client
    ) -> None:
        project_id = await _red_review(red_client)
        path = f"/projects/{project_id}/testing/tests/c1/decision"
        await red_client.post(path, json={"decision": "quarantined", "note": "wrong total"})

        answer = await red_client.post(path, json={"decision": "restored"})

        assert answer.status_code == 200, answer.text
        assert await _stored_test(red_client, project_id, 1) == CANNED_TEST
        refused = await red_client.post(
            f"/projects/{project_id}/testing/decision", json={"kind": "approved"}
        )
        assert refused.status_code == 409
        assert "quarantine a test you judge wrong, with a reason" in refused.json()["error"]

    async def test_a_test_nobody_quarantined_cannot_be_restored(self, red_client) -> None:
        project_id = await _red_review(red_client)

        answer = await red_client.post(
            f"/projects/{project_id}/testing/tests/c1/decision", json={"decision": "restored"}
        )

        assert answer.status_code == 409
        assert "is not quarantined, so there is nothing to restore" in answer.text

    async def test_a_test_that_never_passed_goes_back_to_a_todo(self, red_client) -> None:
        """The next run's fill writes it afresh, so the review waits for that run."""
        project_id = await _red_review(red_client)

        answer = await red_client.post(
            f"/projects/{project_id}/testing/tests/c1/decision",
            json={"decision": "rewrite", "note": "checks the total, not what the person sees"},
        )

        assert answer.status_code == 200, answer.text
        stored = await _stored_test(red_client, project_id, 1)
        assert stored is not None
        assert 'it.todo("a person sees the result");' in stored
        assert "// To be written again, asked by Local development on " in stored
        assert "toBe(5)" not in stored, "the old body is gone"
        refused = await red_client.post(
            f"/projects/{project_id}/testing/decision", json={"kind": "approved"}
        )
        assert refused.status_code == 409

    async def test_an_api_test_is_quarantined_but_never_sent_back(self, red_client) -> None:
        """Every run writes the API tests again from the contract, so asking for
        one again changes nothing; C3 carries a quarantine across instead."""
        red_client.app.state.c3.case_kind = "api"  # type: ignore[attr-defined]
        project_id = await _red_review(red_client)
        path = f"/projects/{project_id}/testing/tests/c1/decision"

        sent_back = await red_client.post(path, json={"decision": "rewrite", "note": "wrong"})
        quarantined = await red_client.post(
            path, json={"decision": "quarantined", "note": "the contract is being changed"}
        )

        assert sent_back.status_code == 409
        assert "is an API test, which every run writes again from the contract" in sent_back.text
        assert quarantined.status_code == 200, quarantined.text

    async def test_a_test_that_passed_before_is_a_regression_not_a_wrong_test(self, client) -> None:
        project_id, _first, second_code = await _passed_then_failed(client)

        answer = await client.post(
            f"/projects/{project_id}/testing/tests/c1/decision",
            json={"decision": "rewrite", "note": "wrong"},
        )

        assert answer.status_code == 409
        assert "passed at test version 1, so it failing now is a regression" in answer.text
        assert await _stored_test(client, project_id, second_code) == CANNED_TEST

    async def test_nothing_is_decided_once_a_newer_code_version_has_its_own_copy(
        self, red_client
    ) -> None:
        """The decision would land in the older version's file and never reach
        the newer one, so the next run would measure the test as it was."""
        project_id = await _red_review(red_client)
        async with red_client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
            newer = await store.next_code_version(conn, project_id)
            await store.create_run(
                conn,
                project_id=project_id,
                requirements_version=newer,
                component="c2",
                source_version=1,
            )
            await store.carry_tests_forward(conn, project_id, to_version=newer)

        answer = await red_client.post(
            f"/projects/{project_id}/testing/tests/c1/decision",
            json={"decision": "quarantined", "note": "wrong total"},
        )

        assert answer.status_code == 409
        assert f"Run the tests on version {newer} first" in answer.text
        assert await _stored_test(red_client, project_id, 1) == CANNED_TEST

    async def test_a_kept_repair_and_a_quarantine_do_not_overlap(self, client) -> None:
        """One file, one decision about the test at a time: a kept repair is in
        the file, and a quarantined test has nothing for a repair to go into."""
        project_id, code_version = await _healed(client)
        heal = f"/projects/{project_id}/testing/heals/c1/decision"
        await client.post(heal, json={"decision": "kept"})

        quarantined = await client.post(
            f"/projects/{project_id}/testing/tests/c1/decision",
            json={"decision": "quarantined", "note": "wrong"},
        )

        assert quarantined.status_code == 409
        assert "Revert the repair first" in quarantined.text
        assert await _stored_test(client, project_id, code_version) == apply_to(
            CANNED_TEST, HONEST_REPAIR.diff
        )

    async def test_a_quarantined_test_s_repair_cannot_be_kept(self, client) -> None:
        project_id, _first, second_code = await _passed_then_failed(client)
        await client.post(
            f"/projects/{project_id}/testing/tests/c1/decision",
            json={"decision": "quarantined", "note": "wrong total"},
        )

        answer = await client.post(
            f"/projects/{project_id}/testing/heals/c1/decision", json={"decision": "kept"}
        )

        assert answer.status_code == 409
        assert "is quarantined, so its file skips the test this repair was made to" in answer.text
        stored = await _stored_test(client, project_id, second_code)
        assert stored is not None and "toBe(5)" in stored, "the repair was not written"


class TestARealTestId:
    """A real id is its file's path and its name. As one path segment it never
    reached a route: its slashes were decoded before the match, so keeping a
    repair answered 404 on every generated test."""

    async def test_it_reaches_the_repair_decision(self, client) -> None:
        client.app.state.c3.case_id = REAL_ID  # type: ignore[attr-defined]
        project_id, code_version = await _healed(client)

        kept = await client.post(
            f"/projects/{project_id}/testing/heals/{_about(REAL_ID)}/decision",
            json={"decision": "kept"},
        )

        assert kept.status_code == 200, kept.text
        assert await _stored_test(client, project_id, code_version) == apply_to(
            CANNED_TEST, HONEST_REPAIR.diff
        )

    async def test_it_reaches_the_test_decision(self, red_client) -> None:
        red_client.app.state.c3.case_id = REAL_ID  # type: ignore[attr-defined]
        project_id = await _red_review(red_client)

        quarantined = await red_client.post(
            f"/projects/{project_id}/testing/tests/{_about(REAL_ID)}/decision",
            json={"decision": "quarantined", "note": "wrong total"},
        )

        assert quarantined.status_code == 200, quarantined.text
        assert [one["testId"] for one in quarantined.json()["healDecisions"]] == [REAL_ID]


class TestARunThatProvedNothing:
    """Only a failed case held an approval up. A workspace that would not install
    returned a report with no tests in it, and approving it was one click that
    read as every proof passing."""

    async def _at_the_review(self, client) -> str:
        return await _red_review(client)

    async def test_no_test_ran_needs_a_note_to_approve(self, client) -> None:
        client.app.state.c3.outcome = "none"  # type: ignore[attr-defined]
        client.app.state.c3.run_steps = [("install", "failed")]  # type: ignore[attr-defined]
        project_id = await self._at_the_review(client)

        refused = await client.post(
            f"/projects/{project_id}/testing/decision", json={"kind": "approved"}
        )
        approved = await client.post(
            f"/projects/{project_id}/testing/decision",
            json={"kind": "approved", "note": "the install is fixed in the next sprint"},
        )

        assert refused.status_code == 409
        assert "no test ran: install failed" in refused.json()["error"]
        assert refused.json()["detail"] == {"concerns": ["no test ran: install failed"]}
        assert approved.status_code == 200, approved.text

    async def test_an_app_with_no_report_needs_a_note_too(self, client) -> None:
        client.app.state.c3.run_steps = [  # type: ignore[attr-defined]
            ("tests (apps/api)", "failed"),
            ("tests (apps/web)", "passed"),
        ]
        project_id = await self._at_the_review(client)

        refused = await client.post(
            f"/projects/{project_id}/testing/decision", json={"kind": "approved"}
        )

        assert refused.status_code == 409
        assert "apps/api produced no test report" in refused.json()["error"]

    async def test_criteria_left_unwritten_need_a_note_too(self, client) -> None:
        client.app.state.c3.outcome = "skipped"  # type: ignore[attr-defined]
        project_id = await self._at_the_review(client)

        refused = await client.post(
            f"/projects/{project_id}/testing/decision", json={"kind": "approved"}
        )

        assert refused.status_code == 409
        assert "1 acceptance criterion declared and not written" in refused.json()["error"]

    async def test_a_run_that_proved_everything_needs_no_note(self, client) -> None:
        project_id = await self._at_the_review(client)

        approved = await client.post(
            f"/projects/{project_id}/testing/decision", json={"kind": "approved"}
        )

        assert approved.status_code == 200, approved.text


class TestAQuarantineLasts:
    """A quarantine is in the file every later run carries, so it is in force
    until somebody restores the test, and the reader can find it to do that."""

    async def test_it_is_still_in_force_at_the_next_run_and_can_be_restored_there(
        self, red_client
    ) -> None:
        project_id = await _red_review(red_client)
        path = f"/projects/{project_id}/testing/tests/c1/decision"
        await red_client.post(path, json={"decision": "quarantined", "note": "wrong total"})
        rerun = await red_client.post(
            f"/projects/{project_id}/testing/decision",
            json={"kind": "changes", "note": "run them again"},
        )
        assert rerun.status_code == 200, rerun.text
        runs = (await red_client.get("/runs", params={"project": project_id})).json()
        await _advance(red_client, runs[0]["id"])

        snapshot = (await red_client.get(f"/projects/{project_id}/testing")).json()
        restored = await red_client.post(path, json={"decision": "restored"})

        assert snapshot["testVersion"] == 2
        outcomes = [
            case["outcome"] for suite in snapshot["tests"]["suites"] for case in suite["cases"]
        ]
        assert outcomes == ["skipped"], "the run that followed skipped it"
        assert [(one["testId"], one["decision"]) for one in snapshot["healDecisions"]] == [
            ("c1", "quarantined")
        ]
        assert restored.status_code == 200, restored.text
        assert await _stored_test(red_client, project_id, 1) == CANNED_TEST
        after = (await red_client.get(f"/projects/{project_id}/testing")).json()
        assert [one["decision"] for one in after["healDecisions"]] == ["restored"]


class TestThePhaseGate:
    async def test_there_is_nothing_to_decide_before_a_run(self, client) -> None:
        project_id = await _through_code(client)

        answer = await client.post(
            f"/projects/{project_id}/testing/decision", json={"kind": "approved", "by": "you"}
        )

        assert answer.status_code == 409
        assert "no testing decision waiting" in answer.text

    async def test_requesting_changes_needs_a_note(self, client) -> None:
        project_id = await _through_code(client)
        await client.post(f"/projects/{project_id}/testing/run")
        runs = (await client.get("/runs", params={"project": project_id})).json()
        await _advance(client, runs[0]["id"])

        answer = await client.post(
            f"/projects/{project_id}/testing/decision", json={"kind": "changes", "by": "you"}
        )

        assert answer.status_code == 409
        assert "needs a note" in answer.text

    async def test_changes_regenerate_the_tests_at_a_new_version(self, client) -> None:
        """Defect 27. The route resumed the run with a kind and a note but no
        version, and the gate refuses to guess one, because only the store
        allocates version numbers. So asking for changes failed the run instead
        of regenerating. The code gate always carried the version; this one
        now does the same."""
        project_id = await _through_code(client)
        await client.post(f"/projects/{project_id}/testing/run")
        runs = (await client.get("/runs", params={"project": project_id})).json()
        run_id = uuid.UUID(str(runs[0]["id"]))
        await _advance(client, run_id)

        answer = await client.post(
            f"/projects/{project_id}/testing/decision",
            json={"kind": "changes", "by": "you", "note": "cover the empty basket"},
        )
        assert answer.status_code == 200, answer.text
        await _advance(client, run_id)

        async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
            run = await store.get_run(conn, run_id)
            gate = await store.pending_gate(conn, project_id=project_id, kind="c3-test-review")
            regenerated = await store.artefacts_at(
                conn, project_id, version=2, kinds=("test-report",)
            )
        assert run is not None and run["state"] == "awaiting_gate", run
        assert gate is not None and gate["requirements_version"] == 2
        assert "test-report" in regenerated

    async def _approved(self, client) -> str:
        project_id = await _through_code(client)
        await client.post(f"/projects/{project_id}/testing/run")
        runs = (await client.get("/runs", params={"project": project_id})).json()
        await _advance(client, runs[0]["id"])
        approved = await client.post(
            f"/projects/{project_id}/testing/decision", json={"kind": "approved", "by": "you"}
        )
        assert approved.status_code == 200, approved.text
        return project_id

    async def test_an_approved_test_version_cannot_be_rewritten(self, client) -> None:
        """Defect 28. The store froze an approved design or code version and
        not a test version, so the report a person approved could be replaced
        underneath the approval, and C4 starts from exactly that approval."""
        project_id = await self._approved(client)

        async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
            with pytest.raises(store.VersionAlreadyApproved) as refused:
                await store.put_artefact(
                    conn, project_id=project_id, kind="validation-report", version=1, body={}
                )
        assert "was approved" in str(refused.value)

    async def test_a_stage_of_an_approved_version_is_not_retried(self, client) -> None:
        """Refused at the route, so an approved version never shows a stage
        that failed only because the store refused to overwrite it."""
        project_id = await self._approved(client)

        answer = await client.post(f"/projects/{project_id}/testing/stages/security-scan/retry")

        assert answer.status_code == 409
        assert "was approved" in answer.text

    async def test_an_approval_records_what_was_left_open(self, client) -> None:
        """An approval that reads as "everything was fine" over three open
        criticals is the audit entry this component exists to prevent."""
        project_id = await _through_code(client)
        await client.post(f"/projects/{project_id}/testing/run")
        runs = (await client.get("/runs", params={"project": project_id})).json()
        await _advance(client, runs[0]["id"])

        answer = await client.post(
            f"/projects/{project_id}/testing/decision", json={"kind": "approved", "by": "you"}
        )

        assert answer.status_code == 200, answer.text
        assert answer.json()["gate"]["decision"]["kind"] == "approved"
        entries = (await client.get("/audit", params={"project": project_id})).json()
        approvals = [row for row in entries if row["action"] == "Approved testing and security"]
        assert approvals, "the approval is audited"
        assert "findings open" in approvals[0]["target"]


class TestTheSnapshotDoesNotLeakOtherPhases:
    async def test_design_and_code_stages_stay_out_of_it(self, client) -> None:
        """`stage_states` holds every phase's rows, and `TestStageId` is a
        Literal over seven. An unfiltered build is a ValidationError on the
        first design row."""
        project_id = await _through_code(client)
        await client.post(f"/projects/{project_id}/testing/run")

        body = (await client.get(f"/projects/{project_id}/testing")).json()

        assert set(body["stages"]) == set(TEST_STAGE_IDS)

    async def test_the_code_phase_is_unchanged_by_a_testing_run(self, client) -> None:
        project_id = await _through_code(client)
        before = (await client.get(f"/projects/{project_id}/code")).json()

        await client.post(f"/projects/{project_id}/testing/run")

        after = (await client.get(f"/projects/{project_id}/code")).json()
        assert after["codeVersion"] == before["codeVersion"]
        assert set(after["stages"]) == set(before["stages"])


class TestADecisionBelongsToTheVersionItWasMadeAbout:
    """C2 records this as a bug that cost it: reporting the newest decision
    whatever its version means the phase never asks again. The page reads as
    decided, draws no decision bar, and the run waiting at its gate waits for
    good. Invisible until versions start accumulating.
    """

    async def _approved_then_moved_on(self, client) -> str:
        project_id = await _through_code(client)
        await client.post(f"/projects/{project_id}/testing/run")
        runs = (await client.get("/runs", params={"project": project_id})).json()
        await _advance(client, runs[0]["id"])
        approved = await client.post(
            f"/projects/{project_id}/testing/decision", json={"kind": "approved", "by": "you"}
        )
        assert approved.status_code == 200, approved.text
        await _advance(client, runs[0]["id"])

        # A second testing version, the way a second run produces one.
        async with client.app.state.pool.connection() as conn:
            version = await store.next_test_version(conn, project_id)
            await store.put_artefact(
                conn,
                project_id=project_id,
                kind="test-report",
                version=version,
                body={
                    "version": version,
                    "generatedAt": "2026-09-20T00:00:00Z",
                    "target": "records",
                    "isolation": "sandbox",
                    "suites": [],
                    "mutationSkippedReason": "not run in this pass",
                },
            )
        return project_id

    async def test_the_gate_asks_again_at_a_new_version(self, client) -> None:
        project_id = await self._approved_then_moved_on(client)

        answer = await client.get(f"/projects/{project_id}/testing")
        assert answer.status_code == 200, answer.text
        body = answer.json()

        assert body["testVersion"] == 2
        assert body["gate"]["decision"] is None, (
            "version 2 has not been decided, and reading version 1's approval here "
            "is how a run waits at its gate for ever"
        )

    async def test_the_earlier_approval_is_still_in_the_history(self, client) -> None:
        """It is not discarded. It was a real decision about a real version,
        and the audit needs it."""
        project_id = await self._approved_then_moved_on(client)

        body = (await client.get(f"/projects/{project_id}/testing")).json()

        assert [row["kind"] for row in body["gate"]["history"]] == ["approved"]
        assert body["gate"]["history"][0]["version"] == 1


class TestTheReviewWaitsForGreenTests:
    """What Book Tracker met. Its test run said "23 passed, 1 failed", the review
    was approved anyway with a note that counted only security findings, and
    Deployment's staging build then ran the same tests and refused the
    candidate. An approval that can only end in that refusal is refused here
    instead, where the person can still act on it."""

    async def _at_the_review(self, client) -> str:
        project_id = await _through_code(client)
        started = await client.post(f"/projects/{project_id}/testing/run")
        assert started.status_code == 200, started.text
        runs = (await client.get("/runs", params={"project": project_id})).json()
        await _advance(client, runs[0]["id"])
        return project_id

    async def test_approval_is_refused_while_a_test_fails(self, red_client) -> None:
        project_id = await self._at_the_review(red_client)

        answer = await red_client.post(
            f"/projects/{project_id}/testing/decision", json={"kind": "approved", "by": "you"}
        )

        assert answer.status_code == 409
        body = answer.json()
        assert '1 test fails in this run, starting with "a person sees the result"' in body["error"]
        assert "staging build runs these same tests" in body["error"]
        assert body["detail"] == [{"test": "a person sees the result"}]
        snapshot = (await red_client.get(f"/projects/{project_id}/testing")).json()
        assert snapshot["gate"]["decision"] is None, "nothing was decided"

    async def test_switching_the_target_does_not_hide_the_runs_failures(self, red_client) -> None:
        """The check read the newest target choice, which may be changed while a
        review waits: choosing a sample emptied the failing list and the
        approval of the generated app's failing run went through. What counts is
        what the run measured, which its report names."""
        project_id = await self._at_the_review(red_client)
        offered = (await red_client.get(f"/projects/{project_id}/testing/targets")).json()
        sample = next(row["id"] for row in offered if row["id"] != "generated")
        switched = await red_client.post(
            f"/projects/{project_id}/testing/target", json={"target": sample}
        )
        assert switched.status_code == 200, switched.text

        answer = await red_client.post(
            f"/projects/{project_id}/testing/decision", json={"kind": "approved"}
        )

        assert answer.status_code == 409
        assert (
            '1 test fails in this run, starting with "a person sees the result"'
            in (answer.json()["error"])
        )

    async def test_changes_can_still_be_requested(self, red_client) -> None:
        project_id = await self._at_the_review(red_client)

        answer = await red_client.post(
            f"/projects/{project_id}/testing/decision",
            json={"kind": "changes", "by": "you", "note": "Write the acceptance tests again."},
        )

        assert answer.status_code == 200, answer.text

    async def test_a_green_run_is_approved(self, client) -> None:
        project_id = await self._at_the_review(client)

        answer = await client.post(
            f"/projects/{project_id}/testing/decision", json={"kind": "approved", "by": "you"}
        )

        assert answer.status_code == 200, answer.text

    async def test_a_sample_s_seeded_failures_do_not_hold_its_review(self, red_client) -> None:
        """A sample fails on purpose: its failures are what the healing loop is
        measured on, and nothing deploys a sample."""
        project_id = await _through_code(red_client)
        async with red_client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
            await store.put_overlay(
                conn,
                project_id=project_id,
                version=1,
                kind="target_selection",
                target_id="target",
                value="sample:java",
                by="you",
            )
        started = await red_client.post(f"/projects/{project_id}/testing/run")
        assert started.status_code == 200, started.text
        runs = (await red_client.get("/runs", params={"project": project_id})).json()
        await _advance(red_client, runs[0]["id"])

        answer = await red_client.post(
            f"/projects/{project_id}/testing/decision", json={"kind": "approved", "by": "you"}
        )

        assert answer.status_code == 200, answer.text
