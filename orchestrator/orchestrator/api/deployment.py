"""The deployment phase's routes, under `/projects/{id}/deployment`.

The browser's only way into Component 4, like every phase: the orchestrator is
the one front door. Every mutation answers with the whole snapshot.

A run starts only from a test version the test review approved, and analyses
the code those tests measured, which is what may ship: code whose tests were
approved against an earlier version would release something nobody reviewed,
and newer code waits for its own tests without holding a release back. The run
records the approved test version it starts from, and its first stage checks
the approval again, because a run can resume a day later.

A person's decision about one assessed update is recorded beside the risk
report, never in it: the report stays as the rules produced it, and the
snapshot lays the two side by side. The release guards, the saga and the
rollback approval land with Phase 5; until then an approval ends the run and
releases nothing.
"""

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from sdlc_contracts import (
    DEPLOY_GENERATING_STAGE_IDS,
    DEPLOY_STAGE_IDS,
    Blocker,
    DeploymentView,
    DeployPlan,
    DeploySnapshot,
    FeedbackReport,
    RiskReport,
    RollbackPlan,
    UpdateDecisionKind,
)

from ..components import spec_for
from ..db import store
from ..deploy import guards
from ..errors import Conflict, NotFound
from ..readmodel.deployment import (
    GATE_KIND,
    chosen_release_target,
    compose_deployment,
    ledger,
    prefetch_deployment,
)
from ..saga.executor import deployment_key
from ..wording import provider_name
from .continuing import continue_if_stopped_here
from .deps import Actor, Db, Owner, Supervisor, Watched, require_project, watched_now
from .stale_reviews import close_stale_review

router = APIRouter(tags=["deployment"])


class DecisionIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    kind: str = Field(pattern="^(approved|changes)$")
    note: str | None = None
    #: A cloud release spends provider minutes, so an approval carries the go
    #: ahead for it explicitly (G5). A local release does not need it.
    go_ahead: bool = Field(default=False, alias="goAhead")


class UpdateDecisionIn(BaseModel):
    """What a person decided about one update: ship it, leave it out, or not yet."""

    decision: UpdateDecisionKind
    note: str | None = None


class FeedbackDecisionIn(BaseModel):
    """What a person did with one suggestion from production: send it, or not."""

    decision: Literal["sent", "dismissed"]
    note: str | None = None


class FeedbackSendIn(BaseModel):
    """Suggestions from production sent to requirements together, as one change."""

    model_config = ConfigDict(populate_by_name=True)

    item_ids: list[str] = Field(min_length=1, alias="itemIds")


class TargetIn(BaseModel):
    """Where a release goes: this machine's containers, or the cloud."""

    target: str = Field(pattern="^(local|cloud)$")


class ScopeIn(BaseModel):
    """What a run analyses: which repository, and optionally which packages."""

    target: str = Field(pattern="^generated$")
    packages: list[str] | None = None


async def _tests_moved_past(conn: Any, project_id: str, gate: store.Row) -> tuple[int, int] | None:
    """The code the waiting run's tests measured and the newest tested code, if that moved on.

    The run reads the test version it started from (`source_version`), and that
    test version's run read a code version: G4's two hops, for the run that
    waits rather than for the newest approval. Newer code without approved tests
    is not a move: the code the run analysed is still what may ship.
    """
    run = await store.get_run(conn, gate["run_id"])
    test_version = int((run or {}).get("source_version") or 0)
    tested = await store.run_for_version(conn, project_id, component="c3", version=test_version)
    analysed = int((tested or {}).get("source_version") or 0)
    releasable = await store.releasable_code_version(conn, project_id)
    if analysed and releasable != analysed:
        return analysed, releasable
    return None


async def release_blockers_at(
    conn: Any, project_id: str, owner: str, *, gate: store.Row, go_ahead: bool = False
) -> list[Blocker]:
    """The release guards over what the pending gate would approve."""
    run = await store.get_run(conn, gate["run_id"]) if gate.get("run_id") else None
    facts = await guards.gather(
        conn,
        project_id,
        owner=owner,
        deploy_version=int(gate["requirements_version"]),
        target=await chosen_release_target(conn, project_id),
        test_version=int((run or {}).get("source_version") or 0),
        go_ahead=go_ahead,
    )
    return guards.release_blockers(facts)


async def _snapshot(
    conn: Any, project_id: str, owner: str, watched: frozenset[str]
) -> DeploySnapshot:
    """The phase as the request leaves it, read in a few round trips.

    Called last: whatever the request wrote is written, so from here it only
    reads, and its reads can share round trips and be asked once.
    """
    async with store.reads_only(conn):
        await prefetch_deployment(conn, project_id, owner)
        project = await require_project(conn, project_id, owner)
        return await compose_deployment(conn, project, watched=watched)


