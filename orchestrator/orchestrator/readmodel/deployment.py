"""Compose a DeploySnapshot from the rows that hold it.

The same three rules as the other phases' read models. Every artefact lives in
its own versioned row, validated against its own schema; this puts them together
with stage, gate and thread state into the one payload the browser reads; and
nothing is stored that can be derived.

Two things here are this phase's own.

**Decisions sit beside the risk report.** A person approving, rejecting or
deferring an update is an overlay, read here and laid beside the report as
`decisions`. The report is exactly what the rule produced. A decision made when
an update was rated lower does not count once its level rises, so a reader is
asked again rather than shown a stale approval.

**The ledger comes from the deployment tables.** A release and a rollback are
carried out by the orchestrator after the gate, so their state is read from
`app.deployments` and `app.deploy_steps`, newest first, with every failure and
its cause, rather than from any artefact a run wrote.

The stage and thread filters are not optional: `stage_states` and the thread
hold every phase's rows, and `DeployStageId` is a Literal over ten ids.
"""

from typing import Any

from psycopg import AsyncConnection
from sdlc_contracts import (
    DEPLOY_ARTEFACT_STAGE_IDS,
    DEPLOY_STAGE_IDS,
    Blocker,
    ChangelogReport,
    DependencyUpdates,
    DeploymentStepView,
    DeploymentView,
    DeployPlan,
    DeploySnapshot,
    DeployStageId,
    DeployStageState,
    DeployThreadMessage,
    FeedbackDecisionView,
    FeedbackReport,
    ImpactReport,
    MonitoringReport,
    PipelineConfig,
    ReleaseCandidate,
    RiskReport,
    RollbackPlan,
    UpdateDecisionView,
)

from ..db import store
from ..deploy import guards
from ..deploy.guards import newest_decisions
from ..deploy.guards import still_counts as counts
from ..deploy.provision import cloud_resources_of
from ..deploy.records import verified_release
from ..deploy.supervisor import RECENT_SECONDS
from ..model_use import kept_model_use
from .gates import gate_state
from .runs import run_status

GATE_KIND = "c4-deploy-review"
TEST_GATE_KIND = "c3-test-review"

#: Every deploy kind, read at the current deploy version.
DEPLOY_KINDS = (
    "dependency-updates",
    "changelog-report",
    "impact-report",
    "risk-report",
    "pipeline-config",
    "deploy-plan",
    "release-candidate",
    "rollback-plan",
    "monitoring-report",
    "feedback",
)


def _stage(row: store.Row) -> DeployStageState:
    return DeployStageState(
        id=row["stage_id"],
        status=row["status"],
        generated_from_version=row["generated_from_version"],
        generated_at=row["generated_at"],
        summary=row["summary"],
        error=row["error"],
        model_use=kept_model_use(row),
    )


#: A run that is over, and so will hand nothing more to the release runner.
_FINISHED_RUN = frozenset({"done", "failed", "superseded"})


async def _runner_at_work(
    conn: AsyncConnection,
    project_id: str,
    deploy_version: int,
    stages: dict[DeployStageId, DeployStageState],
    approved: bool,
    deployments: list[DeploymentView],
    watched: frozenset[str],
) -> None:
    """The runner's two stages marked working while the orchestrator is about to act on them.

    A page reads the phase again only while a stage is generating or a
    deployment is pending or running, and two moments looked finished when they
    were not. After an approval the run resumes in the background and writes
    the release a moment later; after a verified release the monitor opens its
    window within its next poll. In both, nothing was busy, so the page stopped
    asking and showed neither the release nor its window until it was reloaded,
    which is how Book Tracker's first cloud release looked unreleased while it
    served. Each is marked from the rule that will act on it: the run, still
    going, with this version approved or its analysis done and nothing waiting
    on a person; and the monitor's own choice of what to watch.
    """
    if (
        deploy_version
        and stages["release"].status == "pending"
        and not any(one.deploy_version == deploy_version for one in deployments)
    ):
        run = await store.latest_run(conn, project_id, component="c4")
        going = run is not None and run["state"] not in _FINISHED_RUN
        analysed = all(
            stages[stage_id].status in ("complete", "skipped")
            for stage_id in DEPLOY_ARTEFACT_STAGE_IDS
        )
        if going and (approved or (run["state"] == "running" and analysed)):
            stages["release"] = DeployStageState(
                id="release",
                status="generating",
                summary=f"deploy version {deploy_version} is being handed to the release runner",
            )
    if stages["monitoring"].status == "pending" and not any(
        one.id in watched for one in deployments
    ):
        waiting = [
            row
            for row in await store.unwatched_releases(conn, recent_seconds=RECENT_SECONDS)
            if row["project_id"] == project_id
        ]
        if waiting:
            stages["monitoring"] = DeployStageState(
                id="monitoring",
                status="generating",
                summary=(
                    f"a monitoring window opens on deploy version {waiting[-1]['deploy_version']}"
                ),
            )


