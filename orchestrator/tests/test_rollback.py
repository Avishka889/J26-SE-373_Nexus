# ruff: noqa: F811 - `client` is the deployment routes' fixture, imported to be used by name
"""Rollback: only on a person's decision (FR20), and restored only when the fingerprint is back (NFR6).

A verified release R and a failed release F after it are written to the
deployment tables, with the rollback plan F's run prepared, restoring R. The
decision route is shown refusing what it must refuse and writing one rollback
when a person approves; the saga, with a fake adapter, carries that rollback out
and marks F rolled back only when the check says R is served again.
"""

import uuid
from datetime import UTC, datetime

from orchestrator.db import store
from orchestrator.saga.executor import StepFailed, StepResult, run_deployment
from orchestrator.saga.runner import authorise_release
from sdlc_contracts import (
    DeploySnapshot,
    RestoreStep,
    RollbackPlan,
    UpdateRollback,
    VerificationCheck,
    VerifiedRelease,
)

from .conftest import needs_db
from .test_deployment_routes import _approved_tests, client  # noqa: F401

pytestmark = needs_db

NOW = datetime(2026, 9, 28, tzinfo=UTC)
VERIFIED, FAILED = "a" * 64, "b" * 64


async def _release(conn, project_id, version, candidate_hash, *, state, verified=False):
    row, _ = await store.create_deployment(
        conn,
        project_id=project_id,
        deploy_version=version,
        kind="release",
        target="local",
        plan_id=f"{project_id}-deploy-v{version}",
        candidate_hash=candidate_hash,
        idempotency_key=f"{project_id}-release-{version}",
        authorised={"kind": "gate", "by": "you", "gateId": f"g-{version}"},
        requested_by="you",
    )
    await store.finish_deployment(
        conn,
        row["id"],
        state=state,
        verified=verified,
        fingerprint={"candidateHash": candidate_hash, "imageDigest": "sha256:" + "d" * 64},
        cause=None if state == "succeeded" else "verify failed after the switch",
    )
    return row["id"]


def _plan(verified_id, *, restorable=True) -> RollbackPlan:
    if not restorable:
        return RollbackPlan(
            version=2,
            generated_at=NOW,
            candidate_hash=FAILED,
            restorable=False,
            unrestorable_reason="this project has no verified release yet",
            updates=[],
        )
    return RollbackPlan(
        version=2,
        generated_at=NOW,
        candidate_hash=FAILED,
        restore_target=VerifiedRelease(
            deployment_id=str(verified_id),
            deploy_version=1,
            candidate_hash=VERIFIED,
            target="local",
            image_digest="sha256:" + "d" * 64,
            verified_at=NOW,
        ),
        restorable=True,
        steps=[
            RestoreStep(
                id="start-verified", label="Start", provider="local-docker", action="start it"
            ),
            RestoreStep(
                id="switch-back",
                label="Switch back",
                provider="local-docker",
                action="move the port",
                moves_traffic=True,
            ),
        ],
        checks=[VerificationCheck(id="fp", kind="fingerprint", role="app", expect=VERIFIED)],
        updates=[UpdateRollback(update_id="u-000000000001", level="high", status="prepared")],
    )


async def _history(client, *, restorable=True, failed_state="awaiting-rollback-approval"):
    project_id = await _approved_tests(client)
    async with client.app.state.pool.connection() as conn:
        verified = await _release(conn, project_id, 1, VERIFIED, state="succeeded", verified=True)
        failed = await _release(conn, project_id, 2, FAILED, state=failed_state)
        await store.put_artefact(
            conn,
            project_id=project_id,
            kind="rollback-plan",
            version=2,
            body=_plan(verified, restorable=restorable).model_dump(by_alias=True, mode="json"),
        )
    return project_id, verified, failed


def _url(project_id, deployment_id) -> str:
    return f"/projects/{project_id}/deployment/deployments/{deployment_id}/rollback/decision"


async def _rollbacks(client, project_id):
    async with client.app.state.pool.connection() as conn:
        rows = await store.list_deployments(conn, project_id, limit=50)
    return [row for row in rows if row["kind"] == "rollback"]


