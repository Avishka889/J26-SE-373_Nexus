"""The process API: runs, gates, and the audit log.

The architecture the browser does not see. These exist because a run and a gate
are real things with their own lifecycle, and because being able to drive them by
curl is what makes the gate mechanism testable without a UI.

`/activity` is the audit log projected into the shape the activity view reads.
It is a view over the log rather than a fifth phase, so it is not its own table.
"""

import re
import uuid
from typing import Any

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field
from sdlc_contracts import GENERATING_STAGE_IDS

from ..components import QUESTIONS_GATE_KIND, spec_for
from ..db import store
from ..errors import Conflict, NotFound
from ..readmodel.assemble import project_view
from .continuing import continue_run
from .deps import Actor, Db, Owner, Supervisor, require_project

router = APIRouter(tags=["process"])


class StartRun(BaseModel):
    project_id: str = Field(min_length=1, alias="projectId")
    component: str = "c1"


class GateDecisionIn(BaseModel):
    note: str | None = None


def _run_view(row: store.Row) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "projectId": row["project_id"],
        "component": row["component"],
        "requirementsVersion": row["requirements_version"],
        "state": row["state"],
        "startedAt": row["started_at"].isoformat(),
        "finishedAt": row["finished_at"].isoformat() if row["finished_at"] else None,
        "error": row["error"],
        "onlyStage": row.get("only_stage"),
        # What it ran on (0014); null on a run from before, which recorded nothing.
        "model": row.get("model"),
        "thinking": row.get("thinking"),
    }


def _gate_view(row: store.Row) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "runId": str(row["run_id"]),
        "projectId": row["project_id"],
        "kind": row["kind"],
        "requirementsVersion": row["requirements_version"],
        "state": row["state"],
        "payload": row["payload"],
        "decision": row["decision"],
        "decidedBy": row["decided_by"],
        "decidedAt": row["decided_at"].isoformat() if row["decided_at"] else None,
        "note": row["note"],
        "createdAt": row["created_at"].isoformat(),
    }


# ---------------------------------------------------------------------- runs


@router.post("/runs", status_code=status.HTTP_201_CREATED)
async def start_run(
    body: StartRun, conn: Db, owner: Owner, supervisor: Supervisor, actor: Actor
) -> dict[str, Any]:
    if body.component != "c1":
        # This route starts a design run: it opens a design version and marks
        # the design stages as generating. Any other component started here
        # would run on the wrong axis and skip every check its own phase makes
        # before a run, such as a deployment starting without an approved test
        # review. Each later phase starts its runs from its own route.
        raise Conflict(
            f"runs of {body.component} start from their own phase's route, which checks "
            "what that phase requires first; this route starts design runs only"
        )
    project = await require_project(conn, body.project_id, owner)
    if not project["requirement_text"].strip():
        raise Conflict("this project has no requirement text yet, so there is nothing to run")

    # The design axis only: a code run paused at its review is not the design
    # phase being busy. One request at a time asks, so two cannot both start.
    await store.lock_run_axis(conn, body.project_id, "c1")
    existing = await store.active_run(conn, body.project_id, component="c1")
    if existing is not None:
        raise Conflict(f"run {existing['id']} is already in flight for this project")

    version = await store.current_version(conn, body.project_id)
    if version and await store.version_is_approved(
        conn, body.project_id, gate_kind="c1-design-review", version=version
    ):
        # The run would pay for every stage and then be refused at the first
        # write, since an approved version's artefacts are settled.
        raise Conflict(
            f"design version {version} was approved, so it is not generated again in place. "
            "Request a change instead: that opens a new version and asks you to approve it."
        )
    if version == 0:
        version = await store.open_version(conn, body.project_id, note=None, by=actor, applied=True)
    await store.set_stages(
        conn,
        body.project_id,
        list(GENERATING_STAGE_IDS),
        status="generating",
    )
    run = await store.create_run(
        conn, project_id=body.project_id, requirements_version=version, component=body.component
    )
    if supervisor is not None:
        from .projects import _after_commit

        _after_commit(supervisor, run["id"])
    return _run_view(run)


@router.get("/runs")
async def list_runs(
    conn: Db, owner: Owner, project_id: str | None = Query(None, alias="project")
) -> list[dict[str, Any]]:
    return [_run_view(r) for r in await store.list_runs(conn, project_id, owner_id=owner)]


@router.get("/runs/{run_id}")
async def get_run(run_id: uuid.UUID, conn: Db, owner: Owner) -> dict[str, Any]:
    run = await store.get_run(conn, run_id)
    if run is None:
        raise NotFound("run", str(run_id))
    # Another account's run is not found, rather than forbidden: saying it
    # exists would tell a stranger which ids are real.
    await require_project(conn, run["project_id"], owner)
    return _run_view(run)


