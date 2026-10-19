"""One deployment carried out: the plan's steps in order, each recorded, undone only where it may be.

The plan is C4's `deploy-plan` artefact; this runs it. Every step goes through an
adapter chosen by the step's provider (a step that asks no provider, such as a
check, goes to the target's `checks` adapter), and every attempt is recorded,
whatever came of it (FR16).

**Authorisation is asked again first.** The release guards ran at the gate, but a
deployment can start later than that, so they run again before any work, with
the go ahead the authorisation recorded. A deployment they refuse fails with
their words as its cause and touches nothing.

**Idempotency.** A deployment's key is its project, plan, kind and the
authorisation behind it, so asking twice finds the first deployment. A step's key
is its project, plan, step and deployment, and its row outlives the process: a
step already done is not done again, and a step a crash left running is first
looked for (the adapter's `find_existing`) and adopted if it exists, so a retry
with the same key creates nothing.

**Compensation stops where traffic moved.** A step that fails before any step
has moved production traffic undoes the steps before it, newest first, each by
its plan's compensation; the deployment ends `compensated`. After a step that
moved traffic, or when the failing step is the one moving it, undoing is a
rollback, and FR20 lets only a person start one: the deployment ends
`awaiting-rollback-approval`, with nothing undone automatically. The one
exception is a traffic step that fails saying it moved none (`StepFailed`'s
`moved=False`), such as a build that never went live.
"""

import hashlib
import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from psycopg_pool import AsyncConnectionPool
from sdlc_contracts import (
    Blocker,
    DeployPlan,
    DeployStep,
    ReleaseCandidate,
    RollbackPlan,
    VerifiedRelease,
)

from ..db import store
from ..deploy.notes import release_notes
from ..deploy.records import verified_release

log = logging.getLogger(__name__)


def deployment_key(project_id: str, plan_id: str, kind: str, authorisation: str) -> str:
    """The same release, asked for twice under the same authorisation, is one deployment."""
    return hashlib.sha256(f"{project_id}|{plan_id}|{kind}|{authorisation}".encode()).hexdigest()


def step_key(project_id: str, plan_id: str, step_id: str, deployment_id: uuid.UUID) -> str:
    return hashlib.sha256(f"{project_id}|{plan_id}|{step_id}|{deployment_id}".encode()).hexdigest()


@dataclass(frozen=True)
class Plan:
    """What a deployment carries out: a release's deploy plan, or a rollback's restore."""

    plan_id: str
    steps: list[DeployStep]


@dataclass(frozen=True)
class StepContext:
    deployment: store.Row
    plan: Plan
    step: DeployStep
    seq: int
    key: str
    candidate: ReleaseCandidate | None
    #: The release a rollback returns to, or the one running before a release.
    previous: VerifiedRelease | None
    #: What an earlier attempt of this step recorded, for compensation and adoption.
    resource: dict[str, Any] | None = None
    #: What the steps before this one recorded, by step id.
    earlier: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class StepResult:
    resource: dict[str, Any]
    log: str = ""
    command: str = ""


class StepFailed(Exception):
    """A step that did not do what it is for, with what the provider said.

    `moved=False` is a traffic moving step saying, from what its provider
    reported, that it moved none: a build that failed before anything could go
    live, while the previous release kept serving. Only then is a failing
    traffic step undone like any other; unsaid, the failure may have moved
    traffic, and FR20 leaves it for a person.
    """

    def __init__(self, message: str, *, log: str = "", moved: bool | None = None) -> None:
        super().__init__(message)
        self.log = log
        self.moved = moved


class Adapter(Protocol):
    async def execute(self, ctx: StepContext) -> StepResult: ...

    async def compensate(self, ctx: StepContext) -> None: ...

    async def find_existing(self, ctx: StepContext) -> dict[str, Any] | None: ...


#: What asks the guards again: the connection and the deployment row in, the
#: blockers out.
Authorise = Callable[[Any, store.Row], Awaitable[list[Blocker]]]


def _adapter(adapters: dict[str, Adapter], step: DeployStep) -> Adapter:
    name = step.provider or "checks"
    if name not in adapters:
        raise StepFailed(f"no adapter can carry out a {name} step")
    return adapters[name]