class TestTheDecision:
    async def test_an_approval_writes_one_rollback_to_the_verified_release(self, client) -> None:
        project_id, verified, failed = await _history(client)
        decision = {"decision": "approved", "by": "you", "note": "the checkout page is down"}
        first = await client.post(_url(project_id, failed), json=decision)
        again = await client.post(_url(project_id, failed), json=decision)
        assert first.status_code == 200 and again.status_code == 200
        [rollback] = await _rollbacks(client, project_id)
        assert rollback["restores"] == verified and rollback["candidate_hash"] == VERIFIED
        assert rollback["state"] == "pending"
        assert rollback["authorised"] == {
            "kind": "rollback",
            "by": "Local development",
            "deploymentId": str(failed),
            "fromVersion": 2,
            "note": "the checkout page is down",
            "attempt": 1,
        }

    async def test_declining_needs_a_note_and_starts_nothing(self, client) -> None:
        project_id, _, failed = await _history(client)
        bare = await client.post(
            _url(project_id, failed), json={"decision": "rejected", "by": "you"}
        )
        assert bare.status_code == 409 and "needs a note" in bare.json()["error"]
        noted = await client.post(
            _url(project_id, failed),
            json={"decision": "rejected", "by": "you", "note": "fixing forward instead"},
        )
        assert noted.status_code == 200 and await _rollbacks(client, project_id) == []

    async def test_a_declined_rollback_no_longer_waits_on_anyone(self, client) -> None:
        # The first live cloud release stopped at a workflow that had succeeded, and
        # declining its rollback left it waiting, so the page asked again for good.
        project_id, _, failed = await _history(client)
        answer = await client.post(
            _url(project_id, failed),
            json={"decision": "rejected", "by": "you", "note": "the workflow succeeded"},
        )
        async with client.app.state.pool.connection() as conn:
            row = await store.get_deployment(conn, failed)
        assert row["state"] == "kept-unverified", "its traffic moved, so it serves"
        assert DeploySnapshot.model_validate(answer.json()).rollback_pending is False

    async def test_a_declined_rollback_leaves_the_release_as_what_serves(self, client) -> None:
        # Declining marked it failed, and failed means its traffic never moved,
        # so the platform took the release before it as the one serving
        # (review item C4-5).
        project_id, verified, failed = await _history(client)
        await client.post(
            _url(project_id, failed),
            json={"decision": "rejected", "by": "you", "note": "fixing forward"},
        )
        async with client.app.state.pool.connection() as conn:
            earlier = await store.get_deployment(conn, verified)
            replaced_by = await store.newer_deployment(conn, earlier)

        assert replaced_by is not None and replaced_by["id"] == failed

    async def test_a_release_kept_unverified_can_still_be_rolled_back(self, client) -> None:
        project_id, verified, failed = await _history(client)
        await client.post(
            _url(project_id, failed),
            json={"decision": "rejected", "by": "you", "note": "fixing forward"},
        )

        later = await client.post(
            _url(project_id, failed),
            json={"decision": "approved", "by": "you", "note": "the forward fix did not hold"},
        )

        assert later.status_code == 200, later.text
        [rollback] = await _rollbacks(client, project_id)
        assert rollback["restores"] == verified

    async def test_a_verified_release_monitoring_flagged_serves_on_when_declined(
        self, client
    ) -> None:
        project_id, _, _ = await _history(client)
        async with client.app.state.pool.connection() as conn:
            flagged = await _release(
                conn, project_id, 3, "e" * 64, state="awaiting-rollback-approval", verified=True
            )
        await client.post(
            _url(project_id, flagged),
            json={"decision": "rejected", "by": "you", "note": "a cold start, not an outage"},
        )
        async with client.app.state.pool.connection() as conn:
            row = await store.get_deployment(conn, flagged)
        assert row["state"] == "succeeded" and row["verified"]

    async def test_nothing_to_roll_back_to_is_refused_with_the_plans_reason(self, client) -> None:
        project_id, _, failed = await _history(client, restorable=False)
        answer = await client.post(
            _url(project_id, failed), json={"decision": "approved", "by": "you"}
        )
        assert answer.status_code == 409
        assert (
            "nothing to roll back to: this project has no verified release yet"
            in (answer.json()["error"])
        )

    async def test_a_release_that_was_compensated_has_nothing_to_roll_back(self, client) -> None:
        project_id, _, failed = await _history(client, failed_state="compensated")
        answer = await client.post(
            _url(project_id, failed), json={"decision": "approved", "by": "you"}
        )
        assert answer.status_code == 409 and "has nothing to roll back" in answer.json()["error"]


