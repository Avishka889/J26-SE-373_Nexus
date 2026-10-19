"""The saga: every step recorded, undone only before traffic moves, and never done twice.

A fake adapter carries out a real deploy plan (start, check, switch, verify,
where the switch moves traffic) against the real deployment tables, failing
wherever a test says. What is checked is what FR16 and FR20 ask of it: every
attempt is on record with its cause; a failure before traffic moves undoes what
was created, newest first; a failure after it undoes nothing and waits for a
person; asking again creates nothing; and a deployment nobody authorised
touches nothing.
"""

from datetime import UTC, datetime

import pytest
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.saga.executor import StepFailed, StepResult, deployment_key, run_deployment
from orchestrator.saga.runner import authorise_release
from sdlc_contracts import (
    DeployPlan,
    DeployStep,
    DeployTarget,
    EnvironmentProtection,
    RollbackPolicy,
)

from .conftest import needs_db

pytestmark = needs_db

NOW = datetime(2026, 9, 28, tzinfo=UTC)
CANDIDATE = "c" * 64


@pytest.fixture
async def pool(settings: Settings):
    from orchestrator.db.pool import create_app_pool

    pool = create_app_pool(settings.database_url, max_size=2)
    await pool.open(wait=True)
    try:
        yield pool
    finally:
        await pool.close()


@pytest.fixture
async def project(pool):
    async with pool.connection() as conn:
        row = await store.create_project(conn, name="Saga case", owner_id=DEV_OWNER_ID)
    try:
        yield row["id"]
    finally:
        async with pool.connection() as conn:
            await store.delete_project(conn, row["id"], owner_id=DEV_OWNER_ID)


PLAN_STEPS = [
    DeployStep(id="start", label="Start", provider="local-docker", compensation="stop it"),
    DeployStep(id="check", label="Check", depends_on="start"),
    DeployStep(
        id="switch",
        label="Switch",
        provider="local-docker",
        depends_on="check",
        compensation="restore the verified release, once a person approves",
        moves_traffic=True,
    ),
    DeployStep(id="verify", label="Verify", depends_on="switch"),
]


def _plan(project_id: str) -> DeployPlan:
    return DeployPlan(
        plan_id=f"{project_id}-deploy-v1",
        project_id=project_id,
        generated_by="test",
        generated_at=NOW,
        deploy_version=1,
        stack="mern",
        target="local",
        candidate_hash=CANDIDATE,
        targets=[DeployTarget(role="app", provider="local-docker", resource="the image")],
        steps=PLAN_STEPS,
        rollback=RollbackPolicy(note="application only"),
        environment_protection=EnvironmentProtection(github="not-applicable"),
    )


class Fake:
    """Carries out every step, records every call, and fails where it is told to."""

    def __init__(
        self,
        *,
        fail_at: str | None = None,
        existing: dict | None = None,
        moved: bool | None = None,
    ) -> None:
        self.fail_at = fail_at
        self.existing = existing or {}
        #: What the failing step says about traffic, as a provider's report would.
        self.moved = moved
        self.calls: list[tuple[str, str]] = []

    async def execute(self, ctx):
        self.calls.append(("execute", ctx.step.id))
        if ctx.step.id == self.fail_at:
            raise StepFailed(
                f"{ctx.step.id} was made to fail", log="the injected fault", moved=self.moved
            )
        resource = {"id": f"{ctx.step.id}-resource"}
        if ctx.step.id == "verify":
            resource |= {"verified": True, "fingerprint": {"candidateHash": CANDIDATE}}
        return StepResult(resource=resource, log=f"{ctx.step.id} done")

    async def compensate(self, ctx):
        self.calls.append(("compensate", ctx.step.id))

    async def find_existing(self, ctx):
        self.calls.append(("find", ctx.step.id))
        return self.existing.get(ctx.step.id)


async def _deployment(pool, project_id: str, *, authorised=None, key: str = "k-1"):
    async with pool.connection() as conn:
        await store.put_artefact(
            conn,
            project_id=project_id,
            kind="deploy-plan",
            version=1,
            body=_plan(project_id).model_dump(by_alias=True, mode="json"),
        )
        row, _ = await store.create_deployment(
            conn,
            project_id=project_id,
            deploy_version=1,
            kind="release",
            target="local",
            plan_id=f"{project_id}-deploy-v1",
            candidate_hash=CANDIDATE,
            idempotency_key=key,
            authorised={"kind": "gate", "by": "you", "gateId": "g-1"}
            if authorised is None
            else authorised,
            requested_by="you",
        )
    return row["id"]