async def _refuse_while_measuring(conn: Any, project_id: str) -> None:
    # A working run only: a setting that affects only the next run may change
    # while a run waits at its gate, for testing's reason.
    if await store.active_run(conn, project_id, component="c4", states=store.WORKING_RUN_STATES):
        raise Conflict("a deployment run is analysing; change this once it reaches its gate")


@router.get("/projects/{project_id}/deployment")
async def get_deployment(
    project_id: str, conn: Db, owner: Owner, watched: Watched
) -> DeploySnapshot:
    return await _snapshot(conn, project_id, owner, watched)


@router.get("/projects/{project_id}/deployment/targets")
async def get_targets(project_id: str, conn: Db, owner: Owner) -> list[dict[str, Any]]:
    """Where a release can go, and whether each is usable here."""
    from ..config import get_settings

    await require_project(conn, project_id, owner)
    # The connections G5 asks for at the review, asked here too: cloud read as
    # usable on the server setting alone, and a release chosen for it was then
    # refused for a connection nobody had made.
    connections = (await store.settings_body(conn, owner)).get("connections") or {}
    working, failing = guards.cloud_connections(connections)
    missing = [
        provider_name(provider)
        for provider in guards.CLOUD_PROVIDERS
        if provider not in working and provider not in failing
    ]
    if not get_settings().c4_cloud_enabled:
        reason = "cloud releases are turned off on this orchestrator"
    elif missing:
        listed = (
            missing[0] if len(missing) == 1 else ", ".join(missing[:-1]) + f" and {missing[-1]}"
        )
        reason = f"connect {listed} in Settings first"
    elif failing:
        # Connected is not working: the check's verdict is what says so (X-12).
        provider, why = next(iter(failing.items()))
        reason = (
            f"the {provider_name(provider)} connection is not working ({why}): "
            "check it again in Settings"
        )
    else:
        reason = ""
    return [
        {
            "id": "local",
            "label": "This machine, in containers",
            "usable": True,
            "reason": "",
        },
        {
            "id": "cloud",
            "label": "Vercel and Render, through GitHub Actions",
            "usable": not reason,
            "reason": reason,
        },
    ]


#: The stages that write deployment files: detection keeps the release notes and
#: the baseline lockfile; pipeline generation writes the layer a release commits.
FileStage = Literal["pipeline-generation", "dependency-updates"]


@router.get("/projects/{project_id}/deployment/files/{path:path}")
async def get_deploy_file(
    project_id: str,
    path: str,
    conn: Db,
    owner: Owner,
    version: int | None = None,
    stage: FileStage = "pipeline-generation",
) -> dict[str, Any]:
    """One deployment file, by path: by default the generated layer's.

    Its own route, as the code phase's is, so the snapshot stays small while it
    is polled. The stage is part of the address because two stages can hold the
    same path at one version: the baseline lockfile and the candidate's.
    """
    await require_project(conn, project_id, owner)
    at = version or await store.current_deploy_version(conn, project_id)
    content = await store.deploy_file(conn, project_id, version=at, stage_id=stage, path=path)
    if content is None:
        raise NotFound("file", path)
    return {"path": path, "version": at, "stage": stage, "content": content}


class RollbackDecisionIn(BaseModel):
    """A person's decision about rolling one release back (FR20)."""

    decision: str = Field(pattern="^(approved|rejected)$")
    note: str | None = None