class Restorer:
    """Restores in the fake: start and switch succeed; the check serves what it is told."""

    def __init__(self, serves: str) -> None:
        self.serves = serves
        self.calls: list[str] = []

    async def execute(self, ctx):
        self.calls.append(ctx.step.id)
        if ctx.step.id == "verify":
            if self.serves != ctx.previous.candidate_hash:
                raise StepFailed(f"serves candidate {self.serves[:12]}")
            return StepResult(
                resource={"verified": True, "fingerprint": {"candidateHash": self.serves}}
            )
        return StepResult(resource={"container": f"{ctx.step.id}-container"})

    async def compensate(self, ctx):
        self.calls.append(f"undo {ctx.step.id}")

    async def find_existing(self, ctx):
        return None


async def _approved_rollback(client):
    project_id, verified, failed = await _history(client)
    await client.post(
        _url(project_id, failed), json={"decision": "approved", "by": "you", "note": "down"}
    )
    [rollback] = await _rollbacks(client, project_id)
    return project_id, verified, failed, rollback["id"]


class TestTheSaga:
    async def test_a_rollback_that_serves_the_verified_release_again_is_restored(
        self,
        client,
    ) -> None:
        project_id, _, failed, rollback = await _approved_rollback(client)
        fake = Restorer(serves=VERIFIED)
        pool = client.app.state.pool
        state = await run_deployment(
            pool,
            rollback,
            adapters={"local-docker": fake, "checks": fake},
            authorise=authorise_release,
        )
        assert state == "succeeded"
        assert fake.calls == ["start-verified", "switch-back", "verify"]
        async with pool.connection() as conn:
            assert (await store.get_deployment(conn, rollback))["verified"]
            assert (await store.get_deployment(conn, failed))["state"] == "rolled-back"
        # And Activity says so: no end state wrote an entry (review item X-7).
        entries = (await client.get("/activity", params={"project": project_id})).json()
        restored = next(entry for entry in entries if entry["title"].startswith("Restored"))
        assert restored["title"] == "Restored deploy version 1"
        assert restored["category"] == "deployment" and restored["outcome"] == "done"

    async def test_a_rollback_serving_anything_else_is_not_restored_and_waits(
        self,
        client,
    ) -> None:
        _, _, failed, rollback = await _approved_rollback(client)
        fake = Restorer(serves="f" * 64)
        pool = client.app.state.pool
        state = await run_deployment(
            pool,
            rollback,
            adapters={"local-docker": fake, "checks": fake},
            authorise=authorise_release,
        )
        assert state == "awaiting-rollback-approval"
        async with pool.connection() as conn:
            assert (await store.get_deployment(conn, failed))["state"] == (
                "awaiting-rollback-approval"
            )

    async def test_a_rollback_row_without_a_decision_touches_nothing(
        self,
        client,
    ) -> None:
        project_id, verified, _ = await _history(client)
        pool = client.app.state.pool
        async with pool.connection() as conn:
            row, _ = await store.create_deployment(
                conn,
                project_id=project_id,
                deploy_version=1,
                kind="rollback",
                target="local",
                plan_id="p",
                candidate_hash=VERIFIED,
                idempotency_key=str(uuid.uuid4()),
                # Everything but the decision it answers: no release named as the
                # one a person decided to roll back.
                authorised={"kind": "rollback", "by": "you", "fromVersion": 2},
                requested_by="you",
                restores=verified,
            )
        fake = Restorer(serves=VERIFIED)
        state = await run_deployment(
            pool,
            row["id"],
            adapters={"local-docker": fake, "checks": fake},
            authorise=authorise_release,
        )
        assert state == "failed" and fake.calls == []
        async with pool.connection() as conn:
            refused = await store.get_deployment(conn, row["id"])
        assert refused["cause"].endswith("the deployment records no authorisation to act on")


