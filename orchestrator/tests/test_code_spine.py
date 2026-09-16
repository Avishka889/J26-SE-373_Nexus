"""The code phase, driven end to end against a real database.

The claim these hold to account: a code run walks seven stages, writes its
artefacts on its own version axis, stores the files it generated, pauses at a
gate of its own kind, and the design phase beside it is untouched by any of
it. Approving finishes the run; requesting changes regenerates at a new code
version.

The component is canned, because none of that is more true for having spent a
minute and some money generating a real monorepo. What the component produces
is proved where the component lives.
"""

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.clients.canned import CannedC2
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.graph.runner import RunSupervisor
from orchestrator.main import create_app, lifespan_for_tests
from orchestrator.readmodel.assemble import compose
from sdlc_contracts import CODE_GENERATING_STAGE_IDS, CODE_STAGE_IDS

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


async def _approved_design(client: httpx.AsyncClient) -> str:
    """A project whose design ran and was approved: C2's precondition."""
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
    return project_id


async def _start_code_run(client: httpx.AsyncClient, project_id: str):
    """What the code route will do in one place, so this file tests the graph.

    The version is claimed by the run, the design version it reads is pinned on
    it, the code stage rows are seeded, and the ones this run produces flip to
    generating.
    """
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        design_version = await store.current_version(conn, project_id)
        code_version = await store.next_code_version(conn, project_id)
        await store.seed_code_stages(conn, project_id)
        await store.set_stages(
            conn, project_id, list(CODE_GENERATING_STAGE_IDS), status="generating"
        )
        run = await store.create_run(
            conn,
            project_id=project_id,
            requirements_version=code_version,
            component="c2",
            source_version=design_version,
        )
    return run, code_version, design_version


async def _stages(client: httpx.AsyncClient, project_id: str) -> dict[str, dict]:
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        rows = await store.stage_states(conn, project_id)
    return {row["stage_id"]: row for row in rows}


class TestTheTwoGatesAreIndependent:
    """A decision pending in one phase does not block the other.

    Found live, on the cold chain project. A design change was submitted while
    a code review was still pending: the design run walked all eight nodes,
    wrote every artefact, and then could not open its gate, because the index
    allowed one pending gate per project whatever its kind. It surfaced as an
    AssertionError with no message, after six model calls, at the last node.

    The rest of the codebase had always assumed otherwise. `submit_change`
    reads this component's runs only, on the grounds that a code run paused at
    its own gate is not the design phase being busy; the code snapshot carries
    the design version it generated from precisely so a design that moves on
    can say so; and every `pending_gate` caller asks by kind. The index was the
    one place that had not caught up.
    """

    async def test_a_design_change_lands_while_a_code_review_is_pending(self, client) -> None:
        project_id = await _approved_design(client)
        run, _code_version, _design_version = await _start_code_run(client, project_id)
        await _advance(client, run["id"])
        async with client.app.state.pool.connection() as conn:
            assert await store.pending_gate(conn, project_id=project_id, kind="c2-code-review")

        answer = await client.post(
            f"/projects/{project_id}/design/changes",
            json={"note": "Add a second record type.", "by": "you"},
        )

        assert answer.status_code == 200, answer.text
        async with client.app.state.pool.connection() as conn:
            assert await store.current_version(conn, project_id) == 2

    async def test_both_gates_can_be_pending_and_each_is_decided_on_its_own(self, client) -> None:
        """The whole point of the change: two axes, two decisions, no ordering
        imposed between them."""
        project_id = await _approved_design(client)
        run, _code_version, _design_version = await _start_code_run(client, project_id)
        await _advance(client, run["id"])
        await client.post(
            f"/projects/{project_id}/design/changes",
            json={"note": "Add a second record type.", "by": "you"},
        )
        design_run = next(
            r
            for r in (await client.get("/runs", params={"project": project_id})).json()
            if r["component"] == "c1" and r["state"] in {"queued", "running"}
        )
        await _advance(client, design_run["id"])

        async with client.app.state.pool.connection() as conn:
            design_gate = await store.pending_gate(
                conn, project_id=project_id, kind="c1-design-review"
            )
            code_gate = await store.pending_gate(conn, project_id=project_id, kind="c2-code-review")
        assert design_gate is not None, "the design run could not open its gate"
        assert code_gate is not None, "opening the design gate displaced the code review"
        assert design_gate["requirements_version"] == 2

        # And each decision resolves its own phase, leaving the other alone.
        decided = await client.post(
            f"/projects/{project_id}/design/decision", json={"kind": "approved", "by": "you"}
        )
        assert decided.status_code == 200, decided.text
        async with client.app.state.pool.connection() as conn:
            assert (
                await store.pending_gate(conn, project_id=project_id, kind="c1-design-review")
            ) is None
            still = await store.pending_gate(conn, project_id=project_id, kind="c2-code-review")
        assert still is not None, "a design decision resolved the code review"
        assert str(still["id"]) == str(code_gate["id"])