async def _allowed(conn, row):
    return []


async def _run(pool, deployment_id, fake: Fake, authorise=_allowed):
    return await run_deployment(
        pool, deployment_id, adapters={"local-docker": fake, "checks": fake}, authorise=authorise
    )


async def _record(pool, deployment_id):
    async with pool.connection() as conn:
        row = await store.get_deployment(conn, deployment_id)
        steps = await store.deployment_steps(conn, deployment_id)
    return row, {step["step_id"]: step["state"] for step in steps}


async def _said(pool, project_id: str) -> list[tuple[str, str]]:
    """The deployment phase's audit entries, oldest first: (action, detail)."""
    async with pool.connection() as conn:
        rows = await store.audit_trail(conn, owner_id=DEV_OWNER_ID, project_id=project_id, limit=50)
    return [
        (row["action"], row["detail"]) for row in reversed(rows) if row["category"] == "deployment"
    ]


class TestEachEndIsRecorded:
    """Activity never said whether a release went live, failed, was undone or
    rolled back: no end state wrote an audit entry (review item X-7)."""

    async def test_a_verified_release_says_it_went_live(self, pool, project) -> None:
        deployment = await _deployment(pool, project)

        assert await _run(pool, deployment, Fake()) == "succeeded"

        [(action, _)] = await _said(pool, project)
        assert action == "Released deploy version 1"

    async def test_one_undone_before_traffic_moved_says_so_and_why(self, pool, project) -> None:
        deployment = await _deployment(pool, project)

        assert await _run(pool, deployment, Fake(fail_at="check")) == "compensated"

        [(action, detail)] = await _said(pool, project)
        assert action == "Release undone before traffic moved"
        assert "check failed: check was made to fail" in detail

    async def test_one_that_failed_after_traffic_moved_says_a_person_decides(
        self, pool, project
    ) -> None:
        deployment = await _deployment(pool, project)

        assert await _run(pool, deployment, Fake(fail_at="verify")) == "awaiting-rollback-approval"

        [(action, detail)] = await _said(pool, project)
        assert action == "Release failed after traffic moved"
        assert "a person must approve" in detail

    async def test_one_the_guards_refused_says_why(self, pool, project) -> None:
        deployment = await _deployment(pool, project, authorised={})

        assert await _run(pool, deployment, Fake(), authorise=authorise_release) == "failed"

        [(action, detail)] = await _said(pool, project)
        assert action == "Release failed"
        assert "no authorisation to act on" in detail


class TestARelease:
    async def test_every_step_runs_once_and_the_release_is_verified(self, pool, project) -> None:
        deployment = await _deployment(pool, project)
        fake = Fake()
        assert await _run(pool, deployment, fake) == "succeeded"
        row, steps = await _record(pool, deployment)
        assert steps == {step.id: "succeeded" for step in PLAN_STEPS}
        assert row["verified"] and row["fingerprint"] == {"candidateHash": CANDIDATE}
        assert [call for call in fake.calls if call[0] == "execute"] == [
            ("execute", step.id) for step in PLAN_STEPS
        ]


class TestCompensation:
    @pytest.mark.parametrize(
        ("fail_at", "undone"),
        [("start", []), ("check", ["start"])],
    )
    async def test_a_fault_before_traffic_moves_undoes_what_was_created_newest_first(
        self, pool, project, fail_at, undone
    ) -> None:
        deployment = await _deployment(pool, project)
        fake = Fake(fail_at=fail_at)
        assert await _run(pool, deployment, fake) == "compensated"
        row, steps = await _record(pool, deployment)
        assert [step for kind, step in fake.calls if kind == "compensate"] == undone
        assert steps[fail_at] == "failed"
        assert all(steps[step] == "compensated" for step in undone)
        assert row["cause"].startswith(f"{fail_at} failed: {fail_at} was made to fail")

    @pytest.mark.parametrize("fail_at", ["switch", "verify"])
    async def test_a_fault_once_traffic_moves_undoes_nothing_and_waits_for_a_person(
        self, pool, project, fail_at
    ) -> None:
        deployment = await _deployment(pool, project)
        fake = Fake(fail_at=fail_at)
        assert await _run(pool, deployment, fake) == "awaiting-rollback-approval"
        row, steps = await _record(pool, deployment)
        assert not [call for call in fake.calls if call[0] == "compensate"]
        assert steps[fail_at] == "failed" and "a person must approve" in row["cause"]