@router.post("/projects/{project_id}/deployment/deployments/{deployment_id}/retry")
async def release_again(
    project_id: str, deployment_id: str, conn: Db, owner: Owner, watched: Watched, actor: Actor
) -> DeploySnapshot:
    """Release the same approved version again, after a release undone before traffic moved.

    The saga undoes a release that failed before any traffic moved, and the only
    way on was a new analysis and a new review of a version already approved.
    Nothing reached production, so the same version under the same approval may
    go again: the guards are asked again first, as for any release, and asking
    twice finds the one release the first request wrote. After traffic moved,
    undoing is a rollback, which a person decides (FR20), so that is refused.
    """
    await require_project(conn, project_id, owner)
    try:
        undone_id = uuid.UUID(deployment_id)
    except ValueError as bad:
        raise NotFound("deployment", deployment_id) from bad
    undone = await store.get_deployment(conn, undone_id)
    if undone is None or undone["project_id"] != project_id or undone["kind"] != "release":
        raise NotFound("release", deployment_id)
    if undone["state"] != "compensated":
        raise Conflict(
            "only a release undone before any traffic moved is released again; after traffic "
            "moved, undoing it is a rollback, which a person decides"
        )
    version = undone["deploy_version"]
    if version != await store.current_deploy_version(conn, project_id):
        raise Conflict(
            f"deploy version {version} is no longer the newest; release the newest version "
            "from its own review"
        )
    authorised = dict(undone["authorised"] or {})
    facts = await guards.gather(
        conn,
        project_id,
        owner=owner,
        deploy_version=version,
        target=undone["target"],
        test_version=int(authorised.get("testVersion") or 0),
        go_ahead=bool(authorised.get("goAhead")),
    )
    blockers = guards.release_blockers(facts)
    if blockers:
        raise Conflict(
            "the release cannot start again: " + "; ".join(b.message for b in blockers),
            detail=[b.model_dump(by_alias=True, mode="json") for b in blockers],
        )
    found = await store.artefacts_at(conn, project_id, version=version, kinds=("deploy-plan",))
    plan = DeployPlan.model_validate(found["deploy-plan"]["body"])
    try:
        _, created = await store.create_deployment(
            conn,
            project_id=project_id,
            deploy_version=version,
            kind="release",
            target=undone["target"],
            plan_id=plan.plan_id,
            candidate_hash=plan.candidate_hash,
            idempotency_key=deployment_key(
                project_id, plan.plan_id, "release", f"again:{undone_id}"
            ),
            authorised={**authorised, "releasedAgainBy": actor, "after": str(undone_id)},
            requested_by=actor,
            gate_id=undone["gate_id"],
        )
    except store.DeploymentInFlight as busy:
        raise Conflict(f"the release waits: {busy}") from busy
    if created:
        await store.record(
            conn,
            actor=actor,
            action="Queued the release again",
            target=f"deploy version {version}, {undone['target']}",
            detail=f"after release {undone_id}, undone before any traffic moved",
            project_id=project_id,
            category="deployment",
        )
        await store.post_thread_message(
            conn,
            project_id,
            kind="system",
            author=actor,
            content=f"Releasing deploy version {version} again, under the same approval.",
            stage_id="release",  # type: ignore[arg-type]
        )
    return await _snapshot(conn, project_id, owner, watched)


@router.post("/projects/{project_id}/deployment/deployments/{deployment_id}/rollback/decision")
async def decide_rollback(
    project_id: str,
    deployment_id: str,
    body: RollbackDecisionIn,
    conn: Db,
    owner: Owner,
    watched: Watched,
    actor: Actor,
) -> DeploySnapshot:
    """FR20: a rollback starts only when a person decides it, and the decision is on record.

    Approving writes one rollback deployment for the saga: it restores the
    verified release the release's own plan prepared, and it is reported restored
    only when that release's fingerprint is served again. The same decision
    twice finds the same rollback while it is still to run or running; after one
    ended without restoring, approving again is the next attempt. Declining needs
    a note saying why, and closes the question: the release no longer waits on
    anyone.
    """
    await require_project(conn, project_id, owner)
    try:
        release_id = uuid.UUID(deployment_id)
    except ValueError as bad:
        raise NotFound("deployment", deployment_id) from bad
    release = await store.get_deployment(conn, release_id)
    if release is None or release["project_id"] != project_id:
        raise NotFound("deployment", deployment_id)
    note = (body.note or "").strip()
    version = release["deploy_version"]

    if body.decision == "rejected":
        if not note:
            raise Conflict("declining a rollback needs a note saying why")
        await store.close_declined_rollback(conn, release_id)
        await store.record(
            conn,
            actor=actor,
            action="Declined a rollback",
            target=f"deploy version {version}",
            detail=note[:500],
            project_id=project_id,
            category="approval",
        )
        await store.post_thread_message(
            conn,
            project_id,
            kind="system",
            author=actor,
            content=f"Declined rolling back deploy version {version}: {note}",
            stage_id="release",  # type: ignore[arg-type]
        )
        return await _snapshot(conn, project_id, owner, watched)

    found = await store.artefacts_at(conn, project_id, version=version, kinds=("rollback-plan",))
    plan = RollbackPlan.model_validate(found["rollback-plan"]["body"]) if found else None
    restores = (
        await store.get_deployment(conn, uuid.UUID(plan.restore_target.deployment_id))
        if plan is not None and plan.restore_target is not None
        else None
    )
    # The plan was fixed at analysis. If the release it restores was itself rolled
    # back since, the newest verified release still standing on this target is
    # restored instead; with none, the guard refuses (review item C4-9).
    if restores is not None and restores["state"] != "succeeded":
        newest = await store.latest_verified_release(conn, project_id)
        if (
            newest is not None
            and newest["id"] != release_id
            and newest["target"] == release["target"]
        ):
            restores = newest
    blockers = guards.rollback_blockers(release, plan, restores)
    if blockers:
        raise Conflict(
            "the rollback cannot start: " + "; ".join(b.message for b in blockers),
            detail=[b.model_dump(by_alias=True, mode="json") for b in blockers],
        )
    if plan is None or plan.restore_target is None or restores is None:  # the guard said why
        raise Conflict("the rollback cannot start: there is nothing verified to restore")
    plan_id = f"{project_id}-rollback-v{version}"
    # Keyed by attempt. One key per release meant that approving again after a
    # rollback failed found the failed row and started nothing, so the release
    # stayed down with no way to try again (review item C4-3). The first keeps
    # the key it always had.
    attempt = await store.rollback_attempts(conn, release_id) + 1
    authorisation = f"release:{release_id}" + (f":attempt:{attempt}" if attempt > 1 else "")
    try:
        _, created = await store.create_deployment(
            conn,
            project_id=project_id,
            deploy_version=restores["deploy_version"],
            kind="rollback",
            target=release["target"],
            plan_id=plan_id,
            candidate_hash=restores["candidate_hash"],
            idempotency_key=deployment_key(project_id, plan_id, "rollback", authorisation),
            authorised={
                "kind": "rollback",
                "by": actor,
                "deploymentId": str(release_id),
                "fromVersion": version,
                "note": note,
                "attempt": attempt,
            },
            requested_by=actor,
            restores=restores["id"],
        )
    except store.DeploymentInFlight as busy:
        raise Conflict(f"the rollback waits: {busy}") from busy
    if created:
        await store.record(
            conn,
            actor=actor,
            action="Approved a rollback",
            target=f"deploy version {version} to deploy version {restores['deploy_version']}",
            detail=note[:500],
            project_id=project_id,
            category="approval",
        )
        await store.post_thread_message(
            conn,
            project_id,
            kind="system",
            author=actor,
            content=(
                f"Rolling back deploy version {version} to deploy version "
                f"{restores['deploy_version']}, candidate "
                f"{restores['candidate_hash'][:12]}."
            ),
            stage_id="release",  # type: ignore[arg-type]
        )
    return await _snapshot(conn, project_id, owner, watched)