class TestAWholeCodeRun:
    async def test_it_walks_every_stage_and_stops_at_its_own_gate(self, client) -> None:
        project_id = await _approved_design(client)
        run, code_version, design_version = await _start_code_run(client, project_id)
        await _advance(client, run["id"])

        stages = await _stages(client, project_id)
        produced = [stage for stage in CODE_STAGE_IDS if stage != "code-review"]
        assert [stages[stage]["status"] for stage in produced] == ["complete"] * len(produced)
        # The gate stage is complete too: reaching it is what makes the review
        # readable, and the runner writes that, not a node.
        assert stages["code-review"]["status"] == "complete"

        async with client.app.state.pool.connection() as conn:
            stored = await store.get_run(conn, run["id"])
            gate = await store.pending_gate(conn, project_id=project_id, kind="c2-code-review")
        assert stored["state"] == "awaiting_gate"
        assert gate is not None
        assert str(gate["run_id"]) == str(run["id"])
        assert gate["requirements_version"] == code_version
        assert gate["payload"]["designVersion"] == design_version

    async def test_every_artefact_lands_on_the_code_axis(self, client) -> None:
        project_id = await _approved_design(client)
        run, code_version, _ = await _start_code_run(client, project_id)
        await _advance(client, run["id"])

        async with client.app.state.pool.connection() as conn:
            written = await store.artefacts_at(
                conn,
                project_id,
                version=code_version,
                kinds=(
                    "sprint-scope",
                    "tech-stack",
                    "api-contract",
                    "contract-agreement",
                    "code-repository",
                ),
            )
        assert set(written) == {
            "sprint-scope",
            "tech-stack",
            "api-contract",
            "contract-agreement",
            "code-repository",
        }
        # The design axis is where it was: a code run consumes no design version.
        async with client.app.state.pool.connection() as conn:
            assert await store.current_version(conn, project_id) == 1

    async def test_the_files_are_stored_and_the_manifest_names_them(self, client) -> None:
        project_id = await _approved_design(client)
        run, code_version, _ = await _start_code_run(client, project_id)
        await _advance(client, run["id"])

        async with client.app.state.pool.connection() as conn:
            files = await store.code_files(conn, project_id, version=code_version)
            repository = (
                await store.artefacts_at(
                    conn, project_id, version=code_version, kinds=("code-repository",)
                )
            )["code-repository"]["body"]

        manifest_paths = {row["path"] for row in repository["manifest"]}
        assert files, "the code stages stored nothing"
        # The manifest and the file store must name one set, or the viewer
        # offers a file the manifest cannot account for.
        assert manifest_paths == set(files)
        assert repository["build"]["steps"], "the build stage recorded no steps"

    async def test_the_repository_says_why_nothing_was_pushed(self, client) -> None:
        """No connection is a recorded outcome, never an invented URL."""
        project_id = await _approved_design(client)
        run, code_version, _ = await _start_code_run(client, project_id)
        await _advance(client, run["id"])

        async with client.app.state.pool.connection() as conn:
            body = (
                await store.artefacts_at(
                    conn, project_id, version=code_version, kinds=("code-repository",)
                )
            )["code-repository"]["body"]
        assert body["repository"] is None
        assert "no GitHub connection" in body["notPushedReason"]

    async def test_the_component_was_asked_for_every_stage_in_order(self, client) -> None:
        project_id = await _approved_design(client)
        run, _, _ = await _start_code_run(client, project_id)
        await _advance(client, run["id"])
        canned: CannedC2 = client.app.state.c2
        assert canned.calls == [
            "sprint-scope",
            "tech-stack",
            "api-contract",
            "frontend-code",
            "backend-code",
            "contract-agreement",
            "build",
            "push",
        ]


