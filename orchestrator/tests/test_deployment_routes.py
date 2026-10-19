"""The deployment routes, driven over HTTP against a real database.

The phase's graph is proved in the spine test; these prove the doors into it.
A run starts only from a test version the review approved, on the code those
tests measured, while any newer code waits for its own tests; a decision needs
what every gate needs; and an approved deploy version is settled.
"""

import hashlib
import json
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.deploy import guards
from orchestrator.main import create_app, lifespan_for_tests
from orchestrator.saga.runner import authorise_release
from sdlc_contracts import (
    CODE_ARTEFACT_KINDS,
    CODE_GENERATING_STAGE_IDS,
    DEPLOY_STAGE_IDS,
    AtlasDatabase,
    DeploySnapshot,
)

from .conftest import needs_db
from .test_testing_routes import _advance, _through_code

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


async def _approved_tests(client: httpx.AsyncClient) -> str:
    """A project whose current code the test review approved."""
    project_id = await _through_code(client)
    await client.post(f"/projects/{project_id}/testing/run")
    runs = (await client.get("/runs", params={"project": project_id})).json()
    await _advance(client, runs[0]["id"])
    decided = await client.post(
        f"/projects/{project_id}/testing/decision", json={"kind": "approved", "by": "you"}
    )
    assert decided.status_code == 200, decided.text
    await _advance(client, runs[0]["id"])
    return project_id


async def _deploy_run(client: httpx.AsyncClient, project_id: str) -> str:
    started = await client.post(f"/projects/{project_id}/deployment/run")
    assert started.status_code == 200, started.text
    runs = (await client.get("/runs", params={"project": project_id})).json()
    run_id = next(run["id"] for run in runs if run["component"] == "c4")
    await _advance(client, run_id)
    return run_id


async def _newer_code(
    client: httpx.AsyncClient, project_id: str, *, tested: bool, sprint: int | None = None
) -> int:
    """A newer code version, approved, and with `tested` its tests approved too.

    With `sprint`, the build's first story is planned in that sprint, as planning
    the next sprint puts a story in the build.
    """
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        current = await store.current_code_version(conn, project_id)
        newer = current + 1
        design_version = await store.current_version(conn, project_id)
        # What a regeneration writes: every code artefact, at the new version.
        found = await store.artefacts_at(
            conn, project_id, version=current, kinds=CODE_ARTEFACT_KINDS
        )
        for kind, row in found.items():
            body = row["body"]
            if kind == "sprint-scope" and sprint is not None:
                first, *rest = body["stories"]
                body = {**body, "stories": [{**first, "inScope": True, "sprint": sprint}, *rest]}
            await store.put_artefact(
                conn, project_id=project_id, kind=kind, version=newer, body=body
            )
        for stage_id in (*CODE_GENERATING_STAGE_IDS, store.TEST_FILE_STAGE):
            files = await store.code_files(conn, project_id, version=current, stage_id=stage_id)
            if files:
                await store.put_code_files(
                    conn, project_id, version=newer, stage_id=stage_id, files=files
                )
        run = await store.create_run(
            conn,
            project_id=project_id,
            requirements_version=newer,
            component="c2",
            source_version=design_version,
        )
        gate = await store.open_gate(
            conn,
            run_id=run["id"],
            project_id=project_id,
            requirements_version=newer,
            payload={},
            interrupt_id=None,
            kind="c2-code-review",
        )
        await store.resolve_gate(conn, gate["id"], decision="approved", by="you", note="")
        await store.set_run_state(conn, run["id"], "done")
    if tested:
        started = await client.post(f"/projects/{project_id}/testing/run")
        assert started.status_code == 200, started.text
        runs = (await client.get("/runs", params={"project": project_id})).json()
        testing = next(r for r in runs if r["component"] == "c3" and r["state"] == "queued")
        await _advance(client, testing["id"])
        decided = await client.post(
            f"/projects/{project_id}/testing/decision", json={"kind": "approved", "by": "you"}
        )
        assert decided.status_code == 200, decided.text
        await _advance(client, testing["id"])
    return newer


async def _both_statuses(client: httpx.AsyncClient, project_id: str) -> tuple[str, str]:
    """The status the project list shows, and the one the project itself shows."""
    listed = next(p for p in (await client.get("/projects")).json() if p["id"] == project_id)
    alone = (await client.get(f"/projects/{project_id}")).json()
    return listed["status"], alone["status"]


async def _both_progress(client: httpx.AsyncClient, project_id: str) -> tuple[int, int]:
    """The overall progress the sidebar shows, and the one the project header shows."""
    listed = next(p for p in (await client.get("/projects")).json() if p["id"] == project_id)
    alone = (await client.get(f"/projects/{project_id}")).json()
    assert listed["phaseProgress"] == alone["phaseProgress"]
    return listed["progress"], alone["progress"]


