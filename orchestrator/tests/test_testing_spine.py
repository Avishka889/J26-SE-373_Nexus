"""The testing phase, driven end to end against a real database.

The claim these hold to account: a testing run walks six stages, writes its
artefacts on its own version axis, pauses at a gate of its own kind, and leaves
the design and code phases beside it untouched. The component is canned,
because none of that is more true for having spent ten minutes running a real
mutation pass; what the component produces is proved where the component lives.

One thing here is not C2's. The report a run leaves behind changes shape three
times: generation writes it with every case at `not-run`, execution replaces
the outcomes, and quality adds the mutation result. Each of those is true when
it is written, and the test that matters most is the one asserting the first
one is `not-run` rather than empty or absent.
"""

import uuid
from collections.abc import AsyncIterator
from typing import ClassVar

import httpx
import pytest
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.graph.runner import RunSupervisor
from orchestrator.main import create_app, lifespan_for_tests
from sdlc_contracts import (
    CODE_GENERATING_STAGE_IDS,
    TEST_GENERATING_STAGE_IDS,
    TEST_STAGE_IDS,
    ClassificationEvidence,
    HealAttempt,
    HealReport,
    TestGap,
    TestReport,
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


async def _advance(client: httpx.AsyncClient, run_id) -> None:
    supervisor: RunSupervisor = client.app.state.supervisor  # type: ignore[attr-defined]
    await supervisor.advance(uuid.UUID(str(run_id)))


async def _generated_code(client: httpx.AsyncClient) -> tuple[str, int]:
    """A project with an approved design and one code version, C3's input.

    Started the way `test_code_spine` starts a code run rather than through the
    route, for the same reason that file does: this is the graph under test,
    and the route's own guards are proved where the route lives.
    """
    created = await client.post("/projects", json={"name": "Records", "description": ""})
    project_id = created.json()["id"]
    client.created_projects.append(project_id)  # type: ignore[attr-defined]
    await client.patch(
        f"/projects/{project_id}", json={"requirementText": "Someone creates a record."}
    )
    runs = (await client.get("/runs", params={"project": project_id})).json()
    await _advance(client, runs[0]["id"])
    decided = await client.post(
        f"/projects/{project_id}/design/decision", json={"kind": "approved", "by": "you"}
    )
    assert decided.status_code == 200, decided.text
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
    return project_id, code_version


async def _approve_test_review(client: httpx.AsyncClient, project_id: str) -> None:
    """Answer the testing gate, so the run finishes and the phase is free.

    One pending gate per project per kind, so a second testing run cannot open
    its review while the first is still waiting. That is the rule, not a
    limitation to work around: two open test reviews on one project would be
    two decisions about the same thing.
    """
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        gate = await store.pending_gate(conn, project_id=project_id, kind="c3-test-review")
        assert gate is not None, "the testing run should be waiting at its gate"
        await store.resolve_gate(conn, gate["id"], decision="approved", by="you", note="")
        await store.set_run_state(
            conn, gate["run_id"], "queued", resume_payload={"kind": "approved"}
        )
    await _advance(client, gate["run_id"])


async def _regenerated_code(client: httpx.AsyncClient, project_id: str) -> int:
    """A second code version, made the way the code route makes one.

    Requesting changes resumes the run that is waiting at the code gate rather
    than starting a new one, so the run row has to be pointed at the version it
    now produces. C3 depends on that: it finds the design version behind a code
    version by asking which C2 run produced it.
    """
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        gate = await store.pending_gate(conn, project_id=project_id, kind="c2-code-review")
        assert gate is not None, "the first code run should be waiting at its gate"
        await store.resolve_gate(
            conn, gate["id"], decision="changes", by="you", note="add the history view"
        )
        version = await store.next_code_version(conn, project_id)
        await store.set_run_version(conn, gate["run_id"], version)
        await store.set_run_state(
            conn,
            gate["run_id"],
            "queued",
            resume_payload={"kind": "changes", "note": "add the history view", "version": version},
        )
    await _advance(client, gate["run_id"])
    return version


async def _start_testing_run(client: httpx.AsyncClient, project_id: str, code_version: int):
    """What the testing route will do, in one place, so this file tests the graph."""
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        test_version = await store.next_test_version(conn, project_id)
        await store.seed_test_stages(conn, project_id)
        await store.set_stages(
            conn, project_id, list(TEST_GENERATING_STAGE_IDS), status="generating"
        )
        run = await store.create_run(
            conn,
            project_id=project_id,
            requirements_version=test_version,
            component="c3",
            source_version=code_version,
        )
    return run, test_version


async def _request_test_changes(client: httpx.AsyncClient, project_id: str) -> int:
    """Changes at the test review, as the route asks for them: a new test
    version at the same code version, on the run that was waiting."""
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        gate = await store.pending_gate(conn, project_id=project_id, kind="c3-test-review")
        assert gate is not None, "the testing run should be waiting at its gate"
        await store.resolve_gate(conn, gate["id"], decision="changes", by="you", note="again")
        version = await store.next_test_version(conn, project_id)
        await store.set_run_version(conn, gate["run_id"], version)
        await store.set_run_state(
            conn,
            gate["run_id"],
            "queued",
            resume_payload={"kind": "changes", "note": "again", "version": version},
        )
    await _advance(client, gate["run_id"])
    return version


async def _stages(client: httpx.AsyncClient, project_id: str) -> dict[str, dict]:
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        rows = await store.stage_states(conn, project_id)
    return {row["stage_id"]: row for row in rows}


class TestAWholeTestingRun:
    async def test_it_walks_every_stage_and_stops_at_its_own_gate(self, client) -> None:
        project_id, code_version = await _generated_code(client)
        run, test_version = await _start_testing_run(client, project_id, code_version)

        await _advance(client, run["id"])

        stages = await _stages(client, project_id)
        produced = [stage for stage in TEST_STAGE_IDS if stage != "test-review"]
        assert [stages[stage]["status"] for stage in produced] == ["complete"] * len(produced), {
            stage: stages[stage]["error"]
            for stage in produced
            if stages[stage]["status"] == "failed"
        }
        # The gate stage is complete too: reaching it is what makes the review
        # readable, and the runner writes that, not a node.
        assert stages["test-review"]["status"] == "complete"

        async with client.app.state.pool.connection() as conn:
            stored = await store.get_run(conn, run["id"])
            gate = await store.pending_gate(conn, project_id=project_id, kind="c3-test-review")
        assert stored["state"] == "awaiting_gate"
        assert gate is not None
        assert str(gate["run_id"]) == str(run["id"])
        assert gate["requirements_version"] == test_version
        assert gate["payload"]["codeVersion"] == code_version

    async def test_each_stage_says_what_it_did_in_the_conversation(self, client) -> None:
        """Design and Code write each stage's summary to their thread. Testing
        wrote none: its conversation was empty after a whole run, and the same
        events could be read only as the audit log's notes (found on the live
        clinic project, 2026-10-13)."""
        project_id, code_version = await _generated_code(client)
        run, _ = await _start_testing_run(client, project_id, code_version)

        await _advance(client, run["id"])

        snapshot = (await client.get(f"/projects/{project_id}/testing")).json()
        said = [one for one in snapshot["thread"] if one["kind"] == "stage_summary"]
        produced = [stage for stage in TEST_STAGE_IDS if stage != "test-review"]
        # One for every stage the run finished, oldest first as the panel reads.
        assert sorted(one["stageId"] for one in said) == sorted(produced)
        assert {one["author"] for one in said} == {"Testing agent"}
        assert [one["at"] for one in said] == sorted(one["at"] for one in said)
        # And each is the stage's own summary, not a second wording of it.
        for one in said:
            assert one["content"] == snapshot["stages"][one["stageId"]]["summary"]

    async def test_every_stage_was_asked_for_in_order(self, client) -> None:
        project_id, code_version = await _generated_code(client)
        canned = client.app.state.c3
        canned.calls.clear()
        run, _ = await _start_testing_run(client, project_id, code_version)

        await _advance(client, run["id"])

        assert canned.calls == [
            "test-generation",
            "test-run",
            "test-quality",
            "security-scan",
            "remediation",
        ], "self-healing is absent because there is no earlier tested version to compare against"

    async def test_the_artefacts_land_on_the_testing_axis(self, client) -> None:
        project_id, code_version = await _generated_code(client)
        run, test_version = await _start_testing_run(client, project_id, code_version)

        await _advance(client, run["id"])

        async with client.app.state.pool.connection() as conn:
            at = await store.artefacts_at(
                conn,
                project_id,
                version=test_version,
                kinds=("test-report", "validation-report", "remediation-proposal"),
            )
        assert set(at) == {"test-report", "validation-report", "remediation-proposal"}
        # And the code axis is untouched by any of it.
        async with client.app.state.pool.connection() as conn:
            code = await store.artefacts_at(
                conn, project_id, version=code_version, kinds=("api-contract",)
            )
        assert "api-contract" in code


class TestTheReportIsTrueAtEveryStage:
    """Three writers, and each writes something true when it writes it."""

    async def test_generation_leaves_the_cases_not_run(self, client) -> None:
        """Not empty, not absent, not passed: generated and unexecuted.

        The distinction this whole component argues for, in the one place it is
        cheapest to get wrong.
        """
        project_id, code_version = await _generated_code(client)
        run, test_version = await _start_testing_run(client, project_id, code_version)
        supervisor: RunSupervisor = client.app.state.supervisor  # type: ignore[attr-defined]

        # Only the first stage, by running the node directly rather than the run.
        from orchestrator.graph.testing_graph import STAGE_NODES

        node = STAGE_NODES["test-generation"](client.app.state.pool, client.app.state.c3)
        await node(
            {
                "project_id": project_id,
                "run_id": str(run["id"]),
                "test_version": test_version,
                "code_version": code_version,
                "attempt": 0,
            }
        )
        assert supervisor is not None

        async with client.app.state.pool.connection() as conn:
            at = await store.artefacts_at(
                conn, project_id, version=test_version, kinds=("test-report",)
            )
        report = TestReport.model_validate(at["test-report"]["body"])
        assert report.total == 1
        assert report.not_run == 1
        assert report.passed == 0 and report.failed == 0

    async def test_the_run_stage_is_handed_what_the_generation_stage_wrote(self, client) -> None:
        """Or the traces do not survive the stage that replaces the report.

        Both stages write `test-report` at the same version and the write is an
        upsert. Generation's report says what each test was written from, because
        the rules that wrote it knew; the run stage's is built from the runner's
        output, and a runner knows nothing about stories or criteria. So unless
        the earlier report is read before the later one lands and handed back,
        the traces are not merely missing from the result, they are destroyed by
        the stage that replaced them.

        That disabled the healing classifier on every run through here, silently:
        its first signal is what a failing test traces to, and an empty trace is
        an honest `undecided` rather than a wrong answer, so nothing failed and
        nothing said anything.

        `CannedC3` cannot show the consequence, because its run report is traced
        by construction where a real runner's is not. What this asserts is the
        part the orchestrator owns: that the declaration reached the stage.
        """
        project_id, code_version = await _generated_code(client)
        run, test_version = await _start_testing_run(client, project_id, code_version)
        component = client.app.state.c3  # type: ignore[attr-defined]
        seen: list[TestReport | None] = []
        original = component.run_tests

        async def recording(target, *, version: int, declared: TestReport | None = None):
            seen.append(declared)
            return await original(target, version=version, declared=declared)

        component.run_tests = recording

        from orchestrator.graph.testing_graph import STAGE_NODES

        state = {
            "project_id": project_id,
            "run_id": str(run["id"]),
            "test_version": test_version,
            "code_version": code_version,
            "attempt": 0,
        }
        for stage in ("test-generation", "test-run"):
            await STAGE_NODES[stage](client.app.state.pool, component)(state)

        assert seen and seen[0] is not None, "the run stage was given nothing to trace back to"
        declared = seen[0]
        assert declared.total > 0
        assert declared.untraced == 0, (
            "the generation stage wrote cases with nothing to trace to, so there "
            "would be nothing for the run stage to put back"
        )

    async def test_the_generated_tests_are_stored_beside_the_code(self, client) -> None:
        """A generated test belongs in the repository it tests, so it goes in
        the same file store at the same code version, under its own stage."""
        project_id, code_version = await _generated_code(client)
        run, _ = await _start_testing_run(client, project_id, code_version)

        await _advance(client, run["id"])

        async with client.app.state.pool.connection() as conn:
            content = await store.code_file(
                conn,
                project_id,
                version=code_version,
                path="apps/web/src/__tests__/generated.test.ts",
            )
        assert content is not None


class TestWhatNoTestCanAssertStaysOnTheReport:
    """The generation stage names the contract obligations nothing can test.

    Two later stages replace the report at the same version. What the generator
    alone knows has to come through both, or the page that says what was
    generated cannot say what was not (the live clinic project, 2026-10-13).
    """

    _GAPS: ClassVar[list[TestGap]] = [
        TestGap(
            endpoint_id="post-records-id-manage",
            kind="no-way-to-create",
            detail="the contract declares POST /records/{id}/manage and no POST on /records",
        ),
        TestGap(
            endpoint_id="post-records-id-manage",
            kind="auth-not-implemented",
            detail="the contract restricts this to Clerk and the application has no sign-in",
        ),
    ]

    async def test_the_run_and_quality_stages_keep_them(self, client) -> None:
        project_id, code_version = await _generated_code(client)
        client.app.state.c3.gaps = list(self._GAPS)
        try:
            run, test_version = await _start_testing_run(client, project_id, code_version)
            await _advance(client, run["id"])
        finally:
            client.app.state.c3.gaps = []

        async with client.app.state.pool.connection() as conn:
            at = await store.artefacts_at(
                conn, project_id, version=test_version, kinds=("test-report",)
            )
        report = TestReport.model_validate(at["test-report"]["body"])
        assert report.mutation is not None, "the quality stage has replaced the report"
        assert report.gaps == self._GAPS

    async def test_the_page_is_given_them(self, client) -> None:
        project_id, code_version = await _generated_code(client)
        client.app.state.c3.gaps = list(self._GAPS)
        try:
            run, _ = await _start_testing_run(client, project_id, code_version)
            await _advance(client, run["id"])
        finally:
            client.app.state.c3.gaps = []

        snapshot = (await client.get(f"/projects/{project_id}/testing")).json()

        assert [gap["kind"] for gap in snapshot["tests"]["gaps"]] == [
            "no-way-to-create",
            "auth-not-implemented",
        ]
        assert snapshot["tests"]["gaps"][0]["endpointId"] == "post-records-id-manage"

    async def test_the_audit_log_counts_them_by_kind(self, client) -> None:
        project_id, code_version = await _generated_code(client)
        client.app.state.c3.gaps = list(self._GAPS)
        try:
            run, _ = await _start_testing_run(client, project_id, code_version)
            await _advance(client, run["id"])
        finally:
            client.app.state.c3.gaps = []

        snapshot = (await client.get(f"/projects/{project_id}/testing")).json()
        [generated] = [
            one for one in snapshot["audit"] if one["action"] == "Generated Test Generation"
        ]

        assert "gaps: no-way-to-create 1; auth-not-implemented 1" in generated["detail"]
        assert "the contract declares" not in generated["detail"]


class TestAFixIsProposedKnowingTheTestsAndTheContract:
    """Every live fix's risk statement said no test covers its lines and no
    endpoint's contract moves, because the remediation stage handed C3 the scan
    and nothing else: the risk is counted from the run's tests and the contract,
    and both were absent, so both counted zero (review item C3-11)."""

    async def test_the_remediation_stage_is_handed_both(self, client) -> None:
        project_id, code_version = await _generated_code(client)
        run, test_version = await _start_testing_run(client, project_id, code_version)
        component = client.app.state.c3  # type: ignore[attr-defined]
        seen: dict[str, object] = {}
        original = component.propose_remediation

        async def recording(target, report, *, tests=None, contract=None):
            seen.update(tests=tests, contract=contract)
            return await original(target, report, tests=tests, contract=contract)

        component.propose_remediation = recording

        from orchestrator.graph.testing_graph import STAGE_NODES

        state = {
            "project_id": project_id,
            "run_id": str(run["id"]),
            "test_version": test_version,
            "code_version": code_version,
            "attempt": 0,
        }
        for stage in ("test-generation", "test-run", "security-scan", "remediation"):
            await STAGE_NODES[stage](client.app.state.pool, component)(state)

        tests, contract = seen.get("tests"), seen.get("contract")
        assert isinstance(tests, TestReport) and tests.total > 0, "no tests to count coverage from"
        assert contract is not None and contract.endpoints, "no contract to see an endpoint move"


class TestTheTestsFollowTheBuild:
    """The acceptance tests are for the stories the code was built for.

    They followed the sprint plan's proposed list whatever the build held: a
    backlog story a person moved into the build got no acceptance tests, and a
    proposed one moved out kept tests for a feature the code did not have.
    """

    async def test_a_story_moved_in_gets_tests_and_one_moved_out_gets_none(self, client) -> None:
        client.app.state.c1.backlog = 1  # US-2 waits in the backlog
        project_id, _first = await _generated_code(client)
        async with client.app.state.pool.connection() as conn:
            for story_id, in_scope in (("US-2", True), ("US-1", False)):
                await store.put_overlay(
                    conn,
                    project_id=project_id,
                    version=1,
                    kind="story_scope",
                    target_id=story_id,
                    value=in_scope,
                    by="you",
                )
        second = await _regenerated_code(client, project_id)
        client.app.state.c3.sprints.clear()

        run, _ = await _start_testing_run(client, project_id, second)
        await _advance(client, run["id"])

        [given] = client.app.state.c3.sprints
        assert [story.id for story in given.proposed] == ["US-2"]
        assert [story.id for story in given.backlog] == ["US-1"]
        assert given.estimated_points == 8

    async def test_an_unchanged_scope_is_the_plan_as_proposed(self, client) -> None:
        client.app.state.c1.backlog = 1
        project_id, code_version = await _generated_code(client)

        run, _ = await _start_testing_run(client, project_id, code_version)
        await _advance(client, run["id"])

        [given] = client.app.state.c3.sprints
        assert [story.id for story in given.proposed] == ["US-1"]
        assert [story.id for story in given.backlog] == ["US-2"]

    async def test_a_fixed_version_is_tested_for_what_the_version_it_patched_built(
        self, client
    ) -> None:
        """An applied fix writes a code version with no scope of its own."""
        project_id, code_version = await _generated_code(client)
        async with client.app.state.pool.connection() as conn:
            await store.put_overlay(
                conn,
                project_id=project_id,
                version=code_version,
                kind="remediation_decision",
                target_id="fix-1",
                value={"appliedCodeVersion": code_version + 1, "patchedCodeVersion": code_version},
                by="you",
            )
            patched = await store.scope_for_code(conn, project_id, code_version)
            fixed = await store.scope_for_code(conn, project_id, code_version + 1)

        assert patched is not None and fixed == patched


class TestTheHealingLoopNeedsTwoVersions:
    async def test_with_nothing_to_compare_against_it_says_so(self, client) -> None:
        """The trace based classifier's whole signal is the difference between
        two versions. Without an earlier one, no failure can honestly be called
        brittle, and the stage says that rather than healing anyway."""
        project_id, code_version = await _generated_code(client)
        run, _ = await _start_testing_run(client, project_id, code_version)

        await _advance(client, run["id"])

        stages = await _stages(client, project_id)
        assert stages["self-healing"]["status"] == "complete"
        assert "no failure can be called brittle" in (stages["self-healing"]["summary"] or "")
        assert "self-healing" not in client.app.state.c3.calls

    async def test_the_guard_is_told_which_production_lines_changed(self, client) -> None:
        """Where it breaks the code first: the lines whose change made the test
        fail, in the code, never in the tests."""
        project_id, first_code_version = await _generated_code(client)
        first_run, _ = await _start_testing_run(client, project_id, first_code_version)
        await _advance(client, first_run["id"])
        await _approve_test_review(client, project_id)
        second_code_version = await _regenerated_code(client, project_id)
        route = "apps/api/src/routes/things.ts"
        async with client.app.state.pool.connection() as conn:
            files = await store.code_files(
                conn, project_id, version=second_code_version, stage_id="backend-code"
            )
            await store.put_code_files(
                conn,
                project_id,
                version=second_code_version,
                stage_id="backend-code",
                files={**files, route: files[route].replace("res.json(", "res.status(200).json(")},
            )

        second_run, _ = await _start_testing_run(client, project_id, second_code_version)
        await _advance(client, second_run["id"])

        handed = client.app.state.c3.healed_with_changes
        assert [(one.path, one.start, one.end) for one in handed] == [(route, 3, 3)]

    async def test_the_classifier_is_told_the_compared_code_s_last_test_version(
        self, client
    ) -> None:
        """A case first run after it was written from the change (E-25)."""
        project_id, first_code_version = await _generated_code(client)
        first_run, first_test_version = await _start_testing_run(
            client, project_id, first_code_version
        )
        await _advance(client, first_run["id"])
        await _approve_test_review(client, project_id)
        second_code_version = await _regenerated_code(client, project_id)

        second_run, _ = await _start_testing_run(client, project_id, second_code_version)
        await _advance(client, second_run["id"])

        assert client.app.state.c3.healed_from_test_version == first_test_version

    async def test_tests_run_again_at_the_same_code_still_compare_with_the_earlier_code(
        self, client
    ) -> None:
        """Changes at the review regenerate at a new test version on the same
        code. The cases this code's first run wrote stay written after the
        change, so the version handed over is still the earlier code's, not
        the first run's own."""
        project_id, first_code_version = await _generated_code(client)
        first_run, first_test_version = await _start_testing_run(
            client, project_id, first_code_version
        )
        await _advance(client, first_run["id"])
        await _approve_test_review(client, project_id)
        second_code_version = await _regenerated_code(client, project_id)
        second_run, second_test_version = await _start_testing_run(
            client, project_id, second_code_version
        )
        await _advance(client, second_run["id"])

        again = await _request_test_changes(client, project_id)

        assert again > second_test_version
        assert client.app.state.c3.healed_from_test_version == first_test_version

    async def test_the_compared_code_s_last_tests_count_not_its_first(self, client) -> None:
        """Tests written by a second run on the earlier code were still written
        before the change, so the version handed over is that run's."""
        project_id, first_code_version = await _generated_code(client)
        first_run, _ = await _start_testing_run(client, project_id, first_code_version)
        await _advance(client, first_run["id"])
        await _approve_test_review(client, project_id)
        rerun, rerun_version = await _start_testing_run(client, project_id, first_code_version)
        await _advance(client, rerun["id"])
        await _approve_test_review(client, project_id)
        second_code_version = await _regenerated_code(client, project_id)

        second_run, _ = await _start_testing_run(client, project_id, second_code_version)
        await _advance(client, second_run["id"])

        assert client.app.state.c3.healed_from_test_version == rerun_version

    async def test_with_an_earlier_tested_version_the_loop_runs(self, client) -> None:
        project_id, first_code_version = await _generated_code(client)
        first_run, _ = await _start_testing_run(client, project_id, first_code_version)
        await _advance(client, first_run["id"])
        await _approve_test_review(client, project_id)

        second_code_version = await _regenerated_code(client, project_id)
        client.app.state.c3.calls.clear()
        second_run, second_test_version = await _start_testing_run(
            client, project_id, second_code_version
        )

        await _advance(client, second_run["id"])

        assert "self-healing" in client.app.state.c3.calls
        async with client.app.state.pool.connection() as conn:
            at = await store.artefacts_at(
                conn, project_id, version=second_test_version, kinds=("heal-report",)
            )
        report = HealReport.model_validate(at["heal-report"]["body"])
        assert report.from_code_version == first_code_version
        assert report.to_code_version == second_code_version
        # One accepted and one refused, and the gap between the two rates is
        # the guard's effect made visible.
        assert (report.healed, report.refused) == (1, 1)
        assert report.naive_convergence == 100.0
        assert report.strict_convergence == 50.0

        # Every heal and every refusal is its own audit row, with its diff. A
        # run that says "1 healed, 1 refused" and cannot say which is not an
        # audit trail.
        async with client.app.state.pool.connection() as conn:
            entries = await store.audit_trail(conn, project_id=project_id)
        healing = [
            row for row in entries if row["action"] in ("Healed a stale test", "Refused a repair")
        ]
        assert {row["action"] for row in healing} == {"Healed a stale test", "Refused a repair"}
        refusal = next(row for row in healing if row["action"] == "Refused a repair")
        assert "kills-no-mutant" in refusal["detail"]
        assert "toBeTruthy" in refusal["detail"], "the refused diff is the evidence"


class TestWhatChangedBetweenTwoVersions:
    """The stretches the guard is handed, read from the file store."""

    async def test_each_stretch_is_lines_of_the_newer_version_and_tests_are_left_out(
        self, client
    ) -> None:
        from orchestrator.graph.testing_nodes import _changed_code

        project_id, _ = await _generated_code(client)
        older = {
            "apps/api/src/kept.ts": "a\nb\nc\n",
            "apps/api/src/edited.ts": "one\ntwo\nthree\nfour\n",
            "apps/api/src/trimmed.ts": "keep\ndrop\nkeep too\n",
            "apps/api/src/__tests__/things.criteria.test.ts": "it('a', () => {});\n",
        }
        newer = {
            "apps/api/src/kept.ts": "a\nb\nc\n",
            "apps/api/src/edited.ts": "one\nTWO\nthree\nfour\nfive\n",
            "apps/api/src/trimmed.ts": "keep\nkeep too\n",
            "apps/api/src/added.ts": "x\ny\n",
            "apps/api/src/__tests__/things.criteria.test.ts": "it('b', () => {});\n",
        }
        async with client.app.state.pool.connection() as conn:
            for version, files in ((901, older), (902, newer)):
                await store.put_code_files(
                    conn, project_id, version=version, stage_id="backend-code", files=files
                )
        state = {"project_id": project_id, "code_version": 902}

        changed = await _changed_code(client.app.state.pool, state, 901)

        assert [(one.path, one.start, one.end) for one in changed] == [
            ("apps/api/src/added.ts", 1, 2),
            ("apps/api/src/edited.ts", 2, 2),
            ("apps/api/src/edited.ts", 5, 5),
            ("apps/api/src/trimmed.ts", 2, 2),
        ]


class TestEachCaseSaysWhereItStands:
    """C3-10: the test review could not tell this version's new tests from the
    regression suite carried forward, and a test whose criterion had left the
    plan passed as if it still tested the build. Generation stamps both, and the
    run and quality stages keep them."""

    @staticmethod
    async def _report(client, project_id: str, version: int) -> TestReport:
        async with client.app.state.pool.connection() as conn:
            at = await store.artefacts_at(conn, project_id, version=version, kinds=("test-report",))
        return TestReport.model_validate(at["test-report"]["body"])

    async def test_a_second_run_carries_the_first_run_s_case_from_its_version(self, client) -> None:
        project_id, code_version = await _generated_code(client)
        first, first_version = await _start_testing_run(client, project_id, code_version)
        await _advance(client, first["id"])
        await _approve_test_review(client, project_id)
        second, second_version = await _start_testing_run(client, project_id, code_version)
        await _advance(client, second["id"])

        earlier = await self._report(client, project_id, first_version)
        later = await self._report(client, project_id, second_version)
        assert [case.since_version for case in earlier.cases] == [first_version]
        assert [case.since_version for case in later.cases] == [first_version]
        assert later.mutation is not None, "it came through the quality stage too"

    async def test_a_case_whose_criterion_left_its_story_is_obsolete(self, client) -> None:
        client.app.state.c3.case_criterion = "AC-1-9"  # type: ignore[attr-defined]
        project_id, code_version = await _generated_code(client)
        run, test_version = await _start_testing_run(client, project_id, code_version)
        await _advance(client, run["id"])

        [case] = (await self._report(client, project_id, test_version)).cases
        assert case.obsolete == "AC-1-9 is no longer one of US-1's acceptance criteria"


class TestTheAuditSaysWhyARegressionIsOne:
    """The flagged regression's audit row said its traces had not changed, which
    is false for a test written after the change: it traces to what changed
    because it was written from it (E-25)."""

    @staticmethod
    def _flagged(classified_by: str, changed: list[str]) -> HealReport:
        from datetime import UTC, datetime

        return HealReport(
            version=3,
            generated_at=datetime.now(UTC),
            target="the generated app at code version 3",
            from_code_version=2,
            to_code_version=3,
            attempts=[
                HealAttempt(
                    test_id="apps/api/src/__tests__/US-7.criteria.test.ts::no name",
                    test_name="US-7 AC-7-2: no name, no to-do",
                    suite_path="apps/api/src/__tests__/US-7.criteria.test.ts",
                    failure_message="expected 201 to be greater than or equal to 400",
                    classification="regression",
                    classified_by=classified_by,  # type: ignore[arg-type]
                    evidence=ClassificationEvidence(
                        traced_to=["US-7", "R-1"], changed_artefacts=changed
                    ),
                )
            ],
        )

    def test_a_test_written_after_the_change_says_so(self) -> None:
        from orchestrator.graph.testing_nodes import _healing_entries

        [(action, _, detail)] = _healing_entries(self._flagged("written-after-change", ["R-1"]))

        assert action == "Flagged a regression"
        assert "none of which changed" not in detail
        assert "written from the changed requirements" in detail

    def test_one_whose_traces_did_not_move_still_says_that(self) -> None:
        from orchestrator.graph.testing_nodes import _healing_entries

        [(_, _, detail)] = _healing_entries(self._flagged("trace-unchanged", []))

        assert "none of which changed between the two versions" in detail