def _latest_choice(rows: list[store.Row], kind: str, target: str) -> Any:
    found = None
    for row in rows:
        if row["kind"] == kind and row["target_id"] == target:
            found = row["value"]
    return found


def _decisions(
    risk: RiskReport | None,
    overlay_rows: list[store.Row],
    candidate: ReleaseCandidate | None,
) -> list[UpdateDecisionView]:
    """What a person decided about each assessed update, and what is still owed.

    The newest decision per update across versions: an update keeps its id when
    the same move from one version to another is assessed again, so a decision
    follows the update rather than the version it was taken at. It stops
    counting when the update's level has risen above the level it was taken at.

    A decision is owed where the release guard asks for one (G1): on a Medium or
    High update the candidate carries. An update the candidate left out, such as
    a High one on a first release with nothing to roll back to, does not ship in
    this release, and the page would otherwise ask for a decision that counts
    towards nothing.
    """
    if risk is None:
        return []
    included = set(candidate.included) if candidate else set()
    newest = newest_decisions(overlay_rows)
    views = []
    for assessment in risk.assessments:
        final = assessment.arbitration.final
        row = newest.get(assessment.update_id)
        value = row["value"] if row else {}
        at_level = value.get("levelAtDecision") if isinstance(value, dict) else None
        still_counts = row is not None and counts(at_level, final)
        decision = value.get("decision") if still_counts and isinstance(value, dict) else None
        views.append(
            UpdateDecisionView(
                update_id=assessment.update_id,
                decision=decision,
                by=row["by"] if still_counts and row else None,
                at=row["at"] if still_counts and row else None,
                note=value.get("note") if still_counts and isinstance(value, dict) else None,
                level_at_decision=at_level if still_counts else None,
                needs_decision=final != "low"
                and decision is None
                and assessment.update_id in included,
                needs_review_note=final == "high",
            )
        )
    return views


async def ledger(
    conn: AsyncConnection, project_id: str, *, limit: int = 10
) -> list[DeploymentView]:
    """Every deployment attempt, newest first, with its steps and its cause (FR16)."""
    views = []
    rows = await store.list_deployments(conn, project_id, limit=limit)
    steps_by_id = await store.steps_of(conn, [row["id"] for row in rows])
    for row in rows:
        steps = [
            DeploymentStepView(
                seq=step["seq"],
                step_id=step["step_id"],
                label=step["step_id"],
                provider=step["provider"],
                state=step["state"],
                moves_traffic=step["moves_traffic"],
                attempt=step["attempt"],
                command=step["command"] or "",
                log_tail=step["log_tail"] or "",
                error=step["error"] or "",
                started_at=step["started_at"],
                finished_at=step["finished_at"],
            )
            for step in steps_by_id.get(str(row["id"]), [])
        ]
        authorised = row["authorised"] or {}
        views.append(
            DeploymentView(
                id=str(row["id"]),
                kind=row["kind"],
                target=row["target"],
                state=row["state"],
                candidate_hash=row["candidate_hash"],
                deploy_version=row["deploy_version"],
                verified=row["verified"],
                cause=row["cause"] or "",
                fault_injected=row["fault_injected"] or "",
                requested_by=row["requested_by"],
                authorised_by=str(authorised.get("by", "")),
                restores=str(row["restores"]) if row["restores"] else None,
                url=row["url"],
                created_at=row["created_at"],
                finished_at=row["finished_at"],
                steps=steps,
            )
        )
    return views


async def approved_test_version(conn: AsyncConnection, project_id: str) -> int:
    """The newest test version the test review approved, or zero."""
    history = await store.gate_history(conn, project_id, kind=TEST_GATE_KIND)
    approved = [row["requirements_version"] for row in history if row["decision"] == "approved"]
    return max(approved, default=0)