async def run_deployment(
    pool: AsyncConnectionPool,
    deployment_id: uuid.UUID,
    *,
    adapters: dict[str, Adapter],
    authorise: Authorise,
) -> str | None:
    """Claim one deployment and carry it to an end state; the state it ended in."""
    async with pool.connection() as conn:
        row = await store.claim_deployment(conn, deployment_id)
        if row is None:
            return None
        blockers = await authorise(conn, row)
        if blockers:
            await store.finish_deployment(
                conn,
                deployment_id,
                state="failed",
                cause="the release guards refuse it now: "
                + "; ".join(blocker.message for blocker in blockers),
            )
            return "failed"
        loaded = await (_load_rollback if row["kind"] == "rollback" else _load_release)(conn, row)
    if isinstance(loaded, str):
        async with pool.connection() as conn:
            await store.finish_deployment(conn, deployment_id, state="failed", cause=loaded)
        return "failed"
    plan, candidate, previous = loaded

    done: list[tuple[int, DeployStep, dict[str, Any]]] = []
    for seq, step in enumerate(plan.steps):
        key = step_key(row["project_id"], plan.plan_id, step.id, deployment_id)
        async with pool.connection() as conn:
            existing = await store.ensure_step(
                conn,
                deployment_id,
                seq=seq,
                step_id=step.id,
                provider=step.provider,
                idempotency_key=key,
                moves_traffic=step.moves_traffic,
            )
            await store.heartbeat_deployment(conn, deployment_id)
        earlier = {s.id: resource for _, s, resource in done}
        ctx = StepContext(
            deployment=row,
            plan=plan,
            step=step,
            seq=seq,
            key=key,
            candidate=candidate,
            previous=previous,
            resource=existing.get("resource"),
            earlier=earlier,
        )
        if existing["state"] == "succeeded":
            done.append((seq, step, existing.get("resource") or {}))
            continue
        try:
            adapter = _adapter(adapters, step)
            if existing["state"] == "running":
                adopted = await adapter.find_existing(ctx)
                if adopted is not None:
                    async with pool.connection() as conn:
                        await store.update_step(
                            conn,
                            deployment_id,
                            seq,
                            state="succeeded",
                            resource=adopted,
                            log_tail="adopted what an earlier attempt of this step created",
                        )
                    done.append((seq, step, adopted))
                    continue
            async with pool.connection() as conn:
                await store.update_step(conn, deployment_id, seq, state="running", started=True)
            result = await adapter.execute(ctx)
        except Exception as failure:  # recorded, never raised: FR16 keeps every failure
            message = str(failure) or type(failure).__name__
            async with pool.connection() as conn:
                await store.update_step(
                    conn,
                    deployment_id,
                    seq,
                    state="failed",
                    error=message[:2000],
                    log_tail=getattr(failure, "log", "") or message,
                )
            return await _after_failure(
                pool,
                row,
                plan,
                candidate,
                previous,
                step,
                message,
                done,
                adapters,
                step_moved=getattr(failure, "moved", None),
            )
        async with pool.connection() as conn:
            await store.update_step(
                conn,
                deployment_id,
                seq,
                state="succeeded",
                resource=result.resource,
                command=result.command or None,
                log_tail=result.log,
            )
        done.append((seq, step, result.resource))

    last = done[-1][2] if done else {}
    async with pool.connection() as conn:
        await store.finish_deployment(
            conn,
            deployment_id,
            state="succeeded",
            verified=bool(last.get("verified")),
            fingerprint=last.get("fingerprint"),
            url=last.get("url"),
        )
        rolled_back_from = (row.get("authorised") or {}).get("deploymentId")
        if row["kind"] == "rollback" and last.get("verified") and rolled_back_from:
            await store.mark_rolled_back(conn, uuid.UUID(str(rolled_back_from)))
    if row["kind"] == "release" and last.get("verified") and candidate is not None and done:
        await _publish(pool, row, plan, candidate, previous, adapters, done)
    return "succeeded"


async def _publish(
    pool: AsyncConnectionPool,
    row: store.Row,
    plan: Plan,
    candidate: ReleaseCandidate,
    previous: VerifiedRelease | None,
    adapters: Mapping[str, Any],
    done: list[tuple[int, DeployStep, dict[str, Any]]],
) -> None:
    """Say what a verified release shipped, and tag its commit where there is one.

    After verification and never part of it: a tag GitHub refuses is recorded,
    and the release stays the verified release it is (review item C4-7).
    """
    async with pool.connection() as conn:
        run = await store.run_for_version(
            conn, row["project_id"], component="c4", version=row["deploy_version"]
        )
    notes = release_notes(
        deploy_version=row["deploy_version"],
        code_version=candidate.code_version,
        test_version=int((run or {}).get("source_version") or 0),
        candidate_hash=row["candidate_hash"],
        included=len(candidate.included),
        replaces=previous.deploy_version if previous is not None else None,
    )
    earlier = {step.id: resource for _, step, resource in done}
    commit = (earlier.get("commit") or {}).get("commit")
    publisher = adapters.get("github")
    action, detail = "Release notes", notes
    if commit and hasattr(publisher, "publish"):
        seq, step, _ = done[-1]
        ctx = StepContext(
            deployment=row,
            plan=plan,
            step=step,
            seq=seq,
            key="",
            candidate=candidate,
            previous=previous,
            earlier=earlier,
        )
        try:
            tagged = await publisher.publish(ctx, commit=commit, notes=notes)
        except StepFailed as refused:
            action, detail = "Could not tag the release", f"{refused}\n{notes}"
        else:
            action = "Tagged the release"
            detail = f"{tagged['tag']} at {commit[:12]}, {tagged['url']}\n{notes}"
    async with pool.connection() as conn:
        await store.record(
            conn,
            actor="system",
            action=action,
            target=f"deploy version {row['deploy_version']}, {row['target']}",
            detail=detail,
            project_id=row["project_id"],
            category="deployment",
        )