class WindowIn(BaseModel):
    """A bounded monitoring window over the current release."""

    rounds: int = Field(default=10, ge=1, le=120)
    interval: float = Field(default=30.0, ge=1.0, le=600.0)


@router.post("/projects/{project_id}/deployment/monitoring/window")
async def open_monitoring_window(
    project_id: str, body: WindowIn, request: Request, conn: Db, owner: Owner, watched: Watched
) -> DeploySnapshot:
    """Watch the release serving now for a bounded window, in the background.

    Bounded, because a free host probed forever never sleeps. The window writes
    its samples, its report, and, if it finds the release down, a waiting
    rollback decision; it never starts a rollback. Only the release that serves
    now is watched: an older one's address answers for a later deployment.
    """
    await require_project(conn, project_id, owner)
    target = await chosen_release_target(conn, project_id)
    release = await store.serving_release(conn, project_id, target)
    if release is None:
        raise Conflict(
            f"nothing verified serves this project on the {target} target to watch: "
            "no release has been verified, or the newest one is still running or waits "
            "on a rollback decision"
        )
    if not request.app.state.monitor.open(
        release["id"], rounds=body.rounds, interval=body.interval
    ):
        raise Conflict(f"deploy version {release['deploy_version']} is being watched already")
    # Read again: the window this request opened is not in what was read before it.
    return await _snapshot(conn, project_id, owner, watched_now(request.app.state))


async def _undecided_feedback(
    conn: Any, project_id: str, item_ids: list[str]
) -> tuple[dict[str, Any], FeedbackReport, list[Any]]:
    """The newest feedback report and the named items, each refused if decided already."""
    found = await store.newest_artefact(conn, project_id, "feedback")
    if found is None:
        raise Conflict("there is no feedback from production to decide on")
    report = FeedbackReport.model_validate(found["body"])
    by_id = {entry.id: entry for entry in report.items}
    decided = {
        row["target_id"]: row["value"]
        for row in await store.overlays(conn, project_id)
        if row["kind"] == "feedback_decision"
    }
    items = []
    for item_id in dict.fromkeys(item_ids):
        item = by_id.get(item_id)
        if item is None:
            raise NotFound("feedback item", item_id)
        if item_id in decided:
            value = decided[item_id]
            raise Conflict(
                f"this suggestion was {value['decision']} already"
                + (
                    f", as design version {value['designVersion']}"
                    if value.get("designVersion")
                    else ""
                )
            )
        items.append(item)
    return found, report, items


