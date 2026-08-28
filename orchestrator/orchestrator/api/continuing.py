"""Going on with a stopped run, from where it stopped.

The way past a run that stopped was to start over, which generated every stage
again and paid again for every one that had finished. LangGraph saves a run's
progress at every step, so continuing re-runs the stage that broke and what
follows it, and nothing before. Only a person continues a run: the poller never
does, because a run restarted on its own is how an approved design was once
regenerated in place.
"""

from typing import Any

from ..components import ComponentSpec, where_it_stopped
from ..db import store
from ..errors import Conflict

#: Each phase's own version axis, which a newer version moves on from.
_CURRENT_VERSION = {
    "c1": store.current_version,
    "c2": store.current_code_version,
    "c3": store.current_test_version,
    "c4": store.current_deploy_version,
}


async def refusal(conn: Any, run: store.Row, spec: ComponentSpec) -> str | None:
    """Why this run may not go on, or None when it may.

    The caller holds the phase's run lock, so nothing starts between this
    answer and the continue.
    """
    project_id = run["project_id"]
    if run["only_stage"]:
        return "a stage retry is not continued; try the stage again instead"
    if run["state"] != "failed":
        return "this run did not stop, so there is nothing to continue"
    newest = await store.latest_full_run(conn, project_id, component=spec.key)
    if newest is None or str(newest["id"]) != str(run["id"]):
        return "a newer run replaced this one, so it is not continued; that run is the way on"
    if await store.active_run(conn, project_id, component=spec.key) is not None:
        return "another run is working on this phase; wait for it to finish"
    version = int(run["requirements_version"])
    if await store.version_is_approved(conn, project_id, gate_kind=spec.gate_kind, version=version):
        return f"version {version} was approved, so it is settled and not continued"
    current = await _CURRENT_VERSION[spec.key](conn, project_id)
    if current > version:
        return (
            f"this phase has moved on to version {current}, so version {version} is not continued"
        )
    return None


async def continue_run(conn: Any, run: store.Row, spec: ComponentSpec, *, by: str) -> store.Row:
    """Queue the run to go on from where it stopped, and say so.

    The stage that stopped it and the stages it never reached are generating
    again; a leaf that failed earlier is left as it is, because the run already
    went past it and continuing does not redo it.
    """
    reason = await refusal(conn, run, spec)
    if reason is not None:
        raise Conflict(reason)
    project_id = run["project_id"]
    statuses = {
        row["stage_id"]: row["status"] for row in await store.stage_states(conn, project_id)
    }
    pending = [stage for stage in spec.stage_ids if statuses.get(stage, "pending") == "pending"]
    stopped = where_it_stopped(spec, statuses, pending)
    queued = await store.requeue_to_continue(conn, run["id"])
    if queued is None:
        raise Conflict("this run is already going on from where it stopped")
    await store.set_stages(
        conn,
        project_id,
        [stage for stage in spec.generating_stage_ids if stage in pending or stage == stopped],
        status="generating",
    )
    await store.record(
        conn,
        actor=by,
        action="Continued a stopped run",
        target=str(run["id"]),
        detail=f"From {stopped}, at version {run['requirements_version']}.",
        project_id=project_id,
        run_id=run["id"],
    )
    await store.post_thread_message(
        conn,
        project_id,
        kind="system",
        author=by,
        content="Continued the run from where it stopped.",
        stage_id=stopped,  # type: ignore[arg-type]
    )
    return queued


async def continue_if_stopped_here(
    conn: Any, project_id: str, spec: ComponentSpec, stage_id: str, *, by: str
) -> store.Row | None:
    """Continue the phase's stopped run when Try again is on the stage that stopped it.

    Try again there regenerated that one stage and stopped, so the review still
    never came. On any other stage it is still the one-stage retry, which is
    what a leaf that failed before the stop needs: the run went past it.
    """
    run = await store.latest_full_run(conn, project_id, component=spec.key)
    if run is None or await refusal(conn, run, spec) is not None:
        return None
    statuses = {
        row["stage_id"]: row["status"] for row in await store.stage_states(conn, project_id)
    }
    if statuses.get(stage_id) != "failed":
        return None
    pending = [stage for stage in spec.stage_ids if statuses.get(stage, "pending") == "pending"]
    if where_it_stopped(spec, statuses, pending) != stage_id:
        return None
    return await continue_run(conn, run, spec, by=by)