@router.post("/runs/{run_id}/continue")
async def continue_stopped_run(
    run_id: uuid.UUID, conn: Db, owner: Owner, supervisor: Supervisor, actor: Actor
) -> dict[str, Any]:
    """Go on with a stopped run from where it stopped, and nothing before it."""
    run = await store.get_run(conn, run_id)
    if run is None:
        raise NotFound("run", str(run_id))
    await require_project(conn, run["project_id"], owner)
    spec = spec_for(run["component"])
    await store.lock_run_axis(conn, run["project_id"], spec.key)
    # Read again under the lock: a request that waited for it finds the run
    # the first one queued.
    run = await store.get_run(conn, run_id)
    assert run is not None
    queued = await continue_run(conn, run, spec, by=actor)
    if supervisor is not None:
        from .projects import _after_commit

        _after_commit(supervisor, queued["id"])
    return _run_view(queued)


# --------------------------------------------------------------------- gates


@router.get("/gates")
async def list_gates(
    conn: Db,
    owner: Owner,
    gate_status: str = Query("pending", alias="status"),
    project_id: str | None = Query(None, alias="project"),
) -> list[dict[str, Any]]:
    if gate_status != "pending":
        raise Conflict("only pending gates are listed; resolved ones are in the audit log")
    rows = await store.pending_gates(conn, owner_id=owner, project_id=project_id)
    return [_gate_view(g) for g in rows]


@router.post("/gates/{gate_id}/approve")
async def approve_gate(
    gate_id: uuid.UUID,
    body: GateDecisionIn,
    conn: Db,
    owner: Owner,
    supervisor: Supervisor,
    actor: Actor,
) -> dict[str, Any]:
    """Approve, and resume the same thread the gate paused."""
    from .design import _resolve

    gate = await store.pending_gate(conn, gate_id=gate_id)
    if gate is None:
        raise NotFound("pending gate", str(gate_id))
    # Only the review's own account decides it: any account could approve any.
    await require_project(conn, gate["project_id"], owner)
    await _resolve(conn, gate, kind="approved", by=actor, note=body.note, supervisor=supervisor)
    refreshed = await store.pending_gate(conn, gate_id=gate_id)
    return {"ok": True, "resolved": refreshed is None, "runId": str(gate["run_id"])}


@router.post("/gates/{gate_id}/request-changes")
async def request_changes(
    gate_id: uuid.UUID,
    body: GateDecisionIn,
    conn: Db,
    owner: Owner,
    supervisor: Supervisor,
    actor: Actor,
) -> dict[str, Any]:
    from .design import _resolve

    if not (body.note or "").strip():
        raise Conflict("requesting changes needs a note saying what to change")
    gate = await store.pending_gate(conn, gate_id=gate_id)
    if gate is None:
        raise NotFound("pending gate", str(gate_id))
    await require_project(conn, gate["project_id"], owner)
    await _resolve(conn, gate, kind="changes", by=actor, note=body.note, supervisor=supervisor)
    return {"ok": True, "runId": str(gate["run_id"])}


# ----------------------------------------------------------------- attention

#: The phase each review belongs to, and the words a reader knows it by.
_REVIEW_PHASE = {
    "c1-design-review": ("design", "Design Review"),
    # Not a review: the design waits on its questions before building the rest.
    QUESTIONS_GATE_KIND: ("design", "Questions"),
    "c2-code-review": ("code", "Code Review"),
    "c3-test-review": ("testing", "Test Review"),
    "c4-deploy-review": ("deployment", "Deployment Review"),
}
#: The phase a project's status names, and what its run is called there.
_STATUS_PHASE = {
    "draft": ("design", "design"),
    "analyzing": ("design", "design"),
    "design": ("design", "design"),
    "code": ("code", "code generation"),
    "testing": ("testing", "testing"),
    "deploy": ("deployment", "deployment"),
}


