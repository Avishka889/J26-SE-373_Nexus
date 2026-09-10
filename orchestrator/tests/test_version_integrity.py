"""A version, once approved, is what was approved.

All of this comes from one incident on the cold chain project. A design run
from three days earlier still had a stale heartbeat; the poller reclaimed it,
`advance` took the fresh start path because there was no resume payload, and
the graph walked from the first node. Requirements were re-extracted at version
1 and the upsert wrote them over the originals: twenty nine became seventeen,
the version did not move, the gate still said approved, and the rest of the
design was left tracing to twelve requirement ids that no longer existed.

Three guards, tested here, each closing a different link in that chain: the
restart itself, the reclaim of something far too old to recover, and the write
over an approved version.
"""

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.db.store import VersionAlreadyApproved
from orchestrator.graph.runner import RunSupervisor
from orchestrator.main import create_app, lifespan_for_tests

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


async def _designed(client: httpx.AsyncClient) -> tuple[str, str]:
    """A project whose design has run once."""
    created = await client.post("/projects", json={"name": "Version case"})
    project_id = created.json()["id"]
    client.created_projects.append(project_id)  # type: ignore[attr-defined]
    await client.patch(
        f"/projects/{project_id}", json={"requirementText": "Someone creates a record."}
    )
    runs = (await client.get("/runs", params={"project": project_id})).json()
    await _advance(client, runs[0]["id"])
    return project_id, runs[0]["id"]


class TestARunThatAlreadyRanIsNotRestarted:
    async def test_it_is_failed_and_says_why_instead_of_walking_again(self, client) -> None:
        project_id, run_id = await _designed(client)
        async with client.app.state.pool.connection() as conn:
            before = (await store.latest_artefacts(conn, project_id))["requirements"]["body"]
            # Exactly the shape the poller reclaimed: in flight, no decision
            # recorded, and a checkpoint from the walk it already did.
            await store.set_run_state(conn, run_id, "running")
        canned = client.app.state.c1
        canned.calls.clear()

        await _advance(client, run_id)

        assert canned.calls == [], "the graph was walked a second time"
        async with client.app.state.pool.connection() as conn:
            after = (await store.latest_artefacts(conn, project_id))["requirements"]["body"]
            run = await store.get_run(conn, run_id)
        assert after == before, "an artefact was rewritten by a restart"
        assert run["state"] == "failed"
        assert "would regenerate over what it already wrote" in run["error"]

    async def test_nothing_is_left_claiming_to_be_generating(self, client) -> None:
        project_id, run_id = await _designed(client)
        async with client.app.state.pool.connection() as conn:
            await store.set_stages(
                conn, project_id, ["wireframes", "sprint-plan"], status="generating"
            )
            await store.set_run_state(conn, run_id, "running")

        await _advance(client, run_id)

        snapshot = (await client.get(f"/projects/{project_id}/design")).json()
        spinning = [k for k, v in snapshot["stages"].items() if v["status"] == "generating"]
        assert spinning == [], "a stage was left spinning over work that had stopped"

    async def test_a_queued_run_that_never_started_still_starts(self, client) -> None:
        """The guard reads the checkpoint, not the state.

        Recovering a run that was committed and never submitted is the poller's
        whole purpose, and a rule phrased as "cannot resume, so fail" would have
        taken it away.
        """
        created = await client.post("/projects", json={"name": "Queued case"})
        project_id = created.json()["id"]
        client.created_projects.append(project_id)  # type: ignore[attr-defined]
        await client.patch(f"/projects/{project_id}", json={"requirementText": "A thing happens."})
        runs = (await client.get("/runs", params={"project": project_id})).json()

        await _advance(client, runs[0]["id"])

        async with client.app.state.pool.connection() as conn:
            artefacts = await store.latest_artefacts(conn, project_id)
        assert "requirements" in artefacts, "a queued run with no checkpoint must still run"