class TestTheDesignPhaseIsUntouched:
    async def test_the_design_snapshot_still_composes_over_real_code_rows(self, client) -> None:
        """Not planted rows: a whole code run's worth of stage rows, thread
        messages, artefacts and a gate of another kind."""
        project_id = await _approved_design(client)
        run, _, _ = await _start_code_run(client, project_id)
        await _advance(client, run["id"])

        async with client.app.state.pool.connection() as conn:
            project = await store.project_without_owner_check(conn, project_id)
            snapshot = await compose(conn, project)

        assert snapshot.requirements_version == 1
        assert snapshot.gate.decision is not None
        # The design's own gate, not the code one that is now pending.
        assert snapshot.gate.decision.kind == "approved"
        assert all(message.stage_id != "build" for message in snapshot.thread)

    async def test_the_project_reads_as_testing_only_after_the_code_gate(self, client) -> None:
        project_id = await _approved_design(client)
        before = (await client.get(f"/projects/{project_id}")).json()
        assert before["status"] == "code"

        run, _, _ = await _start_code_run(client, project_id)
        await _advance(client, run["id"])
        async with client.app.state.pool.connection() as conn:
            gate = await store.pending_gate(conn, project_id=project_id, kind="c2-code-review")
            await store.resolve_gate(conn, gate["id"], decision="approved", by="you", note=None)

        after = (await client.get(f"/projects/{project_id}")).json()
        assert after["status"] == "testing"


