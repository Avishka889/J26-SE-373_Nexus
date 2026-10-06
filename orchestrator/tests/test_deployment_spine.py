"""The deployment phase, driven end to end against a real database.

The claims these hold to account: a deployment run starts only from a test
version the test review approved, walks its seven stages on its own version
axis, pauses at a gate of its own kind, and leaves the earlier phases untouched.
The component is canned, because none of that is more true for having fetched
release notes or built a container; what the component produces is proved where
the component lives.

One claim is this phase's alone. A release and its monitoring are carried out by
the orchestrator after the gate and outlive any run, so a run that fails must
not reset them. The runner resets every generating stage a failed run owns, and
the release stage is deliberately not one of them.
"""

from collections.abc import AsyncIterator

import httpx
import pytest
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.main import create_app, lifespan_for_tests
from sdlc_contracts import DEPLOY_GENERATING_STAGE_IDS

from .conftest import needs_db
from .test_testing_spine import _advance, _approve_test_review, _generated_code, _start_testing_run

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


async def _tested(client: httpx.AsyncClient, *, approve: bool = True) -> tuple[str, int, int]:
    """A project whose code has been tested, and the test review answered."""
    project_id, code_version = await _generated_code(client)
    run, test_version = await _start_testing_run(client, project_id, code_version)
    await _advance(client, run["id"])
    if approve:
        await _approve_test_review(client, project_id)
    return project_id, code_version, test_version


async def _start_deploy_run(client: httpx.AsyncClient, project_id: str, test_version: int):
    """What the deployment route will do, in one place, so this file tests the graph."""
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        deploy_version = await store.next_deploy_version(conn, project_id)
        await store.seed_deploy_stages(conn, project_id)
        await store.set_stages(
            conn, project_id, list(DEPLOY_GENERATING_STAGE_IDS), status="generating"
        )
        run = await store.create_run(
            conn,
            project_id=project_id,
            requirements_version=deploy_version,
            component="c4",
            source_version=test_version,
        )
    return run, deploy_version


async def _stages(client: httpx.AsyncClient, project_id: str) -> dict[str, dict]:
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        rows = await store.stage_states(conn, project_id)
    return {row["stage_id"]: row for row in rows}


async def _gate(client: httpx.AsyncClient, project_id: str):
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        return await store.pending_gate(conn, project_id=project_id, kind="c4-deploy-review")


async def _answer(client, gate, resume: dict) -> None:
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        await store.resolve_gate(
            conn,
            gate["id"],
            decision=resume["kind"],
            by="you",
            note=resume.get("note"),
        )
        if "version" in resume:
            await store.set_run_version(conn, gate["run_id"], resume["version"])
        await store.set_run_state(conn, gate["run_id"], "queued", resume_payload=resume)
    await _advance(client, gate["run_id"])