async def _finished(client: httpx.AsyncClient, project_id: str, *, state: str, verified: bool):
    """A release of deploy version 1, planted as a run leaves it: the version's
    analysis is written first. A project counts as released only by a release of
    the deploy version it is on, so a release with no version behind it is a
    state no run produces."""
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        await store.put_artefact(
            conn, project_id=project_id, kind="deploy-plan", version=1, body={}
        )
        row, _ = await store.create_deployment(
            conn,
            project_id=project_id,
            deploy_version=1,
            kind="release",
            target="local",
            plan_id=f"{project_id}-deploy-v1",
            candidate_hash="c" * 64,
            idempotency_key=f"{project_id}-{state}",
            authorised={"kind": "gate", "by": "you", "gateId": "g-1"},
            requested_by="you",
        )
        await store.finish_deployment(conn, row["id"], state=state, verified=verified)


class TestTheProjectStatus:
    """The ladder's last two rungs, in the list and on the project alike.

    The server's ladder stopped at testing, so a project the test review approved,
    and one released to the cloud, both read "Testing" in the page's header.
    """

    async def test_an_approved_test_review_reads_as_deploy(self, client) -> None:
        project_id = await _approved_tests(client)
        assert await _both_statuses(client, project_id) == ("deploy", "deploy")
        # Three phases of four finished, and nothing deployed. It read 100.
        assert await _both_progress(client, project_id) == (75, 75)

    async def test_a_deployment_waiting_on_its_review_is_not_finished(self, client) -> None:
        project_id = await _approved_tests(client)
        await _deploy_run(client, project_id)
        assert await _both_progress(client, project_id) == (95, 95)

    async def test_a_verified_release_reads_as_complete(self, client) -> None:
        project_id = await _approved_tests(client)
        await _finished(client, project_id, state="succeeded", verified=True)
        assert await _both_statuses(client, project_id) == ("complete", "complete")
        assert await _both_progress(client, project_id) == (100, 100)

    async def test_a_release_that_failed_is_not_complete(self, client) -> None:
        project_id = await _approved_tests(client)
        await _finished(client, project_id, state="failed", verified=False)
        assert await _both_statuses(client, project_id) == ("deploy", "deploy")
        assert await _both_progress(client, project_id) == (75, 75)


class TestTheSnapshot:
    async def test_a_new_project_has_every_stage_pending(self, client) -> None:
        created = await client.post("/projects", json={"name": "Fresh", "description": ""})
        project_id = created.json()["id"]
        client.created_projects.append(project_id)

        answer = await client.get(f"/projects/{project_id}/deployment")

        assert answer.status_code == 200, answer.text
        snapshot = DeploySnapshot.model_validate(answer.json())
        assert set(snapshot.stages) == set(DEPLOY_STAGE_IDS)
        assert all(stage.status == "pending" for stage in snapshot.stages.values())
        assert snapshot.deploy_version == 0 and snapshot.approved_test_version == 0
        assert snapshot.release_target == "local"