async def chosen_release_target(conn: AsyncConnection, project_id: str) -> str:
    """Where a release goes: the newest choice, or the orchestrator's default."""
    from ..config import get_settings

    target = _latest_choice(await store.overlays(conn, project_id), "release_target", "target")
    return str(target) if target else get_settings().c4_release_target_default


async def _blocking(conn: AsyncConnection, project: store.Row) -> list[Blocker]:
    """The release guards over what a pending review would approve, or nothing to say.

    Computed only while the review waits: before it there is nothing to approve,
    and after it the release carries the guards itself. The go ahead is not
    assumed here, so a cloud release shows that it needs one.
    """
    gate = await store.pending_gate(conn, project_id=project["id"], kind=GATE_KIND)
    if gate is None:
        return []
    run = await store.get_run(conn, gate["run_id"]) if gate.get("run_id") else None
    facts = await guards.gather(
        conn,
        project["id"],
        owner=project["owner_id"],
        deploy_version=int(gate["requirements_version"]),
        target=await chosen_release_target(conn, project["id"]),
        test_version=int((run or {}).get("source_version") or 0),
    )
    return guards.release_blockers(facts)


def _feedback_decisions(overlay_rows: list[store.Row]) -> list[FeedbackDecisionView]:
    """What a person did with each suggestion from production, oldest first."""
    return [
        FeedbackDecisionView(
            item_id=row["target_id"],
            decision=row["value"]["decision"],
            by=row["by"],
            at=row["at"],
            note=row["value"].get("note") or None,
            deploy_version=row["version"],
            design_version=row["value"].get("designVersion"),
        )
        for row in overlay_rows
        if row["kind"] == "feedback_decision"
    ]


async def prefetch_deployment(conn: AsyncConnection, project_id: str, owner: str) -> None:
    """Ask, in three round trips, what composing this snapshot asks one by one.

    In the order the reads depend on each other: what the project and the
    account settle, then what the versions and the waiting review settle, then
    what the review's run settles. Only a read-only request is answered from
    them; a read the lists miss is asked on its own.
    """
    await store.prefetch(
        conn,
        store.get_project_query(project_id, owner),
        store.current_deploy_version_query(project_id),
        store.stage_states_query(project_id),
        store.thread_query(project_id),
        store.gate_history_query(project_id, GATE_KIND),
        store.overlays_query(project_id),
        store.latest_verified_release_query(project_id),
        store.newest_artefact_query(project_id, "monitoring-report"),
        store.list_deployments_query(project_id),
        store.count_deployments_query(project_id),
        store.newest_artefact_query(project_id, "feedback"),
        store.latest_run_query(project_id, "c4"),
        store.unwatched_releases_query(RECENT_SECONDS),
        store.current_test_version_query(project_id),
        store.gate_history_query(project_id, TEST_GATE_KIND),
        store.current_code_version_query(project_id),
        store.settings_body_query(owner),
        store.pending_gate_query(project_id, GATE_KIND),
        store.latest_full_run_query(project_id, "c4"),
    )
    if not store.remembering(conn):
        return
    deploy_version = await store.current_deploy_version(conn, project_id)
    gate = await store.pending_gate(conn, project_id=project_id, kind=GATE_KIND)
    second = []
    approved = await approved_test_version(conn, project_id)
    if approved:
        second.append(store.run_for_version_query(project_id, "c3", approved))
    if deploy_version:
        second.append(store.artefacts_at_query(project_id, deploy_version, DEPLOY_KINDS))
    if gate is not None:
        second.append(
            store.artefacts_at_query(
                project_id, int(gate["requirements_version"]), guards.FACT_KINDS
            )
        )
        if gate.get("run_id"):
            second.append(store.get_run_query(gate["run_id"]))
    await store.prefetch(conn, *second)
    run = await store.get_run(conn, gate["run_id"]) if gate and gate.get("run_id") else None
    tested = int((run or {}).get("source_version") or 0)
    if tested:
        await store.prefetch(
            conn,
            store.run_for_version_query(project_id, "c3", tested),
            store.version_is_approved_query(project_id, TEST_GATE_KIND, tested),
        )