class TestAWholeDeploymentRun:
    async def test_it_walks_every_stage_and_stops_at_its_own_gate(self, client) -> None:
        project_id, code_version, test_version = await _tested(client)
        run, deploy_version = await _start_deploy_run(client, project_id, test_version)

        await _advance(client, run["id"])

        stages = await _stages(client, project_id)
        for stage in DEPLOY_GENERATING_STAGE_IDS:
            assert stages[stage]["status"] == "complete", (stage, stages[stage]["error"])
        assert stages["deployment-review"]["status"] == "complete"
        # The runner's stages are untouched by a run: nothing has been released.
        assert stages["release"]["status"] == "pending"
        assert stages["monitoring"]["status"] == "pending"

        gate = await _gate(client, project_id)
        async with client.app.state.pool.connection() as conn:
            stored = await store.get_run(conn, run["id"])
        assert stored["state"] == "awaiting_gate"
        assert gate is not None and gate["requirements_version"] == deploy_version
        assert gate["payload"]["testVersion"] == test_version
        assert gate["payload"]["codeVersion"] == code_version

    async def test_every_stage_was_asked_for_in_order(self, client) -> None:
        project_id, _, test_version = await _tested(client)
        canned = client.app.state.c4
        canned.calls.clear()
        run, _ = await _start_deploy_run(client, project_id, test_version)

        await _advance(client, run["id"])

        assert canned.calls == [
            "dependency-updates",
            "changelog-analysis",
            "impact-analysis",
            "risk-assessment",
            "pipeline-generation",
            "staging-verification",
            "rollback-planning",
        ]

    async def test_the_artefacts_land_on_the_deploy_axis(self, client) -> None:
        project_id, _, test_version = await _tested(client)
        run, deploy_version = await _start_deploy_run(client, project_id, test_version)

        await _advance(client, run["id"])

        async with client.app.state.pool.connection() as conn:
            at = await store.artefacts_at(
                conn,
                project_id,
                version=deploy_version,
                kinds=(
                    "dependency-updates",
                    "changelog-report",
                    "impact-report",
                    "risk-report",
                    "pipeline-config",
                    "deploy-plan",
                    "release-candidate",
                    "rollback-plan",
                ),
            )
            notes = await store.deploy_files(
                conn, project_id, version=deploy_version, stage_id="dependency-updates"
            )
            layer = await store.deploy_files(
                conn, project_id, version=deploy_version, stage_id="pipeline-generation"
            )
            tests = await store.artefacts_at(
                conn, project_id, version=test_version, kinds=("test-report",)
            )
        assert len(at) == 8
        assert at["deploy-plan"]["body"]["projectId"] == project_id
        assert list(notes) == ["notes/express/5.0.0.md"]
        assert set(layer) == {"Dockerfile", "vercel.json"}
        assert "test-report" in tests, "the testing axis is untouched"


class TestTheGate:
    async def test_approval_ends_the_run(self, client) -> None:
        project_id, _, test_version = await _tested(client)
        run, _ = await _start_deploy_run(client, project_id, test_version)
        await _advance(client, run["id"])

        await _answer(client, await _gate(client, project_id), {"kind": "approved"})

        async with client.app.state.pool.connection() as conn:
            stored = await store.get_run(conn, run["id"])
        assert stored["state"] == "done"

    async def test_an_approved_review_hands_one_release_to_the_saga(self, client) -> None:
        project_id, _, test_version = await _tested(client)
        run, version = await _start_deploy_run(client, project_id, test_version)
        await _advance(client, run["id"])
        snapshot = (await client.get(f"/projects/{project_id}/deployment")).json()
        for view in snapshot["decisions"]:
            if view["needsDecision"]:
                await client.post(
                    f"/projects/{project_id}/deployment/updates/{view['updateId']}/decision",
                    json={"decision": "approved", "by": "you", "note": "reviewed"},
                )
        gate = await _gate(client, project_id)
        approved = await client.post(
            f"/projects/{project_id}/deployment/decision", json={"kind": "approved", "by": "you"}
        )
        assert approved.status_code == 200, approved.text
        await _advance(client, run["id"])
        await _advance(client, run["id"])  # a second delivery writes nothing more

        async with client.app.state.pool.connection() as conn:
            [release] = await store.list_deployments(conn, project_id)
            thread = await store.thread(conn, project_id)
        assert (release["kind"], release["target"], release["state"]) == (
            "release",
            "local",
            "pending",
        )
        assert release["deploy_version"] == version
        assert release["authorised"] == {
            "kind": "gate",
            "by": "Local development",
            "gateId": str(gate["id"]),
            "goAhead": False,
            "testVersion": test_version,
        }
        assert any("Releasing deploy version" in row["content"] for row in thread)

    async def test_an_approval_the_guards_refuse_starts_nothing_and_says_why(self, client) -> None:
        """Answered straight at the store, past the route's own guard check, as a
        resumed run would be: the handover asks the guards again."""
        project_id, _, test_version = await _tested(client)
        run, _ = await _start_deploy_run(client, project_id, test_version)
        await _advance(client, run["id"])

        await _answer(client, await _gate(client, project_id), {"kind": "approved"})

        async with client.app.state.pool.connection() as conn:
            deployments = await store.list_deployments(conn, project_id)
            thread = await store.thread(conn, project_id)
        assert deployments == []
        assert any(
            row["content"].startswith("The release was not started:")
            and "needs a person's approval" in row["content"]
            for row in thread
        )

    async def test_changes_regenerate_at_a_new_deploy_version(self, client) -> None:
        project_id, _, test_version = await _tested(client)
        run, first = await _start_deploy_run(client, project_id, test_version)
        await _advance(client, run["id"])
        async with client.app.state.pool.connection() as conn:
            second = await store.next_deploy_version(conn, project_id)

        await _answer(
            client,
            await _gate(client, project_id),
            {"kind": "changes", "note": "leave vite out", "version": second},
        )

        gate = await _gate(client, project_id)
        assert second == first + 1
        assert gate is not None and gate["requirements_version"] == second
        async with client.app.state.pool.connection() as conn:
            at = await store.artefacts_at(conn, project_id, version=second, kinds=("risk-report",))
        assert "risk-report" in at