class TestStartingARun:
    async def test_nothing_starts_before_the_test_review_approves(self, client) -> None:
        project_id = await _through_code(client)

        answer = await client.post(f"/projects/{project_id}/deployment/run")

        assert answer.status_code == 409
        assert "has not approved a run on the generated app" in answer.text

    async def test_a_run_starts_on_the_tested_code_while_newer_code_waits_for_its_tests(
        self, client
    ) -> None:
        """Approved tests of code version 1 say nothing about code version 2, so
        version 1 is what a run analyses and what may ship. The run was refused
        instead, and nothing could be released until the next sprint was tested."""
        project_id = await _approved_tests(client)
        newer = await _newer_code(client, project_id, tested=False)

        await _deploy_run(client, project_id)

        snapshot = DeploySnapshot.model_validate(
            (await client.get(f"/projects/{project_id}/deployment")).json()
        )
        assert snapshot.code_version == newer
        assert snapshot.deployed_code_version == snapshot.approved_tested_code_version == newer - 1
        assert not snapshot.code_moved_on
        # And which tests the analysis started from, for the review to say (C4-7).
        assert snapshot.analysed_test_version == snapshot.approved_test_version > 0
        assert not [blocker for blocker in snapshot.blocking if blocker.code == "G4"]

    async def test_a_samples_approved_run_does_not_unlock_the_apps_deployment(self, client) -> None:
        """An approved run on a sample says nothing about the generated app, and
        Deployment took the newest approved test version whatever it measured
        (review item C3-3)."""
        project_id = await _through_code(client)
        async with client.app.state.pool.connection() as conn:
            await store.put_overlay(
                conn,
                project_id=project_id,
                version=1,
                kind="target_selection",
                target_id="target",
                value="sample:java",
                by="you",
            )
        await client.post(f"/projects/{project_id}/testing/run")
        runs = (await client.get("/runs", params={"project": project_id})).json()
        await _advance(client, runs[0]["id"])
        approved = await client.post(
            f"/projects/{project_id}/testing/decision", json={"kind": "approved", "by": "you"}
        )
        assert approved.status_code == 200, approved.text
        said = approved.json()["thread"][-1]["content"]
        assert "Deployment can start" not in said and "does not unlock Deployment" in said

        answer = await client.post(f"/projects/{project_id}/deployment/run")

        assert answer.status_code == 409
        assert "has not approved a run on the generated app" in answer.text
        snapshot = DeploySnapshot.model_validate(
            (await client.get(f"/projects/{project_id}/deployment")).json()
        )
        assert snapshot.approved_test_version == 0
        assert (await client.get(f"/projects/{project_id}")).json()["status"] == "testing"

    async def test_a_run_from_approved_tests_reaches_its_gate(self, client) -> None:
        project_id = await _approved_tests(client)

        await _deploy_run(client, project_id)

        snapshot = DeploySnapshot.model_validate(
            (await client.get(f"/projects/{project_id}/deployment")).json()
        )
        assert snapshot.deploy_version == 1
        assert snapshot.approved_test_version == snapshot.test_version == 1
        assert snapshot.deployed_code_version == snapshot.code_version
        assert snapshot.risk is not None and snapshot.gate.decision is None
        # Owed exactly where the release guard asks (G1): Medium and High updates
        # the candidate carries.
        owed = {item.update_id for item in snapshot.decisions if item.needs_decision}
        levels = {a.update_id: a.arbitration.final for a in snapshot.risk.assessments}
        assert snapshot.candidate is not None
        carried = set(snapshot.candidate.included)
        assert owed == {uid for uid, level in levels.items() if level != "low" and uid in carried}
        assert owed, "the run carries a Medium update, which a person decides"

    async def test_an_update_the_candidate_left_out_owes_no_decision(self, client) -> None:
        """What the live walkthrough met. A High update on a first release has no
        verified release to roll back to, so the candidate leaves it out and the
        release guard asks nothing about it; the snapshot asked for a decision on
        it all the same, and the page showed one owed that counted towards
        nothing."""
        project_id = await _approved_tests(client)
        await _deploy_run(client, project_id)

        snapshot = DeploySnapshot.model_validate(
            (await client.get(f"/projects/{project_id}/deployment")).json()
        )
        assert snapshot.candidate is not None
        left_out = {item.update_id for item in snapshot.candidate.excluded}
        assert left_out, "a first release leaves its High update out"
        views = {view.update_id: view for view in snapshot.decisions}
        assert not any(views[update_id].needs_decision for update_id in left_out)
        assert not any(blocker.update_id in left_out for blocker in snapshot.blocking)
        assert snapshot.awaiting_decision == len(
            [view for view in snapshot.decisions if view.needs_decision]
        )

    async def test_a_second_run_waits_for_the_first_review(self, client) -> None:
        project_id = await _approved_tests(client)
        await _deploy_run(client, project_id)

        answer = await client.post(f"/projects/{project_id}/deployment/run")

        assert answer.status_code == 409
        assert "deployment review is waiting" in answer.text


class TestTheApprovedTestsShip:
    """Deployment's staging build reads the tests at the tested code version, and they
    could change after their approval: a later run on the same code rewrites them
    (review item X-2). The approval records what it approved, and the release
    holds while the tests are not those."""

    async def test_tests_changed_after_their_approval_hold_the_release(self, client) -> None:
        project_id = await _approved_tests(client)
        await _deploy_run(client, project_id)
        async with client.app.state.pool.connection() as conn:
            files = await store.code_files(
                conn, project_id, version=1, stage_id=store.TEST_FILE_STAGE
            )
            assert files, "the approved run wrote its tests"
            path, content = next(iter(files.items()))
            await store.put_code_files(
                conn,
                project_id,
                version=1,
                stage_id=store.TEST_FILE_STAGE,
                files={**files, path: content + "\n// changed after the approval\n"},
            )

        snapshot = DeploySnapshot.model_validate(
            (await client.get(f"/projects/{project_id}/deployment")).json()
        )

        [g4] = [blocker for blocker in snapshot.blocking if blocker.code == "G4"]
        assert g4.message == (
            "the tests at code version 1 changed after test version 1 was approved: run the "
            "tests again and approve them, so the release runs the tests a person approved"
        )