async def _send_feedback(
    conn: Any,
    project_id: str,
    found: dict[str, Any],
    report: FeedbackReport,
    items: list[Any],
    actor: str,
    note: str = "",
) -> dict[str, Any] | None:
    """Send suggestions to requirements as one design change note; returns the run it started.

    One note, so several suggestions open one design version and one run of
    Requirements and Design rather than a version and a run each.
    """
    from .design import request_design_change

    origin = f"From production, deploy version {report.deploy_version}"
    if len(items) == 1:
        note = f"{items[0].suggested_requirement} ({origin}: {items[0].evidence})"
    else:
        note = f"{origin}:\n" + "\n".join(
            f"- {item.suggested_requirement} ({item.evidence})" for item in items
        )
    design_version, run = await request_design_change(conn, project_id, note=note, by=actor)
    for item in items:
        await store.put_overlay(
            conn,
            project_id=project_id,
            version=int(found["version"]),
            kind="feedback_decision",  # type: ignore[arg-type]
            target_id=item.id,
            value={"decision": "sent", "note": note, "designVersion": design_version},
            by=actor,
        )
        await store.record(
            conn,
            actor=actor,
            action="Sent a suggestion to requirements",
            target=item.summary[:200],
            detail=(note or item.suggested_requirement)[:500],
            project_id=project_id,
            category="approval",
        )
    await store.post_thread_message(
        conn,
        project_id,
        kind="system",
        author="platform",
        content=(
            f"{actor} sent {'a suggestion' if len(items) == 1 else f'{len(items)} suggestions'} "
            f"to requirements as design version {design_version}: "
            + "; ".join(item.suggested_requirement for item in items)
        ),
        stage_id="monitoring",  # type: ignore[arg-type]
    )
    return run


@router.post("/projects/{project_id}/deployment/feedback/send")
async def send_feedback(
    project_id: str,
    body: FeedbackSendIn,
    conn: Db,
    owner: Owner,
    watched: Watched,
    supervisor: Supervisor,
    actor: Actor,
) -> DeploySnapshot:
    """Send one or more suggestions from production to requirements, as one change (M5).

    The change opens a design version and runs Requirements and Design again
    on every stage, which calls the model, and every later phase then has a
    new design to build from. The page says so before it sends; sending
    several together is one version and one run, where one at a time was a
    version and a run each.
    """
    await require_project(conn, project_id, owner)
    found, report, items = await _undecided_feedback(conn, project_id, body.item_ids)
    run = await _send_feedback(conn, project_id, found, report, items, actor)
    snapshot = await _snapshot(conn, project_id, owner, watched)
    if run is not None and supervisor is not None:
        from .projects import _after_commit

        _after_commit(supervisor, run["id"])
    return snapshot


@router.post("/projects/{project_id}/deployment/feedback/{item_id}/decision")
async def decide_feedback(
    project_id: str,
    item_id: str,
    body: FeedbackDecisionIn,
    conn: Db,
    owner: Owner,
    watched: Watched,
    supervisor: Supervisor,
    actor: Actor,
) -> DeploySnapshot:
    """Send one suggestion from production to requirements, or dismiss it (M5).

    Sent, it becomes a design change note through the path a person's own change
    takes (`request_design_change`), so C1's next run has the suggested
    requirement in its input; `.../feedback/send` sends several as one change.
    Dismissing needs a note saying why. Either is final: an item is sent once,
    because a second note would ask C1 for the same change twice.
    """
    await require_project(conn, project_id, owner)
    found, report, [item] = await _undecided_feedback(conn, project_id, [item_id])
    note = (body.note or "").strip()
    if body.decision == "dismissed" and not note:
        raise Conflict("dismissing a suggestion needs a note saying why")

    run = None
    if body.decision == "sent":
        run = await _send_feedback(conn, project_id, found, report, [item], actor, note)
    else:
        await store.put_overlay(
            conn,
            project_id=project_id,
            version=int(found["version"]),
            kind="feedback_decision",  # type: ignore[arg-type]
            target_id=item_id,
            value={"decision": "dismissed", "note": note, "designVersion": None},
            by=actor,
        )
        await store.record(
            conn,
            actor=actor,
            action="Dismissed a suggestion",
            target=item.summary[:200],
            detail=note[:500],
            project_id=project_id,
            category="approval",
        )
        await store.post_thread_message(
            conn,
            project_id,
            kind="system",
            author="platform",
            content=f"{actor} dismissed a suggestion: {note}",
            stage_id="monitoring",  # type: ignore[arg-type]
        )
    snapshot = await _snapshot(conn, project_id, owner, watched)
    if run is not None and supervisor is not None:
        from .projects import _after_commit

        _after_commit(supervisor, run["id"])
    return snapshot