class TestARollbackThatFailedCanBeTriedAgain:
    """A rollback's idempotency key was fixed per release, so approving again
    after one failed found the failed row and started nothing: the release stayed
    down with no way to try again (review item C4-3)."""

    async def test_approving_again_after_one_failed_writes_the_next_attempt(self, client) -> None:
        project_id, _, failed, first = await _approved_rollback(client)
        pool = client.app.state.pool
        wrong = Restorer(serves="f" * 64)
        await run_deployment(
            pool,
            first,
            adapters={"local-docker": wrong, "checks": wrong},
            authorise=authorise_release,
        )

        again = await client.post(
            _url(project_id, failed),
            json={"decision": "approved", "by": "you", "note": "the port is free now"},
        )

        assert again.status_code == 200, again.text
        rollbacks = await _rollbacks(client, project_id)
        assert len(rollbacks) == 2
        second = next(row for row in rollbacks if row["id"] != first)
        assert second["state"] == "pending"
        assert second["authorised"]["attempt"] == 2
        right = Restorer(serves=VERIFIED)
        state = await run_deployment(
            pool,
            second["id"],
            adapters={"local-docker": right, "checks": right},
            authorise=authorise_release,
        )
        assert state == "succeeded"
        async with pool.connection() as conn:
            assert (await store.get_deployment(conn, failed))["state"] == "rolled-back"

    async def test_approving_twice_while_one_is_still_to_run_is_one_rollback(self, client) -> None:
        project_id, _, failed, first = await _approved_rollback(client)

        again = await client.post(
            _url(project_id, failed), json={"decision": "approved", "by": "you", "note": "down"}
        )

        assert again.status_code == 200
        [only] = await _rollbacks(client, project_id)
        assert only["id"] == first and only["authorised"]["attempt"] == 1


class TestARestoreTargetThatWasItselfRolledBack:
    """A rollback plan is fixed at analysis, and the release it restores can be
    rolled back after that. Marked rolled back, it stayed verified, so approving
    the rollback restored a release that had itself been withdrawn (review item
    C4-9)."""

    async def test_the_newest_release_still_standing_is_restored_instead(self, client) -> None:
        project_id, verified, failed = await _history(client)
        async with client.app.state.pool.connection() as conn:
            await store.mark_rolled_back(conn, verified)
            standing = await _release(
                conn, project_id, 3, "c" * 64, state="succeeded", verified=True
            )

        answer = await client.post(
            _url(project_id, failed), json={"decision": "approved", "by": "you", "note": "down"}
        )

        assert answer.status_code == 200, answer.text
        [rollback] = await _rollbacks(client, project_id)
        assert rollback["restores"] == standing
        assert (rollback["candidate_hash"], rollback["deploy_version"]) == ("c" * 64, 3)

    async def test_with_nothing_else_standing_it_is_refused_and_says_so(self, client) -> None:
        project_id, verified, failed = await _history(client)
        async with client.app.state.pool.connection() as conn:
            await store.mark_rolled_back(conn, verified)

        answer = await client.post(
            _url(project_id, failed), json={"decision": "approved", "by": "you", "note": "down"}
        )

        assert answer.status_code == 409
        assert (
            "the release the plan restores, deploy version 1, is rolled-back now, and no "
            "other verified release stands"
        ) in answer.json()["error"]
        assert await _rollbacks(client, project_id) == []

    async def test_the_release_gate_is_told_which_releases_still_stand(self, client) -> None:
        from orchestrator.api.deps import DEV_OWNER_ID
        from orchestrator.deploy import guards

        project_id, verified, _ = await _history(client)
        asked = {"owner": DEV_OWNER_ID, "deploy_version": 2, "target": "local", "test_version": 0}
        async with client.app.state.pool.connection() as conn:
            before = await guards.gather(conn, project_id, **asked)
            await store.mark_rolled_back(conn, verified)
            after = await guards.gather(conn, project_id, **asked)

        assert before.standing == frozenset({str(verified)})
        assert after.standing == frozenset()