class TestAReviewTheCodeMovedPast:
    """A deployment review waiting while newer code is tested and approved is of an
    analysis of code that is no longer the newest that may ship. Its approval is
    refused (G4), requested changes would analyse the same older code again, and a
    new run closes it. Newer code whose tests are not approved yet leaves the
    review standing: the code it analysed is still what may ship."""

    async def test_analysing_again_closes_it_once_the_newer_code_is_tested(self, client) -> None:
        project_id = await _approved_tests(client)
        waiting = await _deploy_run(client, project_id)
        newer = await _newer_code(client, project_id, tested=True)

        answer = await client.post(f"/projects/{project_id}/deployment/run")

        assert answer.status_code == 200, answer.text
        async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
            closed = await store.get_run(conn, uuid.UUID(waiting))
            history = await store.gate_history(conn, project_id, kind="c4-deploy-review")
            fresh = await store.latest_run(conn, project_id)
            tested = await store.run_for_version(
                conn, project_id, component="c3", version=int(fresh["source_version"])
            )
        assert closed is not None and closed["state"] == "superseded"
        assert history[-1]["decision"] == "changes"
        assert f"version {newer} has approved tests now" in history[-1]["note"]
        assert fresh["component"] == "c4" and str(fresh["id"]) != waiting
        assert tested is not None and tested["source_version"] == newer

    async def test_until_the_newer_code_is_tested_the_review_stays(self, client) -> None:
        """The code it analysed is still what may ship, so it is not stale: a new
        run waits for it as for any review, and G4 has nothing to say."""
        project_id = await _approved_tests(client)
        await _deploy_run(client, project_id)
        await _newer_code(client, project_id, tested=False)

        answer = await client.post(f"/projects/{project_id}/deployment/run")

        assert answer.status_code == 409
        assert "deployment review is waiting" in answer.text
        snapshot = DeploySnapshot.model_validate(
            (await client.get(f"/projects/{project_id}/deployment")).json()
        )
        assert snapshot.gate.decision is None and not snapshot.code_moved_on
        assert not [blocker for blocker in snapshot.blocking if blocker.code == "G4"]

    async def test_until_then_requesting_changes_analyses_the_tested_code_again(
        self, client
    ) -> None:
        project_id = await _approved_tests(client)
        run_id = await _deploy_run(client, project_id)
        newer = await _newer_code(client, project_id, tested=False)

        answer = await client.post(
            f"/projects/{project_id}/deployment/decision",
            json={"kind": "changes", "by": "you", "note": "leave supertest out"},
        )
        assert answer.status_code == 200, answer.text
        await _advance(client, run_id)

        snapshot = DeploySnapshot.model_validate(
            (await client.get(f"/projects/{project_id}/deployment")).json()
        )
        assert snapshot.deploy_version == 2
        assert snapshot.deployed_code_version == newer - 1

    async def test_requesting_changes_once_it_is_tested_is_refused_and_says_what_to_do(
        self, client
    ) -> None:
        """Changes would analyse the older code again: analysing again is the way on."""
        project_id = await _approved_tests(client)
        await _deploy_run(client, project_id)
        newer = await _newer_code(client, project_id, tested=True)

        refused = await client.post(
            f"/projects/{project_id}/deployment/decision",
            json={"kind": "changes", "by": "you", "note": "leave supertest out"},
        )

        assert refused.status_code == 409
        assert "would analyse the older code again" in refused.text
        assert f"Analyse the updates again: that analyses version {newer}" in refused.text


class TestNewerCodeWaitingForItsTests:
    """The next sprint's code held production back. G4 and the checks around it
    read the newest code version written, tested or not, so once sprint 2's code
    existed nothing could be approved, handed to the saga or released again until
    it was tested too. What ships is the code the newest approved tests measured;
    newer code waits for its own tests and holds nothing back."""

    async def test_the_review_is_approved_and_releases_the_tested_code(self, client) -> None:
        project_id = await _approved_tests(client)
        run_id = await _deploy_run(client, project_id)
        newer = await _newer_code(client, project_id, tested=False)
        await _decide_every_update(client, project_id)

        approved = await client.post(
            f"/projects/{project_id}/deployment/decision", json={"kind": "approved", "by": "you"}
        )
        assert approved.status_code == 200, approved.text
        await _advance(client, run_id)

        snapshot = DeploySnapshot.model_validate(
            (await client.get(f"/projects/{project_id}/deployment")).json()
        )
        assert snapshot.candidate is not None and snapshot.candidate.code_version == newer - 1
        [release] = snapshot.deployments
        assert release.kind == "release" and release.state == "pending"

    async def test_the_saga_asks_the_guards_again_and_they_still_hold(self, client) -> None:
        """Before its first step the saga asks the guards again, under the
        authorisation the release recorded: newer code written in between is
        not a reason to refuse it."""
        project_id = await _approved_tests(client)
        run_id = await _deploy_run(client, project_id)
        await _decide_every_update(client, project_id)
        approved = await client.post(
            f"/projects/{project_id}/deployment/decision", json={"kind": "approved", "by": "you"}
        )
        assert approved.status_code == 200, approved.text
        await _advance(client, run_id)
        await _newer_code(client, project_id, tested=False)

        async with client.app.state.pool.connection() as conn:
            [release] = await store.list_deployments(conn, project_id)
            blockers = await authorise_release(conn, release)

        assert blockers == []