@router.get("/projects/{project_id}/deployment/ledger")
async def get_ledger(
    project_id: str, conn: Db, owner: Owner, limit: int = 50
) -> list[DeploymentView]:
    """Every deployment attempt, whatever came of it, with its steps and cause (FR16)."""
    await require_project(conn, project_id, owner)
    return await ledger(conn, project_id, limit=max(1, min(limit, 500)))


@router.post("/projects/{project_id}/deployment/target")
async def choose_target(
    project_id: str, body: TargetIn, conn: Db, owner: Owner, watched: Watched, actor: Actor
) -> DeploySnapshot:
    await require_project(conn, project_id, owner)
    await _refuse_while_measuring(conn, project_id)
    await store.put_overlay(
        conn,
        project_id=project_id,
        version=await store.current_deploy_version(conn, project_id),
        kind="release_target",  # type: ignore[arg-type]
        target_id="target",
        value=body.target,
        by=actor,
    )
    return await _snapshot(conn, project_id, owner, watched)


class PolicyIn(BaseModel):
    """Whether Low updates may ship without a review (FR17), and where."""

    model_config = ConfigDict(populate_by_name=True)

    auto_deploy_low: bool = Field(alias="autoDeployLow")
    #: Automatic releases to the cloud are a separate opt in, off by default,
    #: because each one spends provider minutes nobody reviewed.
    cloud_auto_deploy: bool = Field(default=False, alias="cloudAutoDeploy")


@router.post("/projects/{project_id}/deployment/policy")
async def choose_policy(
    project_id: str, body: PolicyIn, conn: Db, owner: Owner, watched: Watched, actor: Actor
) -> DeploySnapshot:
    """The standing policy a Low update ships under; recorded, with who set it."""
    await require_project(conn, project_id, owner)
    await _refuse_while_measuring(conn, project_id)
    value = {"autoDeployLow": body.auto_deploy_low, "cloudAutoDeploy": body.cloud_auto_deploy}
    await store.put_overlay(
        conn,
        project_id=project_id,
        version=await store.current_deploy_version(conn, project_id),
        kind="release_policy",  # type: ignore[arg-type]
        target_id="policy",
        value=value,
        by=actor,
    )
    await store.record(
        conn,
        actor=actor,
        action="Set the release policy",
        target="automatic Low releases",
        detail=(
            ("on" if body.auto_deploy_low else "off")
            + (", including the cloud" if body.cloud_auto_deploy else ", local only")
        ),
        project_id=project_id,
        category="approval",
    )
    return await _snapshot(conn, project_id, owner, watched)


@router.post("/projects/{project_id}/deployment/scope")
async def choose_scope(
    project_id: str, body: ScopeIn, conn: Db, owner: Owner, watched: Watched, actor: Actor
) -> DeploySnapshot:
    await require_project(conn, project_id, owner)
    await _refuse_while_measuring(conn, project_id)
    await store.put_overlay(
        conn,
        project_id=project_id,
        version=await store.current_deploy_version(conn, project_id),
        kind="update_scope",  # type: ignore[arg-type]
        target_id="scope",
        value={"target": body.target, "packages": body.packages},
        by=actor,
    )
    return await _snapshot(conn, project_id, owner, watched)


