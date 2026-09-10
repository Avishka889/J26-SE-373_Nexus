"""The spine's definition of done, asserted rather than described.

A run reaches the gate and pauses, the process is replaced, the gate is still
pending, approving resumes the same thread to completion, and the audit log shows
every step.

These tests need a database, because that is the whole claim: a gate that only
survives inside one process has not survived anything. They are skipped when no
database is reachable so the suite still runs offline, and CI supplies Postgres
through a service container.
"""

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.clients.canned import CannedC1
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.db.pool import create_app_pool
from orchestrator.graph.build import build_graph
from orchestrator.graph.runner import RunSupervisor
from orchestrator.main import create_app, lifespan_for_tests
from sdlc_contracts import ARTEFACT_STAGE_IDS, DESIGN_STAGE_IDS

from .conftest import needs_db

THIN_REQUIREMENT = "Build a simple calculator app"


pytestmark = needs_db


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    """An app with an in memory checkpointer and no background workers.

    `ASGITransport` does not run the lifespan, so it is entered by hand. Without
    that the pool never opens and every route fails on `app.state.pool`, which is
    exactly how this was first found.

    Tests drive `advance` themselves, so the timing is theirs rather than a race
    against a poller.
    """
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
                # The development database is a shared Neon branch, so a test that
                # leaves its rows behind pollutes what the next person sees and
                # leaves queued runs for a real orchestrator to pick up. Deleting
                # the project cascades to everything under it.
                async with app.state.pool.connection() as conn:
                    for project_id in created:
                        await store.delete_project(conn, project_id, owner_id=DEV_OWNER_ID)


async def _advance(client: httpx.AsyncClient, run_id: str) -> None:
    supervisor: RunSupervisor = client.app.state.supervisor  # type: ignore[attr-defined]
    await supervisor.advance(uuid.UUID(run_id))


async def _pending_gate(client: httpx.AsyncClient, project_id: str) -> dict:
    """The gate waiting on this project, from the process API's own listing."""
    gates = (await client.get("/gates", params={"status": "pending", "project": project_id})).json()
    return next(g for g in gates if g["projectId"] == project_id)


async def _start(client: httpx.AsyncClient, text: str = THIN_REQUIREMENT) -> tuple[str, str]:
    """Create a project, give it a requirement, and return ids for both."""
    created = await client.post("/projects", json={"name": "Calculator", "description": ""})
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]
    client.created_projects.append(project_id)  # type: ignore[attr-defined]

    # The requirement text arriving is the start signal. There is no separate
    # "start the pipeline" call, because the frontend never had one.
    patched = await client.patch(f"/projects/{project_id}", json={"requirementText": text})
    assert patched.status_code == 200, patched.text

    runs = (await client.get("/runs", params={"project": project_id})).json()
    assert len(runs) == 1, "the requirement text should have queued exactly one run"
    return project_id, runs[0]["id"]