class TestTheActivityLog:
    async def test_each_phase_files_its_gate_under_its_own_name(self, client) -> None:
        # Every gate was recorded without a category, so the store's default
        # filed Code's, Testing's and Deployment's under design.
        project_id, _, test_version = await _tested(client)
        run, _ = await _start_deploy_run(client, project_id, test_version)
        await _advance(client, run["id"])
        async with client.app.state.pool.connection() as conn:
            rows = await store.audit_trail(conn, project_id=project_id)
        filed = {
            row["action"]: row["category"]
            for row in rows
            if row["action"].startswith("Reached the")
        }
        assert filed == {
            "Reached the Design Review gate": "design",
            "Reached the Code Review gate": "code",
            "Reached the Test Review gate": "testing",
            "Reached the Deployment Review gate": "deployment",
        }
        assert not [row for row in rows if "The design was approved" in (row["detail"] or "")]


class TestLeavingAnUpdateOut:
    """G3 tells a person who left an update out to request changes and rebuild without it.
    The rebuild read no decision, so its candidate carried the update again and G3 refused
    it again, for good."""

    async def test_changes_rebuild_the_candidate_without_it(self, client) -> None:
        project_id, _, test_version = await _tested(client)
        run, first = await _start_deploy_run(client, project_id, test_version)
        await _advance(client, run["id"])
        async with client.app.state.pool.connection() as conn:
            risk = await store.artefacts_at(conn, project_id, version=first, kinds=("risk-report",))
        zod = next(
            a["updateId"]
            for a in risk["risk-report"]["body"]["assessments"]
            if a["package"] == "zod"
        )
        left_out = await client.post(
            f"/projects/{project_id}/deployment/updates/{zod}/decision",
            json={"decision": "rejected", "by": "you", "note": "zod waits for its own release"},
        )
        assert left_out.status_code == 200, left_out.text
        async with client.app.state.pool.connection() as conn:
            second = await store.next_deploy_version(conn, project_id)

        await _answer(
            client,
            await _gate(client, project_id),
            {"kind": "changes", "note": "rebuild without zod", "version": second},
        )

        async with client.app.state.pool.connection() as conn:
            at = await store.artefacts_at(
                conn, project_id, version=second, kinds=("release-candidate",)
            )
        candidate = at["release-candidate"]["body"]
        assert zod not in candidate["included"]
        [why] = [one for one in candidate["excluded"] if one["updateId"] == zod]
        assert why["reason"] == "rejected" and "zod waits for its own release" in why["detail"]
        snapshot = (await client.get(f"/projects/{project_id}/deployment")).json()
        assert not [b for b in snapshot["blocking"] if b["code"] == "G3"]