class TestTheCloudTarget:
    """A cloud run makes the project's Vercel project and Render service before the layer
    is generated, so the layer names the addresses they really have. The canned component
    answers for the resources, so this never reaches Vercel or Render."""

    async def test_a_cloud_run_makes_the_resources_and_generates_for_their_addresses(
        self, client
    ) -> None:
        project_id = await _approved_tests(client)
        await client.post(
            f"/projects/{project_id}/deployment/target", json={"target": "cloud", "by": "you"}
        )
        await _deploy_run(client, project_id)

        canned = client.app.state.clients["c4"]
        assert canned.provisioned == [project_id]
        slug = project_id.lower().replace("_", "-")
        given = canned.pipeline_settings[-1]
        assert given["backend_origin"] == f"https://{slug}-api.onrender.com"
        assert given["frontend_origin"] == f"https://{slug}.vercel.app"

    async def test_a_local_run_makes_nothing_in_the_cloud(self, client) -> None:
        project_id = await _approved_tests(client)
        await _deploy_run(client, project_id)

        canned = client.app.state.clients["c4"]
        assert canned.provisioned == []
        assert "backend_origin" not in canned.pipeline_settings[-1]
        assert canned.rollback_database == [False], "a local release keeps no database"

    async def test_the_rollback_plan_hears_that_the_project_has_a_database(self, client) -> None:
        """So its note can say a restore leaves the records where they are."""
        project_id = await _approved_tests(client)
        await client.post(
            f"/projects/{project_id}/deployment/target", json={"target": "cloud", "by": "you"}
        )
        canned = client.app.state.clients["c4"]
        made = await canned.provision_cloud(project_id)
        kept = made.model_copy(
            update={
                "database": AtlasDatabase(
                    cluster="Cluster0",
                    host="cluster0.ab1cd.mongodb.net",
                    database="p",
                    username="app-p",
                    service_id=made.render.service_id,
                )
            }
        )
        async with client.app.state.pool.connection() as conn:
            owner = (await store.project_without_owner_check(conn, project_id))["owner_id"]
            await store.put_settings_section(
                conn, owner, ("cloud", project_id), kept.model_dump(by_alias=True, mode="json")
            )
        try:
            await _deploy_run(client, project_id)
        finally:
            async with client.app.state.pool.connection() as conn:
                body = await store.settings_body(conn, owner)
                body.get("cloud", {}).pop(project_id, None)
                await store.put_settings_body(conn, owner, body)

        assert canned.rollback_database == [True]


async def _decide_every_update(client, project_id: str) -> None:
    """Approve every update that needs a person, with the note a High one needs."""
    snapshot = DeploySnapshot.model_validate(
        (await client.get(f"/projects/{project_id}/deployment")).json()
    )
    for view in snapshot.decisions:
        if view.needs_decision:
            answer = await client.post(
                f"/projects/{project_id}/deployment/updates/{view.update_id}/decision",
                json={"decision": "approved", "by": "you", "note": "reviewed the changes"},
            )
            assert answer.status_code == 200, answer.text


class TestTheGate:
    async def test_there_is_nothing_to_decide_before_a_run(self, client) -> None:
        project_id = await _approved_tests(client)
        answer = await client.post(
            f"/projects/{project_id}/deployment/decision", json={"kind": "approved", "by": "you"}
        )
        assert answer.status_code == 409

    async def test_changes_need_a_note(self, client) -> None:
        project_id = await _approved_tests(client)
        await _deploy_run(client, project_id)

        answer = await client.post(
            f"/projects/{project_id}/deployment/decision", json={"kind": "changes", "by": "you"}
        )

        assert answer.status_code == 409
        assert "needs a note" in answer.text

    async def test_changes_regenerate_at_the_next_deploy_version(self, client) -> None:
        project_id = await _approved_tests(client)
        run_id = await _deploy_run(client, project_id)

        answer = await client.post(
            f"/projects/{project_id}/deployment/decision",
            json={"kind": "changes", "by": "you", "note": "leave vite out"},
        )
        assert answer.status_code == 200, answer.text
        await _advance(client, run_id)

        snapshot = DeploySnapshot.model_validate(
            (await client.get(f"/projects/{project_id}/deployment")).json()
        )
        assert snapshot.deploy_version == 2
        async with client.app.state.pool.connection() as conn:
            gate = await store.pending_gate(conn, project_id=project_id, kind="c4-deploy-review")
        assert gate is not None and gate["requirements_version"] == 2

    async def test_an_approved_version_is_settled(self, client) -> None:
        project_id = await _approved_tests(client)
        await _deploy_run(client, project_id)
        await _decide_every_update(client, project_id)
        approved = await client.post(
            f"/projects/{project_id}/deployment/decision", json={"kind": "approved", "by": "you"}
        )
        assert approved.status_code == 200, approved.text

        retried = await client.post(
            f"/projects/{project_id}/deployment/stages/risk-assessment/retry"
        )

        assert retried.status_code == 409
        assert "was approved" in retried.text
        snapshot = DeploySnapshot.model_validate(approved.json())
        assert snapshot.gate.decision is not None and snapshot.gate.decision.kind == "approved"