class TestTheSpine:
    async def test_requirement_text_queues_a_run(self, client: httpx.AsyncClient) -> None:
        project_id, run_id = await _start(client)
        run = (await client.get(f"/runs/{run_id}")).json()
        assert run["state"] == "queued"
        assert run["requirementsVersion"] == 1
        assert run["projectId"] == project_id

    async def test_a_second_patch_does_not_start_a_second_run(
        self, client: httpx.AsyncClient
    ) -> None:
        """The old client side ticker PATCHes repeatedly. Those must be no ops."""
        project_id, _ = await _start(client)
        for _ in range(3):
            await client.patch(
                f"/projects/{project_id}",
                json={"requirementText": THIN_REQUIREMENT, "reqPhase": "wireframes"},
            )
        runs = (await client.get("/runs", params={"project": project_id})).json()
        assert len(runs) == 1

    async def test_derived_fields_ignore_what_a_client_sends(
        self, client: httpx.AsyncClient
    ) -> None:
        """reqPhase, progress and status are computed, so a PATCH cannot set them
        to something the run disagrees with."""
        project_id, _ = await _start(client)
        response = await client.patch(
            f"/projects/{project_id}",
            json={"reqPhase": "design-review", "progress": 100, "status": "complete"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["progress"] != 100
        assert body["status"] != "complete"

    async def test_run_reaches_the_gate_and_pauses(self, client: httpx.AsyncClient) -> None:
        project_id, run_id = await _start(client)
        await _advance(client, run_id)

        run = (await client.get(f"/runs/{run_id}")).json()
        assert run["state"] == "awaiting_gate"

        gates = (await client.get("/gates", params={"status": "pending"})).json()
        mine = [g for g in gates if g["projectId"] == project_id]
        assert len(mine) == 1
        assert mine[0]["kind"] == "c1-design-review"
        assert mine[0]["requirementsVersion"] == 1

    async def test_the_snapshot_has_all_eight_stages(self, client: httpx.AsyncClient) -> None:
        """The client indexes every stage with no null guard, so a missing key is
        a crash rather than a blank."""
        project_id, run_id = await _start(client)
        empty = (await client.get(f"/projects/{project_id}/design")).json()
        assert len(empty["stages"]) == 8

        await _advance(client, run_id)
        snapshot = (await client.get(f"/projects/{project_id}/design")).json()
        assert len(snapshot["stages"]) == 8
        assert snapshot["requirementsVersion"] == 1
        # Every stage a component produces is complete, and the two that are
        # projections rather than artefacts are not.
        for stage_id in ARTEFACT_STAGE_IDS:
            assert snapshot["stages"][stage_id]["status"] == "complete", (
                f"{stage_id} did not finish"
            )
            assert snapshot["stages"][stage_id]["summary"], f"{stage_id} finished without saying so"
        assert snapshot["requirements"]
        assert snapshot["graph"]["nodes"]
        assert snapshot["uml"]["diagrams"]
        assert snapshot["wireframes"]["flows"]
        assert snapshot["sprint"]["proposed"]
        assert snapshot["architecture"]["candidates"]

    async def test_every_artefact_element_carries_traces(self, client: httpx.AsyncClient) -> None:
        """Traceability by construction is the component's claim, so it is
        asserted on the artefacts rather than assumed."""
        project_id, run_id = await _start(client)
        await _advance(client, run_id)
        snapshot = (await client.get(f"/projects/{project_id}/design")).json()

        known = {r["id"] for r in snapshot["requirements"]}
        assert known
        for node in snapshot["graph"]["nodes"]:
            assert node["traces"], f"node {node['id']} traces to nothing"
            assert set(node["traces"]) <= known
        for edge in snapshot["graph"]["edges"]:
            assert edge["traces"], f"edge {edge['id']} traces to nothing"
            assert set(edge["traces"]) <= known

    async def test_every_timestamp_carries_its_zone(self, client: httpx.AsyncClient) -> None:
        """Times went out as "2026-10-03 09:12", UTC with the zone dropped, and the
        pages showed them as they came: five and a half hours early in Colombo. The
        browser now shows each in its reader's zone, which it can do only for a time
        that says which zone it is in. This test used to forbid exactly that, since
        the pages printed the text as it came and a T in it was visible."""
        import json
        import re

        project_id, run_id = await _start(client)
        await _advance(client, run_id)
        snapshot = (await client.get(f"/projects/{project_id}/design")).json()
        times = re.findall(r'"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}[^"]*)"', json.dumps(snapshot))
        assert times, "the snapshot carries times"
        zoneless = [
            t for t in times if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", t)
        ]
        assert not zoneless, f"times without their zone reached the snapshot: {zoneless[:3]}"

    async def test_approving_resumes_the_same_thread_to_completion(
        self, client: httpx.AsyncClient
    ) -> None:
        project_id, run_id = await _start(client)
        await _advance(client, run_id)

        gate = await _pending_gate(client, project_id)

        approved = await client.post(f"/gates/{gate['id']}/approve", json={"by": "A. Chen"})
        assert approved.status_code == 200, approved.text
        assert approved.json()["runId"] == run_id

        # The decision is recorded and the run is queued to resume; the
        # supervisor then carries it to the end on the same thread id.
        await _advance(client, run_id)
        run = (await client.get(f"/runs/{run_id}")).json()
        assert run["state"] == "done"

        snapshot = (await client.get(f"/projects/{project_id}/design")).json()
        assert snapshot["gate"]["decision"]["kind"] == "approved"
        # The request said "A. Chen"; the decision is the signed-in account's.
        assert snapshot["gate"]["decision"]["by"] == "Local development"
        assert snapshot["gate"]["decision"]["version"] == 1

    async def test_a_new_version_is_undecided_and_the_old_decision_is_history(
        self, client: httpx.AsyncClient
    ) -> None:
        """A decision covers the version it was made about and nothing later.

        The contract says exactly that, and the read model reported the newest
        decision whatever its version. So once a project had been approved
        once, `decision` was never null again: the page read it as decided,
        drew no decision bar, and the run waiting at the next version's gate
        waited for good. Reported from the browser, on a project that had been
        approved twice and had no way to approve a third time.
        """
        project_id, run_id = await _start(client)
        await _advance(client, run_id)
        await client.post(
            f"/projects/{project_id}/design/decision",
            json={"kind": "approved", "by": "A. Chen"},
        )
        await _advance(client, run_id)

        await client.post(
            f"/projects/{project_id}/design/changes",
            json={"note": "Add a second kind of record.", "by": "A. Chen"},
        )
        second = (await client.get("/runs", params={"project": project_id})).json()[0]
        await _advance(client, second["id"])

        snapshot = (await client.get(f"/projects/{project_id}/design")).json()
        assert snapshot["requirementsVersion"] == 2
        assert snapshot["gate"]["decision"] is None, (
            "version 2 reported version 1's approval, so the phase never asked again"
        )
        assert [(h["kind"], h["version"]) for h in snapshot["gate"]["history"]] == [("approved", 1)]
        # And the thing the page reads to draw the bar is true.
        assert snapshot["stages"]["design-review"]["status"] == "complete"

    async def test_the_decision_comes_back_once_the_new_version_is_decided(
        self, client: httpx.AsyncClient
    ) -> None:
        """The guard must not hide a decision that does cover this version."""
        project_id, run_id = await _start(client)
        await _advance(client, run_id)
        await client.post(
            f"/projects/{project_id}/design/decision",
            json={"kind": "approved", "by": "A. Chen"},
        )
        await _advance(client, run_id)
        await client.post(
            f"/projects/{project_id}/design/changes",
            json={"note": "Add a second kind of record.", "by": "A. Chen"},
        )
        second = (await client.get("/runs", params={"project": project_id})).json()[0]
        await _advance(client, second["id"])
        await client.post(
            f"/projects/{project_id}/design/decision",
            json={"kind": "approved", "by": "A. Chen"},
        )

        snapshot = (await client.get(f"/projects/{project_id}/design")).json()
        assert snapshot["gate"]["decision"]["version"] == 2
        assert snapshot["gate"]["decision"]["kind"] == "approved"
        assert [h["version"] for h in snapshot["gate"]["history"]] == [1]

    async def test_requesting_changes_regenerates_at_the_next_version(
        self, client: httpx.AsyncClient
    ) -> None:
        project_id, run_id = await _start(client)
        await _advance(client, run_id)

        decided = await client.post(
            f"/projects/{project_id}/design/decision",
            json={"kind": "changes", "by": "A. Chen", "note": "Add a memory function"},
        )
        assert decided.status_code == 200, decided.text

        # Resuming feeds the note back in and the design rebuilds at version 2.
        await _advance(client, run_id)
        snapshot = (await client.get(f"/projects/{project_id}/design")).json()
        assert snapshot["requirementsVersion"] == 2, (
            "the read model composes at the version the artefacts were written "
            "at, or a regenerated design is never shown"
        )
        assert any("memory function" in m["content"] for m in snapshot["thread"])

        # The note is part of the input the regeneration saw, not just a comment
        # attached beside it.
        assert any("memory function" in r["text"] for r in snapshot["requirements"]), (
            "the change note never reached the graph"
        )

        # The run now reports the version it is actually producing, and pauses at
        # a fresh gate for the revision.
        run = (await client.get(f"/runs/{run_id}")).json()
        assert run["requirementsVersion"] == 2
        assert run["state"] == "awaiting_gate"

    async def test_a_revision_does_not_overwrite_the_earlier_version(
        self, client: httpx.AsyncClient
    ) -> None:
        """Every version survives, because the ablation compares them.

        This is the reason version numbers are allocated by the store: a node
        that computed its own would reuse a number and the upsert would erase
        the earlier artefact.
        """
        project_id, run_id = await _start(client)
        await _advance(client, run_id)
        await client.post(
            f"/projects/{project_id}/design/decision",
            json={"kind": "changes", "by": "A. Chen", "note": "Add a memory function"},
        )
        await _advance(client, run_id)

        async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
            rows = await store.artefact_versions(conn, project_id, "requirements")
        assert sorted(rows) == [1, 2], f"versions did not both survive: {rows}"

    async def test_a_note_queued_during_a_run_is_applied_after_approval(
        self, client: httpx.AsyncClient
    ) -> None:
        """The second loop point.

        Requesting a change mid run and then approving must not lose the change:
        without a drain at the end of a run it stays queued forever.
        """
        project_id, run_id = await _start(client)
        await client.post(
            f"/projects/{project_id}/design/changes",
            json={"note": "Also support percentages", "by": "A. Chen"},
        )
        await _advance(client, run_id)

        gate = await _pending_gate(client, project_id)
        await client.post(f"/gates/{gate['id']}/approve", json={"by": "A. Chen"})
        await _advance(client, run_id)

        runs = (await client.get("/runs", params={"project": project_id})).json()
        assert len(runs) == 2, "the queued note should have started a follow up run"
        follow_up = next(r for r in runs if r["id"] != run_id)
        await _advance(client, follow_up["id"])

        snapshot = (await client.get(f"/projects/{project_id}/design")).json()
        assert any("percentages" in r["text"] for r in snapshot["requirements"]), (
            "the queued note was never applied"
        )

    async def test_changes_without_a_note_are_refused(self, client: httpx.AsyncClient) -> None:
        """Requesting changes with nothing to change is not a decision."""
        project_id, run_id = await _start(client)
        await _advance(client, run_id)
        response = await client.post(
            f"/projects/{project_id}/design/decision",
            json={"kind": "changes", "by": "A. Chen", "note": "   "},
        )
        assert response.status_code == 409
        assert "note" in response.json()["error"]

    async def test_deciding_twice_is_refused(self, client: httpx.AsyncClient) -> None:
        project_id, run_id = await _start(client)
        await _advance(client, run_id)
        first = await client.post(
            f"/projects/{project_id}/design/decision",
            json={"kind": "approved", "by": "A. Chen"},
        )
        assert first.status_code == 200
        second = await client.post(
            f"/projects/{project_id}/design/decision",
            json={"kind": "approved", "by": "A. Chen"},
        )
        assert second.status_code == 409

    async def test_the_audit_log_shows_every_step(self, client: httpx.AsyncClient) -> None:
        project_id, run_id = await _start(client)
        await _advance(client, run_id)
        gate = await _pending_gate(client, project_id)
        await client.post(f"/gates/{gate['id']}/approve", json={"by": "A. Chen"})
        await _advance(client, run_id)

        entries = (await client.get("/audit", params={"project": project_id})).json()
        actions = [e["action"] for e in entries]
        for expected in (
            "Created the project",
            "Queued a run",
            "Generated Requirements Analysis",
            "Reached the Design Review gate",
            "Approved the design",
            "Run finished",
        ):
            assert expected in actions, f"the audit log is missing: {expected}\nsaw: {actions}"

        # Every entry names who did it and what it touched.
        for entry in entries:
            assert entry["actor"]
            assert entry["action"]
            assert entry["target"]

    async def test_activity_is_a_view_over_the_audit_log(self, client: httpx.AsyncClient) -> None:
        _project_id, run_id = await _start(client)
        await _advance(client, run_id)
        activity = (await client.get("/activity")).json()
        assert activity
        assert {"id", "timestamp", "title", "actor", "category"} <= set(activity[0])
        # The browser formats it in its reader's zone; a date the server made was UTC's.
        assert "displayDate" not in activity[0]

    async def test_activity_reads_one_project_at_a_time(self, client: httpx.AsyncClient) -> None:
        # The view sits under one project, and it listed every project's events.
        first, first_run = await _start(client)
        second, second_run = await _start(client)
        await _advance(client, first_run)
        await _advance(client, second_run)
        async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
            theirs = {str(row["id"]) for row in await store.audit_trail(conn, project_id=second)}

        answer = await client.get("/activity", params={"project": first})

        assert answer.status_code == 200, answer.text
        ids = {entry["id"] for entry in answer.json()}
        assert ids and not ids & theirs
        missing = await client.get("/activity", params={"project": "p_no_such_project"})
        assert missing.status_code == 404

    async def test_a_run_cannot_be_started_twice(self, client: httpx.AsyncClient) -> None:
        """Two graphs must never run on one thread id."""
        project_id, _ = await _start(client)
        response = await client.post("/runs", json={"projectId": project_id})
        assert response.status_code == 409
        assert "in flight" in response.json()["error"]

    async def test_a_change_during_a_run_is_queued_not_raced(
        self, client: httpx.AsyncClient
    ) -> None:
        project_id, _run_id = await _start(client)
        # The run is queued but not advanced, so it is still in flight.
        response = await client.post(
            f"/projects/{project_id}/design/changes",
            json={"note": "Also support percentages", "by": "A. Chen"},
        )
        assert response.status_code == 200
        runs = (await client.get("/runs", params={"project": project_id})).json()
        assert len(runs) == 1, "a note during a run must not start a second one"

        entries = (await client.get("/audit", params={"project": project_id})).json()
        assert any(e["action"] == "Queued the change" for e in entries)


class TestSurvivingARestart:
    """The claim that a checkpointer exists for.

    An in memory saver would pass every other test in this file and fail this
    one, which is exactly why this one is here.
    """

    async def test_gate_survives_the_process_being_replaced(self, settings: Settings) -> None:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from orchestrator.db.pool import create_checkpointer_pool

        project_id: str
        run_id: uuid.UUID

        # ---- process one: start a run and let it reach the gate
        pool = create_app_pool(settings.database_url, max_size=4)
        await pool.open(wait=True)
        cp_pool = create_checkpointer_pool(settings.checkpointer_url, max_size=2)
        await cp_pool.open(wait=True)
        checkpointer = AsyncPostgresSaver(cp_pool)  # type: ignore[arg-type]
        await checkpointer.setup()

        graph = build_graph(pool, checkpointer, CannedC1())
        supervisor = RunSupervisor(pool=pool, graph=graph)

        async with pool.connection() as conn:
            project = await store.create_project(
                conn, name="Restart", description="", owner_id=DEV_OWNER_ID
            )
            project_id = project["id"]
            await store.patch_project(conn, project_id, {"requirement_text": THIN_REQUIREMENT})
            version = await store.open_version(conn, project_id, note=None, by="you", applied=True)
            run = await store.create_run(conn, project_id=project_id, requirements_version=version)
            run_id = run["id"]

        await supervisor.advance(run_id)

        async with pool.connection() as conn:
            assert (await store.get_run(conn, run_id))["state"] == "awaiting_gate"

        # ---- the process goes away entirely
        await cp_pool.close()
        await pool.close()
        del graph, supervisor, checkpointer

        # ---- process two: nothing in memory, everything from the database
        pool2 = create_app_pool(settings.database_url, max_size=4)
        await pool2.open(wait=True)
        cp_pool2 = create_checkpointer_pool(settings.checkpointer_url, max_size=2)
        await cp_pool2.open(wait=True)
        checkpointer2 = AsyncPostgresSaver(cp_pool2)  # type: ignore[arg-type]
        graph2 = build_graph(pool2, checkpointer2, CannedC1())
        supervisor2 = RunSupervisor(pool=pool2, graph=graph2)

        try:
            async with pool2.connection() as conn:
                gate = await store.pending_gate(conn, project_id=project_id)
                assert gate is not None, "the gate did not survive the restart"
                assert gate["requirements_version"] == 1

                # Approve through the same path the API uses.
                await store.resolve_gate(
                    conn, gate["id"], decision="approved", by="A. Chen", note=None
                )
                await store.set_run_state(
                    conn,
                    run_id,
                    "queued",
                    resume_payload={"kind": "approved", "note": None},
                )

            # The resume lands on the same thread id, in a process that never saw
            # the interrupt happen.
            await supervisor2.advance(run_id)

            async with pool2.connection() as conn:
                run = await store.get_run(conn, run_id)
                assert run["state"] == "done", f"resume did not complete: {run['state']}"
        finally:
            async with pool2.connection() as conn:
                await store.delete_project(conn, project_id, owner_id=DEV_OWNER_ID)
            await cp_pool2.close()
            await pool2.close()

    async def test_a_decision_with_no_checkpoint_fails_instead_of_starting_over(
        self, client: httpx.AsyncClient
    ) -> None:
        """`Command(resume=...)` on an unknown thread is not an error to LangGraph.

        It starts the graph from the beginning with empty state, so the first node
        crashes on a missing key and the real cause is invisible. A run row can
        outlive its checkpoint, so this has to be caught at the boundary.
        """
        project_id, run_id = await _start(client)
        async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
            # Never advanced, so no checkpoint exists for this thread.
            await store.set_run_state(
                conn,
                uuid.UUID(run_id),
                "queued",
                resume_payload={"kind": "approved", "note": None},
            )

        await _advance(client, run_id)

        run = (await client.get(f"/runs/{run_id}")).json()
        assert run["state"] == "failed"
        assert "no checkpoint" in run["error"]

        entries = (await client.get("/audit", params={"project": project_id})).json()
        assert any(e["action"] == "Run failed" for e in entries)


class TestTheGateNodeStaysEmpty:
    """A structural guard rather than a behavioural one.

    LangGraph re-executes the interrupted node on resume, so anything placed
    above `interrupt()` runs twice. Today the gate node has nothing above it, and
    this test is what notices the day somebody adds a database read there.
    """

    @pytest.mark.parametrize(
        ("module", "name"),
        [
            ("orchestrator.graph.nodes", "design_gate"),
            ("orchestrator.graph.code_nodes", "code_gate"),
            ("orchestrator.graph.testing_nodes", "test_gate"),
        ],
    )
    def test_nothing_happens_before_the_interrupt(self, module: str, name: str) -> None:
        """Every gate, not just the first one written.

        Parameterised over the registry's three so a fourth phase inherits the
        guard by being added here rather than by somebody remembering. It
        covered only the design gate until C3 arrived, which is exactly how a
        structural guard quietly stops being structural.
        """
        import importlib
        import inspect

        source = inspect.getsource(getattr(importlib.import_module(module), name))
        body = source.split('"""', 2)[-1]
        before = body.split("interrupt(", 1)[0]

        for forbidden in ("await", "store.", "conn", "pool"):
            assert forbidden not in before, (
                f"{forbidden!r} appears before interrupt() in {name}. "
                "That code re-runs every time a human answers the gate."
            )

    def test_the_graph_compiles_without_a_database(self) -> None:
        """Graph shape is checkable with no infrastructure at all."""
        graph = build_graph(
            pool=None,  # type: ignore[arg-type]
            checkpointer=InMemorySaver(),
            c1=CannedC1(),
        )
        assert graph is not None


class TestOneStageFailing:
    """A leaf stage that dies should cost its own artefact and nothing else.

    Requirements and the graph are load bearing: everything downstream reads
    them. The other four are leaves, and taking the sprint plan down because a
    diagram failed would cost the reader five good artefacts to report one bad
    one.
    """

    @pytest.fixture
    async def client_failing_wireframes(
        self, settings: Settings
    ) -> AsyncIterator[httpx.AsyncClient]:
        app = create_app(settings, lifespan_factory=lifespan_for_tests)
        app.state.c1 = CannedC1(fails={"wireframes"})
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

    async def test_the_run_finishes_and_the_other_stages_still_land(
        self, client_failing_wireframes: httpx.AsyncClient
    ) -> None:
        client = client_failing_wireframes
        project_id, run_id = await _start(client)
        await _advance(client, run_id)

        snapshot = (await client.get(f"/projects/{project_id}/design")).json()
        stages = snapshot["stages"]

        assert stages["wireframes"]["status"] == "failed"
        # In plain words, because the contract refuses a failed stage that does
        # not say why and because a reader has to decide whether to retry.
        assert stages["wireframes"]["error"]
        assert not snapshot["wireframes"]["flows"]

        # And everything after it ran anyway.
        assert stages["sprint-plan"]["status"] == "complete"
        assert snapshot["sprint"]["proposed"]
        for stage_id in ("requirements", "architecture-graph", "uml-diagrams"):
            assert stages[stage_id]["status"] == "complete"

    async def test_it_still_reaches_the_gate(
        self, client_failing_wireframes: httpx.AsyncClient
    ) -> None:
        # The reader decides. A stage failing is information for them, not a
        # reason for the phase to refuse to finish.
        client = client_failing_wireframes
        project_id, run_id = await _start(client)
        await _advance(client, run_id)

        assert (await client.get(f"/runs/{run_id}")).json()["state"] == "awaiting_gate"
        assert await _pending_gate(client, project_id)

    async def test_approving_over_the_failure_needs_a_note(
        self, client_failing_wireframes: httpx.AsyncClient
    ) -> None:
        # Approving was one click whatever had failed: eighteen live projects sat
        # at an open design review with a failed stage.
        client = client_failing_wireframes
        project_id, run_id = await _start(client)
        await _advance(client, run_id)

        refused = await client.post(
            f"/projects/{project_id}/design/decision", json={"kind": "approved", "by": "A. Chen"}
        )
        assert refused.status_code == 409
        assert "1 failed stage" in refused.json()["error"]
        assert await _pending_gate(client, project_id)

        note = "Wireframes are drawn by hand this sprint."
        approved = await client.post(
            f"/projects/{project_id}/design/decision",
            json={"kind": "approved", "by": "A. Chen", "note": note},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["gate"]["decision"]["note"] == note

    async def test_the_failure_is_in_the_audit_log_with_its_reason(
        self, client_failing_wireframes: httpx.AsyncClient
    ) -> None:
        client = client_failing_wireframes
        project_id, run_id = await _start(client)
        await _advance(client, run_id)

        events = (await client.get("/audit", params={"project": project_id})).json()
        failed = next(e for e in events if e["action"] == "Failed to generate Wireframes")
        assert "told to fail" in failed["detail"]


class TestRetryingOneStage:
    """Retry should cost the stage it names and nothing else.

    It used to create an ordinary run, which walks the whole graph. With one node
    standing in for the component that quietly regenerated two artefacts; with
    one node per stage it would regenerate six, so asking for the wireframes
    again rewrote the requirements, the graph, the diagrams and the sprint plan
    the reader had just accepted.
    """

    async def test_it_calls_one_stage_and_not_the_others(self, client: httpx.AsyncClient) -> None:
        project_id, run_id = await _start(client)
        await _advance(client, run_id)

        component: CannedC1 = client.app.state.c1  # type: ignore[attr-defined]
        component.calls.clear()

        await client.post(f"/projects/{project_id}/design/stages/wireframes/retry")
        retry = (await client.get("/runs", params={"project": project_id})).json()[0]
        await _advance(client, retry["id"])

        assert component.calls == ["wireframes"], (
            f"a retry should ask for one stage; it asked for {component.calls}"
        )

    async def test_the_other_artefacts_are_left_alone(self, client: httpx.AsyncClient) -> None:
        project_id, run_id = await _start(client)
        await _advance(client, run_id)
        before = (await client.get(f"/projects/{project_id}/design")).json()

        await client.post(f"/projects/{project_id}/design/stages/wireframes/retry")
        retry = (await client.get("/runs", params={"project": project_id})).json()[0]
        await _advance(client, retry["id"])
        after = (await client.get(f"/projects/{project_id}/design")).json()

        assert after["sprint"] == before["sprint"]
        assert after["graph"]["nodes"] == before["graph"]["nodes"]
        assert after["requirements"] == before["requirements"]
        assert after["stages"]["wireframes"]["status"] == "complete"

    async def test_a_change_after_a_retry_waits_for_the_paused_run(
        self, client: httpx.AsyncClient
    ) -> None:
        """A retry is a run of its own that finishes in a moment, and the change
        note asked only the newest run whether the design was busy: it found the
        finished retry, opened version 2 and started a second full run beside
        the first, still paused at its review. That run crashed at the gate the
        first one held, and the project needed repairing by hand."""
        project_id, run_id = await _start(client)
        await _advance(client, run_id)
        await client.post(f"/projects/{project_id}/design/stages/wireframes/retry")
        retry = (await client.get("/runs", params={"project": project_id})).json()[0]
        await _advance(client, retry["id"])
        before = (await client.get("/runs", params={"project": project_id})).json()

        answer = await client.post(
            f"/projects/{project_id}/design/changes", json={"note": "add a genre field"}
        )

        assert answer.status_code == 200, answer.text
        after = (await client.get("/runs", params={"project": project_id})).json()
        assert len(after) == len(before), "a second full run started beside the paused one"
        assert answer.json()["requirementsVersion"] == 1, "the note waits; version 1 is reviewed"

    async def test_a_note_waiting_on_the_review_is_shown_on_it(
        self, client: httpx.AsyncClient
    ) -> None:
        """A note that arrives while the review waits applies only when the
        review is decided, and approving then started a new version nobody had
        been told about. The snapshot lists it, so the review can say so."""
        project_id, run_id = await _start(client)
        await _advance(client, run_id)

        await client.post(
            f"/projects/{project_id}/design/changes", json={"note": "add a genre field"}
        )

        snapshot = (await client.get(f"/projects/{project_id}/design")).json()
        assert snapshot["queuedChanges"] == ["add a genre field"]
        assert snapshot["requirementsVersion"] == 1

    async def test_it_finishes_without_opening_a_second_gate(
        self, client: httpx.AsyncClient
    ) -> None:
        """A retry is not a pass through the phase.

        Run with the gate still pending, which is when a reader actually
        retries: they are looking at the design, one stage is wrong, and they
        ask for it again before deciding. It is also the hazard, because a
        second gate on one project violates the partial unique index.
        """
        project_id, run_id = await _start(client)
        await _advance(client, run_id)
        before = (
            await client.get("/gates", params={"status": "pending", "project": project_id})
        ).json()
        assert len(before) == 1

        await client.post(f"/projects/{project_id}/design/stages/wireframes/retry")
        retry = (await client.get("/runs", params={"project": project_id})).json()[0]
        await _advance(client, retry["id"])

        assert (await client.get(f"/runs/{retry['id']}")).json()["state"] == "done"
        after = (
            await client.get("/gates", params={"status": "pending", "project": project_id})
        ).json()
        assert [g["id"] for g in after] == [g["id"] for g in before], "a retry opened a gate"

    async def test_a_retry_after_approval_is_refused_before_it_costs_anything(
        self, client: httpx.AsyncClient
    ) -> None:
        """An approved version is what was approved.

        Regenerating one artefact in place would leave the record saying a
        reader approved something that is no longer there. The refusal is at
        the route rather than at the write, so nothing is spent finding out:
        the node would have called the model first.
        """
        project_id, run_id = await _start(client)
        await _advance(client, run_id)
        await client.post(
            f"/projects/{project_id}/design/decision",
            json={"kind": "approved", "by": "A. Chen"},
        )
        component: CannedC1 = client.app.state.c1  # type: ignore[attr-defined]
        component.calls.clear()

        answer = await client.post(f"/projects/{project_id}/design/stages/uml-diagrams/retry")

        assert answer.status_code == 409
        assert "was approved" in answer.json()["error"]
        assert "Request a change instead" in answer.json()["error"]
        assert component.calls == [], "a refused retry still called the model"
        # And nothing was left mid flight by the refusal.
        snapshot = (await client.get(f"/projects/{project_id}/design")).json()
        spinning = [k for k, v in snapshot["stages"].items() if v["status"] == "generating"]
        assert spinning == []


class TestALoadBearingStageFailing:
    """When the graph fails, nothing may be left claiming to be generating.

    Requirements and the graph are load bearing, so a failure in either fails the
    run. That leaves the four stages after it never started, and they were marked
    generating when the run was queued. Generating is the one state a reader
    cannot act on: the client polls while anything is generating, so the strip
    spins forever over work that stopped.
    """

    @pytest.fixture
    async def client_failing_the_graph(
        self, settings: Settings
    ) -> AsyncIterator[httpx.AsyncClient]:
        app = create_app(settings, lifespan_factory=lifespan_for_tests)
        app.state.c1 = CannedC1(fails={"architecture-graph"})
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

    async def test_the_stage_that_broke_says_so_and_the_rest_go_back_to_pending(
        self, client_failing_the_graph: httpx.AsyncClient
    ) -> None:
        client = client_failing_the_graph
        project_id, run_id = await _start(client)
        await _advance(client, run_id)

        stages = (await client.get(f"/projects/{project_id}/design")).json()["stages"]

        assert stages["requirements"]["status"] == "complete"
        assert stages["architecture-graph"]["status"] == "failed"
        assert "told to fail" in stages["architecture-graph"]["error"]

        # The four after it never ran. Pending is the truthful answer, and it is
        # what stops the client polling.
        for stage_id in (
            "architecture-recommendation",
            "uml-diagrams",
            "wireframes",
            "sprint-plan",
        ):
            assert stages[stage_id]["status"] == "pending", (
                f"{stage_id} is {stages[stage_id]['status']} after the run died"
            )
            assert stages[stage_id]["error"] is None

    async def test_the_run_fails_and_names_what_it_never_reached(
        self, client_failing_the_graph: httpx.AsyncClient
    ) -> None:
        client = client_failing_the_graph
        project_id, run_id = await _start(client)
        await _advance(client, run_id)

        assert (await client.get(f"/runs/{run_id}")).json()["state"] == "failed"
        events = (await client.get("/audit", params={"project": project_id})).json()
        failed = next(e for e in events if e["action"] == "Run failed")
        assert "Stages not reached" in failed["detail"]
        assert "sprint-plan" in failed["detail"]

    async def test_no_gate_opens_on_a_design_that_was_never_built(
        self, client_failing_the_graph: httpx.AsyncClient
    ) -> None:
        client = client_failing_the_graph
        project_id, run_id = await _start(client)
        await _advance(client, run_id)
        gates = (
            await client.get("/gates", params={"status": "pending", "project": project_id})
        ).json()
        assert gates == [], "a gate opened on a design that was never built"


class TestTheGateIsReachable:
    """Every stage must read complete, or the decision bar never appears.

    The client decides the gate is waiting by asking whether all eight stages are
    complete. Two of them are projections that no component generates: the domain
    model is a view over the architecture graph, and the design review is the gate
    itself. Nothing was flipping the domain model, so it sat at pending for the
    life of the project and `gateWaiting` was false forever.

    That is not a cosmetic gap. It meant no design could be approved or sent back
    outside fixtures, and the gate is the entire point of the phase.
    """

    async def test_all_eight_stages_read_complete_at_the_gate(
        self, client: httpx.AsyncClient
    ) -> None:
        project_id, run_id = await _start(client)
        await _advance(client, run_id)

        stages = (await client.get(f"/projects/{project_id}/design")).json()["stages"]
        for stage_id in DESIGN_STAGE_IDS:
            assert stages[stage_id]["status"] == "complete", (
                f"{stage_id} is {stages[stage_id]['status']}, so the decision bar never renders"
            )
            assert stages[stage_id]["summary"], f"{stage_id} finished without saying so"

    async def test_the_domain_model_counts_the_graph_it_projects(
        self, client: httpx.AsyncClient
    ) -> None:
        # Counted rather than written, like every other summary, so it cannot
        # claim a number the design does not have.
        project_id, run_id = await _start(client)
        await _advance(client, run_id)
        snapshot = (await client.get(f"/projects/{project_id}/design")).json()

        entities = [n for n in snapshot["graph"]["nodes"] if n["kind"] == "entity"]
        summary = snapshot["stages"]["domain-model"]["summary"]
        assert str(len(entities)) in summary
        assert "entit" in summary

    async def test_a_failed_graph_leaves_the_projection_alone(self, settings: Settings) -> None:
        # The projection is as complete as its source and no more. If the graph
        # never landed there is nothing to project, and saying otherwise would put
        # a green tick on an empty page.
        app = create_app(settings, lifespan_factory=lifespan_for_tests)
        app.state.c1 = CannedC1(fails={"architecture-graph"})
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                c.app = app  # type: ignore[attr-defined]
                c.created_projects = []  # type: ignore[attr-defined]
                try:
                    project_id, run_id = await _start(c)
                    await _advance(c, run_id)
                    stages = (await c.get(f"/projects/{project_id}/design")).json()["stages"]
                    assert stages["architecture-graph"]["status"] == "failed"
                    assert stages["domain-model"]["status"] == "pending"
                finally:
                    async with app.state.pool.connection() as conn:
                        for pid in c.created_projects:  # type: ignore[attr-defined]
                            await store.delete_project(conn, pid, owner_id=DEV_OWNER_ID)