class TestATrafficStepThatMovedNone:
    """A traffic step can fail before anything goes live, as a build that fails
    does while the previous release keeps serving. Said so by the step, the
    failure is undone like any other; unsaid, it is left for a person."""

    async def test_it_is_undone_like_a_step_before_traffic(self, pool, project) -> None:
        deployment = await _deployment(pool, project)
        fake = Fake(fail_at="switch", moved=False)
        assert await _run(pool, deployment, fake) == "compensated"
        row, steps = await _record(pool, deployment)
        assert steps["switch"] == "failed" and steps["start"] == "compensated"
        assert "Undone before any traffic moved" in row["cause"]

    async def test_it_cannot_undo_traffic_an_earlier_step_moved(self, pool, project) -> None:
        deployment = await _deployment(pool, project)
        fake = Fake(fail_at="verify", moved=False)
        assert await _run(pool, deployment, fake) == "awaiting-rollback-approval"
        assert not [call for call in fake.calls if call[0] == "compensate"]


class TestIdempotency:
    async def test_asking_for_the_same_release_twice_finds_the_first(self, pool, project) -> None:
        await _deployment(pool, project, key="same")
        async with pool.connection() as conn:
            row, created = await store.create_deployment(
                conn,
                project_id=project,
                deploy_version=1,
                kind="release",
                target="local",
                plan_id="p",
                candidate_hash=CANDIDATE,
                idempotency_key="same",
                authorised={"kind": "gate", "by": "you", "gateId": "g-1"},
                requested_by="you",
            )
        assert not created and row["plan_id"] == f"{project}-deploy-v1"
        assert deployment_key("p", "plan", "release", "gate:1") == deployment_key(
            "p", "plan", "release", "gate:1"
        )

    async def test_a_second_deployment_waits_for_the_first(self, pool, project) -> None:
        await _deployment(pool, project, key="first")
        with pytest.raises(store.DeploymentInFlight):
            await _deployment(pool, project, key="second")

    async def test_a_finished_deployment_is_not_run_again(self, pool, project) -> None:
        deployment = await _deployment(pool, project)
        fake = Fake()
        await _run(pool, deployment, fake)
        before = list(fake.calls)
        assert await _run(pool, deployment, fake) is None
        assert fake.calls == before

    async def test_a_step_a_crash_left_running_is_adopted_not_done_again(
        self, pool, project
    ) -> None:
        deployment = await _deployment(pool, project)
        async with pool.connection() as conn:
            await store.claim_deployment(conn, deployment)
            await store.ensure_step(
                conn,
                deployment,
                seq=0,
                step_id="start",
                provider="local-docker",
                idempotency_key="crashed",
                moves_traffic=False,
            )
            await store.update_step(conn, deployment, 0, state="running", started=True)
            await conn.execute(
                "UPDATE app.deployments SET heartbeat_at = now() - interval '1 hour' WHERE id = %s",
                (deployment,),
            )
        fake = Fake(existing={"start": {"id": "the container an earlier attempt started"}})
        assert await _run(pool, deployment, fake) == "succeeded"
        assert ("find", "start") in fake.calls and ("execute", "start") not in fake.calls
        async with pool.connection() as conn:
            [start] = [s for s in await store.deployment_steps(conn, deployment) if s["seq"] == 0]
        assert start["resource"] == {"id": "the container an earlier attempt started"}


class TestAuthorisation:
    async def test_a_deployment_nobody_authorised_touches_nothing(self, pool, project) -> None:
        deployment = await _deployment(pool, project, authorised={})
        fake = Fake()
        assert await _run(pool, deployment, fake, authorise=authorise_release) == "failed"
        row, steps = await _record(pool, deployment)
        assert fake.calls == [] and steps == {}
        assert row["cause"] == (
            "the release guards refuse it now: the deployment records no authorisation to act on"
        )