class TestWhatThePageWaitsFor:
    """The page reads the phase again only while something is working, so the moment
    between an approval and the release being written must say it is working: it
    did not, and Book Tracker's first cloud release showed as never run while it
    served."""

    async def test_an_approved_release_is_working_until_the_runner_writes_it(self, client) -> None:
        project_id = await _approved_tests(client)
        run_id = await _deploy_run(client, project_id)
        await _decide_every_update(client, project_id)
        waiting = (await client.get(f"/projects/{project_id}/deployment")).json()

        approved = await client.post(
            f"/projects/{project_id}/deployment/decision", json={"kind": "approved", "by": "you"}
        )

        assert approved.status_code == 200, approved.text
        assert waiting["stages"]["release"]["status"] == "pending", "a review is not a release"
        assert approved.json()["stages"]["release"]["status"] == "generating"
        await _advance(client, run_id)
        after = (await client.get(f"/projects/{project_id}/deployment")).json()
        assert [one["deployVersion"] for one in after["deployments"]] == [1]
        # The written release carries the rest: the page polls while it is pending.
        assert after["stages"]["release"]["status"] == "pending"
        assert after["deployments"][0]["state"] == "pending"


class TestSettings:
    async def test_the_release_policy_is_a_recorded_choice(self, client) -> None:
        project_id = await _approved_tests(client)
        answer = await client.post(
            f"/projects/{project_id}/deployment/policy", json={"autoDeployLow": True, "by": "you"}
        )
        assert answer.status_code == 200, answer.text
        assert DeploySnapshot.model_validate(answer.json()).auto_deploy_low is True

    async def test_the_release_target_is_a_recorded_choice(self, client) -> None:
        project_id = await _approved_tests(client)

        answer = await client.post(
            f"/projects/{project_id}/deployment/target", json={"target": "cloud", "by": "you"}
        )

        assert answer.status_code == 200, answer.text
        assert answer.json()["releaseTarget"] == "cloud"

    async def test_an_unknown_target_is_refused(self, client) -> None:
        project_id = await _approved_tests(client)
        answer = await client.post(
            f"/projects/{project_id}/deployment/target", json={"target": "azure", "by": "you"}
        )
        assert answer.status_code == 422

    async def test_the_cloud_is_usable_only_with_its_connections(self, client, monkeypatch) -> None:
        """It read usable on the server setting alone, and a release chosen for
        it was refused at the review for a connection nobody had made.

        The account's connections are read through a stand-in: this client acts
        as the development identity, whose real settings a test must not write.
        """
        from orchestrator.config import get_settings

        monkeypatch.setattr(get_settings(), "c4_cloud_enabled", True)
        project_id = await _approved_tests(client)
        connected: dict[str, dict] = {}

        async def settings_body(conn, owner_id):
            return {"connections": dict(connected)}

        monkeypatch.setattr(store, "settings_body", settings_body)

        async def cloud() -> dict:
            answer = await client.get(f"/projects/{project_id}/deployment/targets")
            return next(one for one in answer.json() if one["id"] == "cloud")

        bare = await cloud()
        assert bare["usable"] is False
        assert bare["reason"] == "connect GitHub, Vercel and Render in Settings first"

        works = {"probe": {"verdict": "SUITABLE", "reason": "Authenticates."}}
        connected.update(github=works, vercel=works)
        assert (await cloud())["reason"] == "connect Render in Settings first"

        # Connected is not working: the check's verdict was stored and never
        # read, so a refused key read as usable (review item X-12).
        connected.update(render={"probe": {"verdict": "UNUSABLE", "reason": "Render refused it."}})
        refused = await cloud()
        assert refused["usable"] is False
        assert refused["reason"] == (
            "the Render connection is not working (Render refused it.): check it again in Settings"
        )
        async with client.app.state.pool.connection() as conn:
            facts = await guards.gather(
                conn, project_id, owner="anyone", deploy_version=0, target="cloud", test_version=0
            )
        assert facts.connected == frozenset({"github", "vercel"})
        assert facts.failing == {"render": "Render refused it."}

        connected.update(render=works)
        ready = await cloud()
        assert ready["usable"] is True and ready["reason"] == ""

    async def test_the_snapshot_says_what_a_run_would_analyse(self, client) -> None:
        """The first-run screen said the approved tests measured the current
        code whatever they measured, and the chosen packages were nowhere."""
        project_id = await _approved_tests(client)
        scoped = await client.post(
            f"/projects/{project_id}/deployment/scope",
            json={"target": "generated", "packages": ["express", "zod"]},
        )

        snapshot = scoped.json()
        assert scoped.status_code == 200, scoped.text
        assert snapshot["scopePackages"] == ["express", "zod"]
        assert snapshot["approvedTestedCodeVersion"] == snapshot["codeVersion"] > 0

    async def test_the_snapshot_counts_every_attempt_beyond_the_ten_it_shows(self, client) -> None:
        project_id = await _approved_tests(client)
        async with client.app.state.pool.connection() as conn:
            for attempt in range(12):
                row, _ = await store.create_deployment(
                    conn,
                    project_id=project_id,
                    deploy_version=1,
                    kind="release",
                    target="local",
                    plan_id="plan-1",
                    candidate_hash="c" * 64,
                    idempotency_key=f"attempt-{attempt}",
                    authorised={"by": "you"},
                    requested_by="you",
                )
                await store.finish_deployment(conn, row["id"], state="failed", cause="boot failed")

        snapshot = (await client.get(f"/projects/{project_id}/deployment")).json()

        assert len(snapshot["deployments"]) == 10
        assert snapshot["deploymentsTotal"] == 12