class TestAnAbandonedRunIsRetiredNotReclaimed:
    async def test_it_is_not_offered_to_a_worker(self, client) -> None:
        _project_id, run_id = await _designed(client)
        async with client.app.state.pool.connection() as conn:
            await store.set_run_state(conn, run_id, "running")
            await conn.execute(
                "UPDATE app.runs SET heartbeat_at = now() - interval '3 days' WHERE id = %s",
                (run_id,),
            )
            claimable = await store.claimable_runs(conn, stale_by_component={"c1": 90})
            abandoned = await store.abandoned_runs(conn)

        assert all(str(row["id"]) != str(run_id) for row in claimable), (
            "a three day old run was offered for reclaiming"
        )
        assert any(str(row["id"]) == str(run_id) for row in abandoned)

    async def test_a_merely_stalled_run_is_still_reclaimed(self, client) -> None:
        """The ceiling must not swallow the case the window exists for."""
        _project_id, run_id = await _designed(client)
        async with client.app.state.pool.connection() as conn:
            await store.set_run_state(conn, run_id, "running")
            await conn.execute(
                "UPDATE app.runs SET heartbeat_at = now() - interval '10 minutes' WHERE id = %s",
                (run_id,),
            )
            claimable = await store.claimable_runs(conn, stale_by_component={"c1": 90})
        assert any(str(row["id"]) == str(run_id) for row in claimable)

    async def test_a_run_that_died_before_its_first_heartbeat_is_still_claimable(
        self, client
    ) -> None:
        """The ceiling reads `started_at` when there is no heartbeat.

        A run that crashed on entry has a NULL there, and a NULL compared with
        anything is NULL, so a ceiling phrased as `heartbeat_at >` would have
        excluded the row from both halves of the query at once: too old to
        claim, too young to retire, in flight for ever.
        """
        _project_id, run_id = await _designed(client)
        async with client.app.state.pool.connection() as conn:
            await store.set_run_state(conn, run_id, "running")
            await conn.execute(
                "UPDATE app.runs SET heartbeat_at = NULL, started_at = now() - "
                "interval '10 minutes' WHERE id = %s",
                (run_id,),
            )
            claimable = await store.claimable_runs(conn, stale_by_component={"c1": 90})
        assert any(str(row["id"]) == str(run_id) for row in claimable), (
            "a run that never heartbeat was left in flight for ever"
        )

    async def test_retiring_says_so_and_stops_the_spinning(self, client) -> None:
        project_id, run_id = await _designed(client)
        async with client.app.state.pool.connection() as conn:
            await store.set_run_state(conn, run_id, "running")
            await store.set_stages(conn, project_id, ["wireframes"], status="generating")
            await conn.execute(
                "UPDATE app.runs SET heartbeat_at = now() - interval '3 days' WHERE id = %s",
                (run_id,),
            )
            row = (await store.abandoned_runs(conn))[0]

        await client.app.state.supervisor._retire(row)

        async with client.app.state.pool.connection() as conn:
            run = await store.get_run(conn, run_id)
        assert run["state"] == "failed"
        assert "went silent" in run["error"]
        snapshot = (await client.get(f"/projects/{project_id}/design")).json()
        assert snapshot["stages"]["wireframes"]["status"] != "generating"

    async def test_it_leaves_another_component_of_the_same_project_alone(self, client) -> None:
        """A project can have a design run abandoned while a code run is live.

        Clearing every generating row would tell the reader that work still
        happening had stopped, which is the same lie as a stage that spins over
        work that has finished, told the other way round.
        """
        project_id, run_id = await _designed(client)
        async with client.app.state.pool.connection() as conn:
            await store.set_run_state(conn, run_id, "running")
            await store.set_stages(conn, project_id, ["wireframes"], status="generating")
            await store.seed_code_stages(conn, project_id)
            await store.set_stages(conn, project_id, ["api-contract"], status="generating")
            await conn.execute(
                "UPDATE app.runs SET heartbeat_at = now() - interval '3 days' WHERE id = %s",
                (run_id,),
            )
            row = (await store.abandoned_runs(conn))[0]

        await client.app.state.supervisor._retire(row)

        async with client.app.state.pool.connection() as conn:
            stages = await store.stage_states(conn, project_id)
        by_id = {row["stage_id"]: row["status"] for row in stages}
        assert by_id["wireframes"] == "pending", "the retired run left its own stage spinning"
        assert by_id["api-contract"] == "generating", (
            "retiring a design run stopped a code run's stage from saying it was working"
        )