class TestDecidingAtTheGate:
    async def test_approving_finishes_the_run(self, client) -> None:
        project_id = await _approved_design(client)
        run, _, _ = await _start_code_run(client, project_id)
        await _advance(client, run["id"])

        async with client.app.state.pool.connection() as conn:
            gate = await store.pending_gate(conn, project_id=project_id, kind="c2-code-review")
            await store.resolve_gate(conn, gate["id"], decision="approved", by="you", note=None)
            await store.set_run_state(
                conn, run["id"], "queued", resume_payload={"kind": "approved", "note": None}
            )
        await _advance(client, run["id"])

        async with client.app.state.pool.connection() as conn:
            finished = await store.get_run(conn, run["id"])
        assert finished["state"] == "done"

    async def test_requesting_changes_regenerates_at_a_new_code_version(self, client) -> None:
        project_id = await _approved_design(client)
        run, first_version, _ = await _start_code_run(client, project_id)
        await _advance(client, run["id"])

        async with client.app.state.pool.connection() as conn:
            gate = await store.pending_gate(conn, project_id=project_id, kind="c2-code-review")
            await store.resolve_gate(
                conn, gate["id"], decision="changes", by="you", note="use the llm arm"
            )
            next_version = await store.next_code_version(conn, project_id)
            await store.set_run_state(
                conn,
                run["id"],
                "queued",
                resume_payload={
                    "kind": "changes",
                    "note": "use the llm arm",
                    "version": next_version,
                },
            )
        assert next_version == first_version + 1
        await _advance(client, run["id"])

        async with client.app.state.pool.connection() as conn:
            written = await store.artefacts_at(
                conn, project_id, version=next_version, kinds=("api-contract",)
            )
            # The first version is still there: the evaluation compares them.
            first = await store.artefacts_at(
                conn, project_id, version=first_version, kinds=("api-contract",)
            )
        assert "api-contract" in written
        assert "api-contract" in first

    async def test_a_choice_made_at_one_version_carries_into_the_next(self, client) -> None:
        """An arm chosen once stays chosen. A decision that had to be made
        again after every regeneration would be a setting, not a decision."""
        project_id = await _approved_design(client)
        run, first_version, _ = await _start_code_run(client, project_id)
        await _advance(client, run["id"])

        async with client.app.state.pool.connection() as conn:
            await store.put_overlay(
                conn,
                project_id=project_id,
                version=first_version,
                kind="contract_arm_choice",
                target_id="arm",
                value="llm",
                by="you",
            )
            gate = await store.pending_gate(conn, project_id=project_id, kind="c2-code-review")
            await store.resolve_gate(
                conn, gate["id"], decision="changes", by="you", note="regenerate"
            )
            next_version = await store.next_code_version(conn, project_id)
            await store.set_run_state(
                conn,
                run["id"],
                "queued",
                resume_payload={"kind": "changes", "note": "n", "version": next_version},
            )
        await _advance(client, run["id"])

        async with client.app.state.pool.connection() as conn:
            body = (
                await store.artefacts_at(
                    conn, project_id, version=next_version, kinds=("api-contract",)
                )
            )["api-contract"]["body"]
        assert body["chosen"] == "llm"


class TestFailure:
    async def test_a_leaf_failure_still_reaches_the_gate(self, client) -> None:
        """A build that broke is a report the reader decides about. A run that
        died on it leaves them nothing to decide."""
        client.app.state.c2 = CannedC2(fails={"build"})
        project_id = await _approved_design(client)
        # The graph was compiled with the app's own component, so rebuild it
        # around the failing one.
        from orchestrator.graph.code_graph import build_code_graph

        client.app.state.graphs["c2"] = build_code_graph(
            client.app.state.pool, client.app.state.checkpointer, client.app.state.c2
        )
        client.app.state.supervisor._graphs["c2"] = client.app.state.graphs["c2"]
        client.app.state.supervisor._clients["c2"] = client.app.state.c2

        run, _, _ = await _start_code_run(client, project_id)
        await _advance(client, run["id"])

        stages = await _stages(client, project_id)
        assert stages["build"]["status"] == "failed"
        assert stages["build"]["error"]
        assert stages["code-review"]["status"] == "complete"
        async with client.app.state.pool.connection() as conn:
            stored = await store.get_run(conn, run["id"])
        assert stored["state"] == "awaiting_gate"

    async def test_a_load_bearing_failure_fails_the_run_and_strands_nothing(self, client) -> None:
        client.app.state.c2 = CannedC2(fails={"api-contract"})
        project_id = await _approved_design(client)
        from orchestrator.graph.code_graph import build_code_graph

        client.app.state.graphs["c2"] = build_code_graph(
            client.app.state.pool, client.app.state.checkpointer, client.app.state.c2
        )
        client.app.state.supervisor._graphs["c2"] = client.app.state.graphs["c2"]
        client.app.state.supervisor._clients["c2"] = client.app.state.c2

        run, _, _ = await _start_code_run(client, project_id)
        await _advance(client, run["id"])

        stages = await _stages(client, project_id)
        assert stages["api-contract"]["status"] == "failed"
        # Nothing left claiming to be generating: the client polls while
        # anything is, and the work has stopped.
        assert not [stage for stage in CODE_STAGE_IDS if stages[stage]["status"] == "generating"]
        async with client.app.state.pool.connection() as conn:
            stored = await store.get_run(conn, run["id"])
            gate = await store.pending_gate(conn, project_id=project_id, kind="c2-code-review")
        assert stored["state"] == "failed"
        assert gate is None