async def _risk_row(client, project_id: str) -> tuple[DeploySnapshot, str]:
    """The snapshot, and the sha256 of the stored risk report exactly as stored."""
    async with client.app.state.pool.connection() as conn:
        version = await store.current_deploy_version(conn, project_id)
        found = await store.artefacts_at(conn, project_id, version=version, kinds=("risk-report",))
    snapshot = DeploySnapshot.model_validate(
        (await client.get(f"/projects/{project_id}/deployment")).json()
    )
    body = json.dumps(found["risk-report"]["body"], sort_keys=True).encode()
    return snapshot, hashlib.sha256(body).hexdigest()


def _by_package(snapshot: DeploySnapshot, package: str) -> str:
    """The update id of one package's assessment."""
    assert snapshot.risk is not None
    return next(a.update_id for a in snapshot.risk.assessments if a.package == package)


class TestUpdateDecisions:
    """A person's decision about an update sits beside the report, never inside it."""

    async def test_a_decision_is_laid_beside_the_report_and_the_report_does_not_move(
        self, client
    ) -> None:
        project_id = await _approved_tests(client)
        await _deploy_run(client, project_id)
        snapshot, before = await _risk_row(client, project_id)
        zod = _by_package(snapshot, "zod")

        answer = await client.post(
            f"/projects/{project_id}/deployment/updates/{zod}/decision",
            json={"decision": "approved", "by": "you"},
        )

        assert answer.status_code == 200, answer.text
        decided = DeploySnapshot.model_validate(answer.json())
        [view] = [d for d in decided.decisions if d.update_id == zod]
        assert (view.decision, view.level_at_decision) == ("approved", "medium")
        _, after = await _risk_row(client, project_id)
        assert after == before

    async def test_approving_a_high_update_needs_a_review_note(self, client) -> None:
        project_id = await _approved_tests(client)
        await _deploy_run(client, project_id)
        snapshot, _ = await _risk_row(client, project_id)
        express = _by_package(snapshot, "express")
        route = f"/projects/{project_id}/deployment/updates/{express}/decision"

        bare = await client.post(route, json={"decision": "approved", "by": "you"})
        noted = await client.post(
            route, json={"decision": "approved", "by": "you", "note": "app.del is gone; fixed"}
        )

        assert bare.status_code == 409 and "review note" in bare.json()["error"]
        assert noted.status_code == 200, noted.text

    async def test_leaving_an_update_out_needs_a_reason(self, client) -> None:
        project_id = await _approved_tests(client)
        await _deploy_run(client, project_id)
        snapshot, _ = await _risk_row(client, project_id)
        vite = _by_package(snapshot, "vite")

        answer = await client.post(
            f"/projects/{project_id}/deployment/updates/{vite}/decision",
            json={"decision": "rejected", "by": "you"},
        )

        assert answer.status_code == 409 and "saying why" in answer.json()["error"]

    async def test_an_update_the_report_does_not_hold_is_not_found(self, client) -> None:
        project_id = await _approved_tests(client)
        await _deploy_run(client, project_id)

        answer = await client.post(
            f"/projects/{project_id}/deployment/updates/u-000000000000/decision",
            json={"decision": "deferred", "by": "you"},
        )

        assert answer.status_code == 404


class TestTheLedger:
    async def test_every_attempt_is_listed_with_its_steps_and_cause(self, client) -> None:
        project_id = await _approved_tests(client)
        async with client.app.state.pool.connection() as conn:
            row, _ = await store.create_deployment(
                conn,
                project_id=project_id,
                deploy_version=1,
                kind="release",
                target="local",
                plan_id="plan",
                candidate_hash="c" * 64,
                idempotency_key=f"{project_id}-ledger",
                authorised={"kind": "gate", "by": "you", "gateId": "g-1"},
                requested_by="you",
            )
            await store.ensure_step(
                conn,
                row["id"],
                seq=0,
                step_id="start",
                provider="local-docker",
                idempotency_key=f"{project_id}-ledger-start",
                moves_traffic=False,
            )
            await store.update_step(
                conn, row["id"], 0, state="failed", started=True, error="no image"
            )
            await store.finish_deployment(
                conn, row["id"], state="compensated", cause="start failed: no image"
            )

        answer = await client.get(f"/projects/{project_id}/deployment/ledger")

        assert answer.status_code == 200
        [attempt] = answer.json()
        assert (attempt["state"], attempt["cause"]) == ("compensated", "start failed: no image")
        assert [(s["stepId"], s["state"]) for s in attempt["steps"]] == [("start", "failed")]