Loaded = tuple[Plan, ReleaseCandidate | None, VerifiedRelease | None]


async def _load_release(conn: Any, row: store.Row) -> Loaded | str:
    """A release carries out its deploy plan; the release before it is what it replaces."""
    found = await store.artefacts_at(
        conn,
        row["project_id"],
        version=row["deploy_version"],
        kinds=("deploy-plan", "release-candidate"),
    )
    if "deploy-plan" not in found:
        return "there is no deploy plan to carry out"
    deploy = DeployPlan.model_validate(found["deploy-plan"]["body"])
    candidate = (
        ReleaseCandidate.model_validate(found["release-candidate"]["body"])
        if "release-candidate" in found
        else None
    )
    previous_row = await store.latest_verified_release(conn, row["project_id"])
    previous = (
        verified_release(previous_row)
        if previous_row is not None and previous_row["id"] != row["id"]
        else None
    )
    return Plan(deploy.plan_id, list(deploy.steps)), candidate, previous


async def _load_rollback(conn: Any, row: store.Row) -> Loaded | str:
    """A rollback carries out the restore its failed release's plan prepared, then checks
    that the verified release's fingerprint is served again (NFR6)."""
    restores = await store.get_deployment(conn, row["restores"]) if row.get("restores") else None
    if restores is None:
        return "the rollback names no verified release to restore"
    target = verified_release(restores)
    from_version = int((row.get("authorised") or {}).get("fromVersion") or 0)
    found = await store.artefacts_at(
        conn, row["project_id"], version=from_version, kinds=("rollback-plan",)
    )
    if "rollback-plan" not in found:
        return "there is no rollback plan to carry out"
    prepared = RollbackPlan.model_validate(found["rollback-plan"]["body"])
    steps = [
        DeployStep(
            id=step.id,
            label=step.label,
            provider=step.provider,
            compensation=(
                "the release it replaced is not started again: a person decides"
                if step.moves_traffic
                else None
            ),
            moves_traffic=step.moves_traffic,
        )
        for step in prepared.steps
    ]
    steps.append(
        DeployStep(
            id="verify",
            label="Check the verified release is what is served again",
            depends_on=steps[-1].id if steps else None,
        )
    )
    restored = await store.artefacts_at(
        conn, row["project_id"], version=target.deploy_version, kinds=("release-candidate",)
    )
    candidate = (
        ReleaseCandidate.model_validate(restored["release-candidate"]["body"])
        if "release-candidate" in restored
        else None
    )
    return Plan(row["plan_id"], steps), candidate, target


async def _after_failure(
    pool: AsyncConnectionPool,
    row: store.Row,
    plan: Plan,
    candidate: ReleaseCandidate | None,
    previous: VerifiedRelease | None,
    failed: DeployStep,
    message: str,
    done: list[tuple[int, DeployStep, dict[str, Any]]],
    adapters: dict[str, Adapter],
    *,
    step_moved: bool | None = None,
) -> str:
    deployment_id = row["id"]
    moved = (failed.moves_traffic and step_moved is not False) or any(
        step.moves_traffic for _, step, _ in done
    )
    if moved:
        async with pool.connection() as conn:
            await store.finish_deployment(
                conn,
                deployment_id,
                state="awaiting-rollback-approval",
                cause=(
                    f"{failed.id} failed after production traffic may have moved: {message}. "
                    "Undoing it is a rollback, which a person must approve"
                ),
            )
        return "awaiting-rollback-approval"

    undone: list[str] = []
    for seq, step, resource in reversed(done):
        if not step.compensation:
            continue
        ctx = StepContext(
            deployment=row,
            plan=plan,
            step=step,
            seq=seq,
            key=step_key(row["project_id"], plan.plan_id, step.id, deployment_id),
            candidate=candidate,
            previous=previous,
            resource=resource,
        )
        try:
            await _adapter(adapters, step).compensate(ctx)
        except Exception as failure:  # recorded: a compensation that failed is a cause too
            async with pool.connection() as conn:
                await store.update_step(
                    conn,
                    deployment_id,
                    seq,
                    state="failed",
                    error=f"compensation failed: {failure}"[:2000],
                )
                await store.finish_deployment(
                    conn,
                    deployment_id,
                    state="failed",
                    cause=f"{failed.id} failed: {message}; undoing {step.id} failed too: {failure}",
                )
            return "failed"
        async with pool.connection() as conn:
            await store.update_step(
                conn, deployment_id, seq, state="compensated", log_tail=step.compensation
            )
        undone.append(step.id)
    async with pool.connection() as conn:
        await store.finish_deployment(
            conn,
            deployment_id,
            state="compensated",
            cause=(
                f"{failed.id} failed: {message}. Undone before any traffic moved: "
                f"{', '.join(undone) or 'nothing had been created'}"
            ),
        )
    return "compensated"