class TestAnApprovedVersionIsImmutable:
    async def test_writing_over_an_approved_design_is_refused(self, client) -> None:
        project_id, _run_id = await _designed(client)
        approved = await client.post(
            f"/projects/{project_id}/design/decision",
            json={"kind": "approved", "by": "you"},
        )
        assert approved.status_code == 200

        async with client.app.state.pool.connection() as conn:
            with pytest.raises(VersionAlreadyApproved) as refused:
                await store.put_artefact(
                    conn,
                    project_id=project_id,
                    kind="requirements",
                    version=1,
                    body={"requirements": []},
                )
        assert "was approved" in str(refused.value)
        assert "open a new version" in str(refused.value).lower()

    async def test_an_unapproved_version_is_still_writable(self, client) -> None:
        """Retries and re-executed nodes depend on the upsert, so the guard has
        to bite only where a decision has been recorded."""
        project_id, _ = await _designed(client)
        async with client.app.state.pool.connection() as conn:
            await store.put_artefact(
                conn,
                project_id=project_id,
                kind="requirements",
                version=1,
                body={"requirements": []},
            )
            body = (await store.latest_artefacts(conn, project_id))["requirements"]["body"]
        assert body == {"requirements": []}

    async def test_the_other_axis_is_not_affected_by_a_design_approval(self, client) -> None:
        """A design gate decides design versions. A code artefact at the same
        number is a different axis and must stay writable."""
        project_id, _ = await _designed(client)
        await client.post(
            f"/projects/{project_id}/design/decision", json={"kind": "approved", "by": "you"}
        )
        async with client.app.state.pool.connection() as conn:
            await store.put_artefact(
                conn, project_id=project_id, kind="tech-stack", version=1, body={"ok": True}
            )


class TestTheDecisionRecordsWhatWasOpen:
    async def test_an_approval_names_the_findings_that_were_open(self, client) -> None:
        project_id, _run_id = await _designed(client)
        # A node tracing to a requirement that is not there: exactly what the
        # cold chain design was approved over, thirty nine times.
        async with client.app.state.pool.connection() as conn:
            graph = (await store.latest_artefacts(conn, project_id))["architecture-graph"]["body"]
            graph["nodes"][0]["traces"] = ["R-404"]
            await store.put_artefact(
                conn,
                project_id=project_id,
                kind="architecture-graph",
                version=1,
                body=graph,
            )

        # Approving over an open error needs a reason, said with the approval.
        refused = await client.post(
            f"/projects/{project_id}/design/decision", json={"kind": "approved", "by": "you"}
        )
        assert refused.status_code == 409
        assert "1 consistency error" in refused.json()["error"]
        await client.post(
            f"/projects/{project_id}/design/decision",
            json={"kind": "approved", "by": "you", "note": "R-404 is restored next version."},
        )

        trail = (await client.get("/audit", params={"project": project_id})).json()
        approval = next(row for row in trail if row["action"] == "Approved the design")
        assert "consistency error" in approval["detail"]
        assert "R-404 is restored next version." in approval["detail"]

    async def test_a_clean_approval_says_that_too(self, client) -> None:
        """Silence would read the same as unread. The record has to distinguish
        an approval over a clean report from one over an unread report."""
        project_id, _ = await _designed(client)
        await client.post(
            f"/projects/{project_id}/design/decision", json={"kind": "approved", "by": "you"}
        )
        trail = (await client.get("/audit", params={"project": project_id})).json()
        approval = next(row for row in trail if row["action"] == "Approved the design")
        assert "consistency" in approval["detail"]