async def compose_deployment(
    conn: AsyncConnection, project: store.Row, *, watched: frozenset[str] = frozenset()
) -> DeploySnapshot:
    """Read everything for one project's deployment phase and assemble the snapshot."""
    from ..config import get_settings

    project_id = project["id"]
    deploy_version = await store.current_deploy_version(conn, project_id)
    artefacts = (
        await store.artefacts_at(conn, project_id, version=deploy_version, kinds=DEPLOY_KINDS)
        if deploy_version
        else {}
    )
    stage_rows = await store.stage_states(conn, project_id)
    thread_rows = await store.thread(conn, project_id)
    history_rows = await store.gate_history(conn, project_id, kind=GATE_KIND)
    overlay_rows = await store.overlays(conn, project_id)

    def parsed(kind: str, model: Any) -> Any:
        found = artefacts.get(kind)
        return model.model_validate(found["body"]) if found else None

    updates = parsed("dependency-updates", DependencyUpdates)
    risk = parsed("risk-report", RiskReport)
    candidate = parsed("release-candidate", ReleaseCandidate)

    stages: dict[DeployStageId, DeployStageState] = {
        row["stage_id"]: _stage(row) for row in stage_rows if row["stage_id"] in DEPLOY_STAGE_IDS
    }
    for stage_id in DEPLOY_STAGE_IDS:
        stages.setdefault(stage_id, DeployStageState(id=stage_id))

    scope = _latest_choice(overlay_rows, "update_scope", "scope")
    target = _latest_choice(overlay_rows, "release_target", "target")
    policy = _latest_choice(overlay_rows, "release_policy", "policy")
    release = await store.latest_verified_release(conn, project_id)
    # What was learned in production belongs to the release that was watched, which
    # a later analysis run does not change: the newest, whichever version it is at.
    monitored = await store.newest_artefact(conn, project_id, "monitoring-report")
    deployments = await ledger(conn, project_id)
    fed_back = await store.newest_artefact(conn, project_id, "feedback")
    gate = gate_state(history_rows, deploy_version)
    await _runner_at_work(
        conn,
        project_id,
        deploy_version,
        stages,
        gate.decision is not None and gate.decision.kind == "approved",
        deployments,
        watched,
    )

    approved = await approved_test_version(conn, project_id)
    approved_run = (
        await store.run_for_version(conn, project_id, component="c3", version=approved)
        if approved
        else None
    )
    return DeploySnapshot(
        project_id=project_id,
        deploy_version=deploy_version,
        test_version=await store.current_test_version(conn, project_id),
        approved_test_version=approved,
        approved_tested_code_version=int((approved_run or {}).get("source_version") or 0),
        code_version=await store.current_code_version(conn, project_id),
        deployed_code_version=updates.code_version if updates else 0,
        target=str(scope.get("target", "generated")) if isinstance(scope, dict) else "generated",
        scope_packages=[str(one) for one in scope.get("packages") or []]
        if isinstance(scope, dict)
        else [],
        release_target=str(target) if target else get_settings().c4_release_target_default,
        auto_deploy_low=bool(policy.get("autoDeployLow")) if isinstance(policy, dict) else False,
        stages=stages,
        updates=updates,
        changelog=parsed("changelog-report", ChangelogReport),
        impact=parsed("impact-report", ImpactReport),
        risk=risk,
        pipeline=parsed("pipeline-config", PipelineConfig),
        plan=parsed("deploy-plan", DeployPlan),
        candidate=candidate,
        rollback=parsed("rollback-plan", RollbackPlan),
        monitoring=MonitoringReport.model_validate(monitored["body"]) if monitored else None,
        feedback=FeedbackReport.model_validate(fed_back["body"]) if fed_back else None,
        decisions=_decisions(risk, overlay_rows, candidate),
        feedback_decisions=_feedback_decisions(overlay_rows),
        deployments=deployments,
        deployments_total=await store.count_deployments(conn, project_id),
        current_release=verified_release(release) if release else None,
        watching=next((one.id for one in deployments if one.id in watched), None),
        cloud=await cloud_resources_of(conn, project_id, project["owner_id"]),
        blocking=await _blocking(conn, project),
        gate=gate,
        run=await run_status(conn, project_id, component="c4"),
        thread=[
            DeployThreadMessage(
                id=str(row["id"]),
                kind=row["kind"],
                stage_id=row["stage_id"],
                author=row["author"],
                content=row["content"],
                at=row["at"],
            )
            for row in thread_rows
            if row["stage_id"] in DEPLOY_STAGE_IDS
        ],
    )