class TestStagingAgainWhileTheReviewWaits:
    """A candidate that did not verify could only be fixed by requesting changes,
    which opens a new deploy version and runs every stage again, the changelog's
    model calls included. Staging alone runs again, at the same version."""

    async def test_a_retry_verifies_the_candidate_and_clears_the_guard(self, client) -> None:
        project_id = await _approved_tests(client)
        client.app.state.c4.verified = False
        await _deploy_run(client, project_id)
        before = DeploySnapshot.model_validate(
            (await client.get(f"/projects/{project_id}/deployment")).json()
        )
        assert before.candidate is not None and before.candidate.verified is False
        assert any(blocker.code == "G3" for blocker in before.blocking)

        client.app.state.c4.verified = True
        client.app.state.c4.calls.clear()
        retried = await client.post(
            f"/projects/{project_id}/deployment/stages/staging-verification/retry"
        )
        assert retried.status_code == 200, retried.text
        runs = (await client.get("/runs", params={"project": project_id})).json()
        await _advance(client, runs[0]["id"])

        after = DeploySnapshot.model_validate(
            (await client.get(f"/projects/{project_id}/deployment")).json()
        )
        assert after.deploy_version == before.deploy_version
        assert after.candidate is not None and after.candidate.verified is True
        assert not any(blocker.code == "G3" for blocker in after.blocking)
        assert client.app.state.c4.calls == ["staging-verification"]


class TestReleasingAgainWhenNothingMoved:
    """A release that failed before any traffic moved was undone, and the only way
    on was a new analysis and a new review of a version already approved. Nothing
    reached production, so releasing the same approved version again is safe."""

    async def _undone(self, client) -> tuple[str, str]:
        project_id = await _approved_tests(client)
        run_id = await _deploy_run(client, project_id)
        await _decide_every_update(client, project_id)
        approved = await client.post(
            f"/projects/{project_id}/deployment/decision", json={"kind": "approved", "by": "you"}
        )
        assert approved.status_code == 200, approved.text
        await _advance(client, run_id)
        async with client.app.state.pool.connection() as conn:
            release = (await store.list_deployments(conn, project_id))[0]
            await store.finish_deployment(
                conn,
                release["id"],
                state="compensated",
                cause="boot failed: the container exited. Undone before any traffic moved",
            )
        return project_id, str(release["id"])

    async def test_the_same_approved_version_is_released_again(self, client) -> None:
        project_id, release_id = await self._undone(client)

        answer = await client.post(
            f"/projects/{project_id}/deployment/deployments/{release_id}/retry"
        )

        assert answer.status_code == 200, answer.text
        snapshot = DeploySnapshot.model_validate(answer.json())
        newest, undone = snapshot.deployments[0], snapshot.deployments[1]
        assert str(undone.id) == release_id
        assert newest.kind == "release" and newest.state == "pending"
        assert newest.deploy_version == undone.deploy_version
        assert newest.candidate_hash == undone.candidate_hash
        # Queued, which is all it is yet: recorded as "Released again", it read as
        # Succeeded in Activity while it waited (review item X-7).
        entries = (await client.get("/activity", params={"project": project_id})).json()
        titles = [entry["title"] for entry in entries]
        assert "Queued the release again" in titles and "Released again" not in titles

    async def test_asking_twice_releases_once(self, client) -> None:
        """Even once the first answer has finished: while it is pending the
        one-active-deployment rule refuses a second anyway, so the key is what
        holds after that."""
        project_id, release_id = await self._undone(client)
        path = f"/projects/{project_id}/deployment/deployments/{release_id}/retry"
        await client.post(path)
        async with client.app.state.pool.connection() as conn:
            again = (await store.list_deployments(conn, project_id))[0]
            await store.finish_deployment(conn, again["id"], state="compensated", cause="again")

        await client.post(path)

        async with client.app.state.pool.connection() as conn:
            assert len(await store.list_deployments(conn, project_id)) == 2

    async def test_newer_code_waiting_for_its_tests_does_not_stop_it(self, client) -> None:
        """The undone release is of the tested code, which is still what may ship."""
        project_id, release_id = await self._undone(client)
        await _newer_code(client, project_id, tested=False)

        answer = await client.post(
            f"/projects/{project_id}/deployment/deployments/{release_id}/retry"
        )

        assert answer.status_code == 200, answer.text

    async def test_a_release_that_moved_traffic_is_not_released_again(self, client) -> None:
        """After traffic moved, undoing is a rollback, which a person decides."""
        project_id, release_id = await self._undone(client)
        async with client.app.state.pool.connection() as conn:
            await store.finish_deployment(
                conn, uuid.UUID(release_id), state="awaiting-rollback-approval"
            )

        answer = await client.post(
            f"/projects/{project_id}/deployment/deployments/{release_id}/retry"
        )

        assert answer.status_code == 409
        assert "before any traffic moved" in answer.json()["error"]