class TestWhatAFailureCosts:
    async def test_a_leaf_failure_does_not_fail_the_run(self, client) -> None:
        """The notes could not be read: that signal abstains, and a reader can
        still decide on the other two."""
        project_id, _, test_version = await _tested(client)
        client.app.state.c4.fails.add("changelog-analysis")
        run, _ = await _start_deploy_run(client, project_id, test_version)

        await _advance(client, run["id"])

        stages = await _stages(client, project_id)
        assert stages["changelog-analysis"]["status"] == "failed"
        assert stages["risk-assessment"]["status"] == "complete"
        assert await _gate(client, project_id) is not None

    async def test_a_load_bearing_failure_leaves_a_release_in_flight_alone(self, client) -> None:
        """The runner resets the generating stages a failed run owns. A release
        in flight belongs to the saga, not to the run, and must survive it."""
        project_id, _, test_version = await _tested(client)
        client.app.state.c4.fails.add("risk-assessment")
        run, _ = await _start_deploy_run(client, project_id, test_version)
        async with client.app.state.pool.connection() as conn:
            await store.set_stages(conn, project_id, ["release"], status="generating")

        await _advance(client, run["id"])

        stages = await _stages(client, project_id)
        async with client.app.state.pool.connection() as conn:
            stored = await store.get_run(conn, run["id"])
        assert stored["state"] == "failed"
        assert stages["risk-assessment"]["status"] == "failed"
        assert stages["pipeline-generation"]["status"] != "generating"
        assert stages["release"]["status"] == "generating", "a failed run reset a release"

    async def test_a_run_from_an_unapproved_test_version_goes_nowhere(self, client) -> None:
        project_id, _, test_version = await _tested(client, approve=False)
        # The testing run is still waiting at its own gate; answer it with
        # changes so the test version stays unapproved and the phase is free.
        async with client.app.state.pool.connection() as conn:
            gate = await store.pending_gate(conn, project_id=project_id, kind="c3-test-review")
            await store.resolve_gate(conn, gate["id"], decision="changes", by="you", note="no")
        run, _ = await _start_deploy_run(client, project_id, test_version)

        await _advance(client, run["id"])

        stages = await _stages(client, project_id)
        assert stages["dependency-updates"]["status"] == "failed"
        assert "has not been approved" in stages["dependency-updates"]["error"]
        assert client.app.state.c4.calls == [], "nothing was analysed"


async def test_a_deployment_run_cannot_be_started_through_the_design_route(client) -> None:
    """`POST /runs` opens a design version and marks the design stages as
    generating; a deployment started there would skip the approval check."""
    created = await client.post("/projects", json={"name": "Runs", "description": ""})
    project_id = created.json()["id"]
    client.created_projects.append(project_id)
    # With requirement text, a design run would start here, so the refusal is
    # the only thing standing between this request and a run on the wrong axis.
    await client.patch(f"/projects/{project_id}", json={"requirementText": "Someone keeps a list."})
    runs_before = (await client.get("/runs", params={"project": project_id})).json()
    async with client.app.state.pool.connection() as conn:
        for run in runs_before:
            await store.set_run_state(conn, run["id"], "done")

    answer = await client.post("/runs", json={"projectId": project_id, "component": "c4"})

    assert answer.status_code == 409
    assert "start from their own phase's route" in answer.text
    runs_after = (await client.get("/runs", params={"project": project_id})).json()
    assert not [run for run in runs_after if run["component"] == "c4"]
    assert len(runs_after) == len(runs_before)


async def _overlay(client, project_id: str, kind: str, target_id: str, value) -> None:
    """A choice written as its route writes it."""
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        await store.put_overlay(
            conn,
            project_id=project_id,
            version=await store.current_deploy_version(conn, project_id),
            kind=kind,  # type: ignore[arg-type]
            target_id=target_id,
            value=value,
            by="you",
        )