@router.post("/projects/{project_id}/deployment/run")
async def start_run(
    project_id: str, conn: Db, owner: Owner, watched: Watched, supervisor: Supervisor, actor: Actor
) -> DeploySnapshot:
    """Analyse the updates, generate and stage a candidate, then stop at the gate.

    The run is on the code the newest approved tests measured. Newer code waits
    for its own tests: the next sprint's code refused the run, and nothing could
    be released until that sprint was tested too.
    """
    await require_project(conn, project_id, owner)

    test_version = await store.approved_test_version(conn, project_id)
    if not test_version:
        raise Conflict(
            "the test review has not approved a run on the generated app, so there is "
            "nothing this phase may deploy: an approved run on a sample says nothing about "
            "the app"
        )
    tested = await store.run_for_version(conn, project_id, component="c3", version=test_version)
    tested_code = int((tested or {}).get("source_version") or 0)

    await store.lock_run_axis(conn, project_id, "c4")
    gate = await store.pending_gate(conn, project_id=project_id, kind=GATE_KIND)
    if gate is not None:
        moved = await _tests_moved_past(conn, project_id, gate)
        if moved is None:
            raise Conflict(
                "a deployment review is waiting on this project; decide it before starting "
                "another run"
            )
        # The review is of an analysis of code that newer tested code replaced:
        # its approval is refused (G4), requested changes would analyse the same
        # older code again, and this refused a new run while it waited.
        analysed, releasable = moved
        await close_stale_review(
            conn,
            project_id,
            gate,
            by=actor,
            reason=(
                f"This analysis is of code version {analysed}, and version {releasable} has "
                "approved tests now, so this review closes and the updates are analysed on "
                f"version {releasable}."
            ),
            stage_id="deployment-review",
            category="deployment",
            what=f"deploy version {gate['requirements_version']}",
        )
    if await store.active_run(conn, project_id, component="c4") is not None:
        raise Conflict("a deployment run is already in flight on this project")

    deploy_version = await store.next_deploy_version(conn, project_id)
    await store.seed_deploy_stages(conn, project_id)
    await store.set_stages(conn, project_id, list(DEPLOY_GENERATING_STAGE_IDS), status="generating")
    run = await store.create_run(
        conn,
        project_id=project_id,
        requirements_version=deploy_version,
        component="c4",
        source_version=test_version,
    )
    await store.record(
        conn,
        actor=actor,
        action="Started a deployment run",
        target=f"deploy version {deploy_version}",
        detail=f"From test version {test_version}, which tested code version {tested_code}.",
        project_id=project_id,
        run_id=run["id"],
        category="deployment",
    )
    if supervisor is not None:
        from .projects import _after_commit

        _after_commit(supervisor, run["id"])
    return await _snapshot(conn, project_id, owner, watched)


@router.post("/projects/{project_id}/deployment/stages/{stage_id}/retry")
async def retry_stage(
    project_id: str,
    stage_id: str,
    conn: Db,
    owner: Owner,
    watched: Watched,
    supervisor: Supervisor,
    actor: Actor,
) -> DeploySnapshot:
    """Re-run one analysis stage at the deploy version already produced."""
    if stage_id not in DEPLOY_STAGE_IDS:
        raise NotFound("stage", stage_id)
    if stage_id not in spec_for("c4").stage_nodes():
        raise Conflict(f"{stage_id} is not a stage a run produces; there is nothing to re-run here")
    await require_project(conn, project_id, owner)
    version = await store.current_deploy_version(conn, project_id)
    if not version:
        raise Conflict("nothing has been analysed yet, so there is no stage to retry")
    if await store.version_is_approved(conn, project_id, gate_kind=GATE_KIND, version=version):
        raise Conflict(
            f"deploy version {version} was approved, so its stages are settled. Start a new "
            "run to analyse again."
        )
    await store.lock_run_axis(conn, project_id, "c4")
    # Try again on the stage that stopped the phase's run goes on with that
    # run, to the review, rather than regenerating the one stage and stopping.
    continued = await continue_if_stopped_here(conn, project_id, spec_for("c4"), stage_id, by=actor)
    if continued is not None:
        if supervisor is not None:
            from .projects import _after_commit

            _after_commit(supervisor, continued["id"])
        return await _snapshot(conn, project_id, owner, watched)
    if await store.active_run(conn, project_id, component="c4", states=store.WORKING_RUN_STATES):
        raise Conflict(
            "a deployment run is already working on this project; wait for it to finish "
            "before retrying a stage"
        )
    latest = await store.latest_run(conn, project_id, component="c4")
    await store.set_stage(conn, project_id, stage_id, status="generating")  # type: ignore[arg-type]
    run = await store.create_run(
        conn,
        project_id=project_id,
        requirements_version=version,
        component="c4",
        only_stage=stage_id,
        source_version=(latest or {}).get("source_version"),
    )
    if supervisor is not None:
        from .projects import _after_commit

        _after_commit(supervisor, run["id"])
    return await _snapshot(conn, project_id, owner, watched)