@router.get("/attention")
async def attention(conn: Db, owner: Owner) -> list[dict[str, Any]]:
    """Everything waiting on this account: rollbacks, reviews, then stopped runs.

    The bell said "Nothing needs you right now" while thirty seven reviews
    waited: its invented demo lines were removed and nothing real replaced
    them. A release that stopped serving comes first, then the reviews, the
    longest waiting first, then the runs that stopped in the phase a project
    is in. Each names its project and phase, so the bell can open the page.
    """
    await store.prefetch(
        conn,
        store.list_projects_query(owner),
        store.waiting_rollbacks_query(owner),
        store.pending_gates_query(owner),
        *store.project_progress_queries(owner),
    )
    names = {row["id"]: row["name"] for row in await store.list_projects(conn, owner_id=owner)}
    items: list[dict[str, Any]] = []
    for row in await store.waiting_rollbacks(conn, owner_id=owner):
        items.append(
            {
                "id": f"rollback:{row['id']}",
                "kind": "rollback",
                "projectId": row["project_id"],
                "projectName": names.get(row["project_id"], ""),
                "phase": "deployment",
                "title": "A rollback waits for your decision",
                "message": f"Deploy version {row['deploy_version']} stopped serving what was "
                "released.",
                "at": row["created_at"].isoformat(),
            }
        )
    for gate in await store.pending_gates(conn, owner_id=owner):
        phase, review = _REVIEW_PHASE.get(gate["kind"], ("design", "Review"))
        items.append(
            {
                "id": f"review:{gate['id']}",
                "kind": "review",
                "projectId": gate["project_id"],
                "projectName": names.get(gate["project_id"], ""),
                "phase": phase,
                "title": f"{review} waiting",
                "message": (
                    f"Version {gate['requirements_version']}: the design waits on your "
                    "answers to its questions."
                    if gate["kind"] == QUESTIONS_GATE_KIND
                    else f"Version {gate['requirements_version']} waits on your review."
                ),
                "at": gate["created_at"].isoformat(),
            }
        )
    for project_id, facts in (await store.project_progress(conn, owner_id=owner)).items():
        view = project_view(facts)
        if not view["runStopped"]:
            continue
        phase, run = _STATUS_PHASE.get(view["status"], ("design", "design"))
        items.append(
            {
                "id": f"stopped:{project_id}:{phase}",
                "kind": "stopped",
                "projectId": project_id,
                "projectName": names.get(project_id, ""),
                "phase": phase,
                "title": "A run stopped",
                "message": f"The {run} run stopped before it finished.",
                "at": None,
            }
        )
    return items


# --------------------------------------------------------------------- audit


@router.get("/audit")
async def audit(
    conn: Db,
    owner: Owner,
    project_id: str | None = Query(None, alias="project"),
    limit: int = Query(200, ge=1, le=1000),
) -> list[dict[str, Any]]:
    # The signed-in owner's entries only, and a project named here must be
    # theirs: with more than one account this listed every account's events.
    if project_id is not None:
        await require_project(conn, project_id, owner)
    rows = await store.audit_trail(conn, owner_id=owner, project_id=project_id, limit=limit)
    return [
        {
            "id": str(row["id"]),
            "at": row["at"].isoformat(),
            "projectId": row["project_id"],
            "runId": str(row["run_id"]) if row["run_id"] else None,
            "actor": row["actor"],
            "action": row["action"],
            "target": row["target"],
            "category": row["category"],
            "detail": row["detail"],
        }
        for row in rows
    ]


#: What an action's words say it was. Read from the words because the audit log
#: records actions as sentences, and the categories say which phase, not how it went.
_FAILED = re.compile(r"\b(failed|abandoned|retired|stopped)\b", re.IGNORECASE)
_CHANGES = re.compile(r"\brequested\b.*\bchanges?\b|\bqueued the change\b", re.IGNORECASE)
_DONE = re.compile(
    r"^(approved|re-verified|released|restored|applied)\b|\bverified\b", re.IGNORECASE
)


def outcome_of(action: str) -> str:
    """failed, changes, done or info: how the event went, for its mark in the timeline.

    The timeline read success off the category, so a change request at a
    review and a failed run drew the green check.
    """
    if _FAILED.search(action):
        return "failed"
    if _CHANGES.search(action):
        return "changes"
    if _DONE.search(action):
        return "done"
    return "info"


@router.get("/activity")
async def activity(
    conn: Db,
    owner: Owner,
    project: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
) -> list[dict[str, Any]]:
    """The audit log in the shape the activity view reads.

    With `project`, that project's events only, and only for its owner: the
    view sits under one project, and it listed every project's events.
    """
    if project is not None:
        await require_project(conn, project, owner)
    rows = await store.audit_trail(conn, owner_id=owner, project_id=project, limit=limit)
    return [
        {
            "id": str(row["id"]),
            "timestamp": row["at"].isoformat(timespec="seconds"),
            "title": row["action"],
            "description": row["detail"] or row["target"],
            "actor": row["actor"],
            "category": row["category"],
            "outcome": outcome_of(row["action"]),
            "artifactRef": row["target"],
        }
        for row in rows
    ]