class TestPinningTheDesign:
    async def test_a_design_that_moves_on_does_not_change_what_was_generated(self, client) -> None:
        """The run reads the version it pinned. Written as a planted newer
        design, because reproducing the race by timing would be a flaky test
        about the same fact."""
        project_id = await _approved_design(client)
        run, code_version, design_version = await _start_code_run(client, project_id)

        async with client.app.state.pool.connection() as conn:
            # A newer design appears before the code run gets going.
            await store.put_artefact(
                conn,
                project_id=project_id,
                kind="sprint-plan",
                version=design_version + 1,
                body={
                    "sprintName": "Sprint 2",
                    "goal": "something else entirely",
                    "velocityAssumption": {"points": 20, "basis": "assumed"},
                    "estimatedPoints": 0,
                    "proposed": [],
                    "backlog": [],
                },
            )
        await _advance(client, run["id"])

        async with client.app.state.pool.connection() as conn:
            scope = (
                await store.artefacts_at(
                    conn, project_id, version=code_version, kinds=("sprint-scope",)
                )
            )["sprint-scope"]["body"]
        assert scope["sprintName"] == "Sprint 1 (proposed)"
        assert scope["stories"], "the pinned plan's story should still be in scope"


class TestRacingTheDecisionsCommit:
    """A run paused at its gate is never started fresh.

    Found on the first live code walk. A scope change resolved the pending
    gate, allocated code version 2 and handed the run to a worker; the worker
    read the row before the route's transaction committed, saw it still
    awaiting_gate with no payload, took the fresh start path and regenerated
    code version 1 on top of itself. The reader lost the version they were
    deciding on and got no diff, because there was nothing to diff against.
    """

    async def test_advancing_a_paused_run_changes_nothing(self, client) -> None:
        project_id = await _approved_design(client)
        run, code_version, _ = await _start_code_run(client, project_id)
        await _advance(client, run["id"])

        async with client.app.state.pool.connection() as conn:
            before = await store.artefacts_at(
                conn, project_id, version=code_version, kinds=("api-contract",)
            )
        canned: CannedC2 = client.app.state.c2
        canned.calls.clear()

        # Exactly the race: the row still says awaiting_gate and carries no
        # payload, because the decision's transaction has not landed.
        await _advance(client, run["id"])

        assert canned.calls == [], "a paused run must not be walked again"
        async with client.app.state.pool.connection() as conn:
            after = await store.artefacts_at(
                conn, project_id, version=code_version, kinds=("api-contract",)
            )
            stored = await store.get_run(conn, run["id"])
        assert after["api-contract"]["body"] == before["api-contract"]["body"]
        assert stored["state"] == "awaiting_gate"

    async def test_a_recorded_decision_still_resumes(self, client) -> None:
        """The guard reads the payload, not the state, so a decision that did
        commit resumes exactly as before."""
        project_id = await _approved_design(client)
        run, first_version, _ = await _start_code_run(client, project_id)
        await _advance(client, run["id"])

        async with client.app.state.pool.connection() as conn:
            gate = await store.pending_gate(conn, project_id=project_id, kind="c2-code-review")
            await store.resolve_gate(
                conn, gate["id"], decision="changes", by="you", note="narrow it"
            )
            next_version = await store.next_code_version(conn, project_id)
            await store.set_run_state(
                conn,
                run["id"],
                "queued",
                resume_payload={"kind": "changes", "note": "narrow it", "version": next_version},
            )
        await _advance(client, run["id"])

        async with client.app.state.pool.connection() as conn:
            written = await store.artefacts_at(
                conn, project_id, version=next_version, kinds=("api-contract",)
            )
        assert next_version == first_version + 1
        assert "api-contract" in written, "the regeneration landed on the new version"