@router.post("/projects/{project_id}/deployment/decision")
async def submit_decision(
    project_id: str,
    body: DecisionIn,
    conn: Db,
    owner: Owner,
    watched: Watched,
    supervisor: Supervisor,
    actor: Actor,
) -> DeploySnapshot:
    """The deployment review gate.

    A change is regenerated at a new deploy version, allocated here because only
    the store allocates version numbers, and carried in the resume payload, as
    the code and testing gates carry theirs.
    """
    await require_project(conn, project_id, owner)
    gate = await store.pending_gate(conn, project_id=project_id, kind=GATE_KIND)
    if gate is None:
        raise Conflict("there is no deployment decision waiting on this project")
    if body.kind == "changes" and not (body.note or "").strip():
        raise Conflict("requesting changes needs a note saying what to change")
    if body.kind == "changes":
        moved = await _tests_moved_past(conn, project_id, gate)
        if moved is not None:
            analysed, releasable = moved
            raise Conflict(
                f"this analysis is of code version {analysed}, and version {releasable} has "
                "approved tests now, so requested changes would analyse the older code again. "
                f"Analyse the updates again: that analyses version {releasable} and closes "
                "this review"
            )
    if body.kind == "approved":
        blockers = await release_blockers_at(
            conn, project_id, owner, gate=gate, go_ahead=body.go_ahead
        )
        if blockers:
            raise Conflict(
                "the release guards refuse this approval: "
                + "; ".join(blocker.message for blocker in blockers),
                detail=[blocker.model_dump(by_alias=True, mode="json") for blocker in blockers],
            )

    resolved = await store.resolve_gate(
        conn,
        gate["id"],
        decision=body.kind,  # type: ignore[arg-type]
        by=actor,
        note=body.note,
    )
    if resolved is None:
        raise Conflict("that decision was already recorded")

    await store.post_thread_message(
        conn,
        project_id,
        kind="system",
        author=actor,
        content=(
            f"Approved deploy version {gate['requirements_version']}."
            if body.kind == "approved"
            else f"Requested changes: {body.note}"
        ),
        stage_id="deployment-review",  # type: ignore[arg-type]
    )
    await store.record(
        conn,
        actor=actor,
        action="Approved the deployment"
        if body.kind == "approved"
        else "Requested deployment changes",
        target=f"deploy version {gate['requirements_version']}",
        detail=(body.note or "")[:500],
        project_id=project_id,
        run_id=gate["run_id"],
        category="approval",
    )

    resume: dict[str, Any] = {
        "kind": body.kind,
        "note": body.note or "",
        "by": actor,
        "goAhead": body.go_ahead,
        "gateId": str(gate["id"]),
    }
    if body.kind == "changes":
        version = await store.next_deploy_version(conn, project_id)
        await store.set_run_version(conn, gate["run_id"], version)
        await store.set_stages(
            conn, project_id, list(DEPLOY_GENERATING_STAGE_IDS), status="generating"
        )
        resume["version"] = version
    await store.set_run_state(conn, gate["run_id"], "queued", resume_payload=resume)

    if supervisor is not None:
        from .projects import _after_commit

        _after_commit(supervisor, gate["run_id"])
    return await _snapshot(conn, project_id, owner, watched)


@router.post("/projects/{project_id}/deployment/updates/{update_id}/decision")
async def decide_update(
    project_id: str,
    update_id: str,
    body: UpdateDecisionIn,
    conn: Db,
    owner: Owner,
    watched: Watched,
    actor: Actor,
) -> DeploySnapshot:
    """One person's decision about one assessed update, beside the report.

    Recorded as an overlay with the level the update had when it was decided,
    so a decision taken at Medium stops counting if a later run finds the same
    update High. Approving a High update needs a review note (FR17's manual
    review), and leaving any update out needs a note saying why.
    """
    await require_project(conn, project_id, owner)
    version = await store.current_deploy_version(conn, project_id)
    found = await store.artefacts_at(conn, project_id, version=version, kinds=("risk-report",))
    if "risk-report" not in found:
        raise Conflict("there is no risk assessment at the current deploy version to decide on")
    risk = RiskReport.model_validate(found["risk-report"]["body"])
    assessment = next((a for a in risk.assessments if a.update_id == update_id), None)
    if assessment is None:
        raise NotFound("update", update_id)
    note = (body.note or "").strip()
    level = assessment.arbitration.final
    if body.decision == "approved" and level == "high" and not note:
        raise Conflict(
            "approving a High update needs a review note: a High update is reviewed by a person"
        )
    if body.decision == "rejected" and not note:
        raise Conflict("leaving an update out needs a note saying why")

    await store.put_overlay(
        conn,
        project_id=project_id,
        version=version,
        kind="update_decision",  # type: ignore[arg-type]
        target_id=update_id,
        value={"decision": body.decision, "note": note, "levelAtDecision": level},
        by=actor,
    )
    await store.record(
        conn,
        actor=actor,
        action={
            "approved": "Approved an update",
            "rejected": "Left an update out",
            "deferred": "Deferred an update",
        }[body.decision],
        target=f"{assessment.key} ({level})",
        detail=note[:500],
        project_id=project_id,
        category="approval",
    )
    return await _snapshot(conn, project_id, owner, watched)