async def _verified_release_before(client, project_id: str) -> None:
    """A release that went out and was verified, so this is not the project's first."""
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        row, _ = await store.create_deployment(
            conn,
            project_id=project_id,
            deploy_version=1,
            kind="release",
            target="local",
            plan_id="an-earlier-plan",
            candidate_hash="b" * 64,
            idempotency_key=f"{project_id}-earlier",
            authorised={"kind": "gate", "by": "you", "gateId": "g-0"},
            requested_by="you",
        )
        await store.finish_deployment(
            conn,
            row["id"],
            state="succeeded",
            verified=True,
            fingerprint={"candidateHash": "b" * 64, "imageDigest": "sha256:" + "d" * 64},
        )


async def _thread(client, project_id: str) -> list[str]:
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        return [row["content"] for row in await store.thread(conn, project_id)]


async def _releases(client, project_id: str) -> list[dict]:
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        rows = await store.list_deployments(conn, project_id, limit=50)
    return [row for row in rows if row["plan_id"] != "an-earlier-plan"]


class TestTheRoute:
    """After the stages: the review, a release under the policy, or no further (FR17)."""

    async def test_a_low_update_under_the_policy_ships_without_a_review(self, client) -> None:
        project_id, _, test_version = await _tested(client)
        await _verified_release_before(client, project_id)
        await _overlay(client, project_id, "release_policy", "policy", {"autoDeployLow": True})
        await _overlay(
            client,
            project_id,
            "update_scope",
            "scope",
            {"target": "generated", "packages": ["vite"]},
        )
        run, version = await _start_deploy_run(client, project_id, test_version)

        await _advance(client, run["id"])

        assert await _gate(client, project_id) is None
        [release] = await _releases(client, project_id)
        assert (release["deploy_version"], release["state"]) == (version, "pending")
        assert release["authorised"]["kind"] == "policy"
        assert release["authorised"]["policy"] == "autoDeployLow"
        assert any("automatically under the policy" in m for m in await _thread(client, project_id))

    async def test_a_first_release_is_reviewed_whatever_the_policy(self, client) -> None:
        project_id, _, test_version = await _tested(client)
        await _overlay(client, project_id, "release_policy", "policy", {"autoDeployLow": True})
        await _overlay(
            client,
            project_id,
            "update_scope",
            "scope",
            {"target": "generated", "packages": ["vite"]},
        )
        run, _ = await _start_deploy_run(client, project_id, test_version)

        await _advance(client, run["id"])

        assert await _gate(client, project_id) is not None
        assert await _releases(client, project_id) == []
        assert "Held for review: a project's first release is always reviewed." in await _thread(
            client, project_id
        )

    async def test_a_medium_update_is_held_for_a_person(self, client) -> None:
        project_id, _, test_version = await _tested(client)
        await _verified_release_before(client, project_id)
        await _overlay(client, project_id, "release_policy", "policy", {"autoDeployLow": True})
        run, _ = await _start_deploy_run(client, project_id, test_version)

        await _advance(client, run["id"])

        assert await _gate(client, project_id) is not None
        assert any(
            m.startswith("Held for review:") and "above Low" in m
            for m in await _thread(client, project_id)
        )

    async def test_a_stack_no_template_fits_is_analysis_only(self, client) -> None:
        project_id, _, test_version = await _tested(client)
        await _overlay(client, project_id, "stack_selection", "stack", "react-spring-postgres")
        run, _ = await _start_deploy_run(client, project_id, test_version)

        await _advance(client, run["id"])

        assert await _gate(client, project_id) is None
        assert await _releases(client, project_id) == []
        async with client.app.state.pool.connection() as conn:
            assert (await store.get_run(conn, run["id"]))["state"] == "done"
        assert any(
            m.startswith("Analysis only: validated templates exist for mern only")
            for m in await _thread(client, project_id)
        )
