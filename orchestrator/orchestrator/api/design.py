"""The design read model, and the decision that resolves the gate.

These are the routes the browser already calls. They are a facade over the same
state the process API exposes: `POST /design/decision` resolves the pending gate
on this project's current run, which is the same act as `POST /gates/{id}/approve`
reached from a different direction.

Every route answers with a whole snapshot, which is what lets the client write
one response into its cache and never re-derive partial state.
"""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sdlc_contracts import (
    ARTEFACT_STAGE_IDS,
    DESIGN_STAGE_IDS,
    GENERATING_STAGE_IDS,
    DesignSnapshot,
)

from ..components import QUESTIONS_GATE_KIND, spec_for
from ..db import store
from ..errors import Conflict, NotFound
from ..readmodel.assemble import compose, prefetch_design
from ..wording import stage_label
from .continuing import continue_if_stopped_here
from .deps import Actor, Db, Owner, Supervisor, require_project

router = APIRouter(tags=["design"])


class TextIn(BaseModel):
    text: str = Field(min_length=1)


class AssumptionPatch(BaseModel):
    """Two operations share one route, told apart by which field is present."""

    text: str | None = None
    dismissed: bool | None = None


class AnswerIn(BaseModel):
    answer: str = Field(min_length=1)


class SelectIn(BaseModel):
    candidate_id: str = Field(min_length=1, alias="candidateId")


class LabelIn(BaseModel):
    label: str = Field(min_length=1)


class NoteIn(BaseModel):
    note: str = Field(min_length=1)


class ChangeIn(BaseModel):
    note: str = Field(min_length=1)


class DecisionIn(BaseModel):
    kind: str = Field(pattern="^(approved|changes)$")
    note: str | None = None


class ContinueIn(BaseModel):
    """How the design goes on from its questions: with the answers, or the assumptions."""

    kind: str = Field(pattern="^(answers|assumptions)$")


async def _snapshot(conn: Any, project_id: str, owner: str) -> DesignSnapshot:
    """The phase as the request leaves it, read in a few round trips.

    Called last: whatever the request wrote is written, so from here it only
    reads, and its reads can share round trips and be asked once.
    """
    async with store.reads_only(conn):
        await prefetch_design(conn, project_id, owner)
        return await compose(conn, await require_project(conn, project_id, owner))


@router.get("/projects/{project_id}/design")
async def get_design(project_id: str, conn: Db, owner: Owner) -> DesignSnapshot:
    return await _snapshot(conn, project_id, owner)


@router.patch("/projects/{project_id}/design/requirements/{requirement_id}")
async def edit_requirement(
    project_id: str, requirement_id: str, body: TextIn, conn: Db, owner: Owner, actor: Actor
) -> DesignSnapshot:
    """Correct a requirement without regenerating anything.

    Stored as an overlay, so the text the machine produced survives underneath.
    Only a change note rebuilds the design, and the UI says so where the edit
    happens. Code Generation reads the corrected text.
    """
    await require_project(conn, project_id, owner)
    version = await _editable(conn, project_id, "requirements")
    await store.put_overlay(
        conn,
        project_id=project_id,
        version=version,
        kind="requirement_text",
        target_id=requirement_id,
        value=body.text,
        by=actor,
    )
    await store.record(
        conn,
        actor=actor,
        action="Corrected a requirement",
        target=requirement_id,
        detail="Marked as adjusted. The design was not regenerated.",
        project_id=project_id,
    )
    return await _snapshot(conn, project_id, owner)


@router.patch("/projects/{project_id}/design/assumptions/{assumption_id}")
async def patch_assumption(
    project_id: str, assumption_id: str, body: AssumptionPatch, conn: Db, owner: Owner, actor: Actor
) -> DesignSnapshot:
    await require_project(conn, project_id, owner)
    version = await _editable(conn, project_id, "requirements")
    if body.text is not None:
        await store.put_overlay(
            conn,
            project_id=project_id,
            version=version,
            kind="assumption_text",
            target_id=assumption_id,
            value=body.text,
            by=actor,
        )
    if body.dismissed is not None:
        await store.put_overlay(
            conn,
            project_id=project_id,
            version=version,
            kind="assumption_dismissed",
            target_id=assumption_id,
            value=body.dismissed,
            by=actor,
        )
    return await _snapshot(conn, project_id, owner)


async def _refuse_once_approved(conn: Any, project_id: str, version: int) -> None:
    if await store.version_is_approved(
        conn, project_id, gate_kind="c1-design-review", version=version
    ):
        raise Conflict(
            f"Requirements version {version} is approved, so its record stays as it was "
            "approved. Send the change as a change note: it opens a new version."
        )


async def _editable(conn: Any, project_id: str, kind: str) -> int:
    """The version of the shown artefact an edit is kept against, refused once approved.

    An edit was kept against whatever version was newest and accepted after the
    approval, silently rewriting the approved record; and kept against a newer
    version than the one on screen, it applied to that version's different text.
    """
    found = (await store.latest_artefacts(conn, project_id)).get(kind)
    if found is None:
        raise Conflict(f"there is no {stage_label(kind)} to change yet")
    await _refuse_once_approved(conn, project_id, found["version"])
    return int(found["version"])


@router.post("/projects/{project_id}/design/questions/{question_id}/answer")
async def answer_question(
    project_id: str,
    question_id: str,
    body: AnswerIn,
    conn: Db,
    owner: Owner,
    supervisor: Supervisor,
    actor: Actor,
) -> DesignSnapshot:
    """Record an answer, against the version of the questions it answers.

    Recorded and nothing more: answers reach the design when the reader applies
    them (`POST .../design/answers/apply`). The last answer used to apply them
    all at once, which regenerated the whole design, a model run, with no word
    beforehand and a "Requested changes" in the record the reader never asked
    for, while the page said to answer before deciding.

    The answer is kept at the version the questions were asked in, so a
    regenerated design's new questions do not arrive answered with old answers.
    """
    await require_project(conn, project_id, owner)
    artefacts = await store.latest_artefacts(conn, project_id)
    asked = artefacts.get("requirements")
    if asked is None or not any(
        question.get("id") == question_id for question in asked["body"].get("questions", [])
    ):
        raise NotFound("question", question_id)
    await store.put_overlay(
        conn,
        project_id=project_id,
        version=asked["version"],
        kind="question_answer",
        target_id=question_id,
        value=body.answer,
        by=actor,
    )
    # An answer belongs in the thread too: that is where the conversation about
    # these requirements lives.
    await store.post_thread_message(
        conn,
        project_id,
        kind="answer",
        author=actor,
        content=body.answer,
        stage_id="requirements",
    )
    return await _snapshot(conn, project_id, owner)


@router.post("/projects/{project_id}/design/answers/apply")
async def apply_answers(
    project_id: str, conn: Db, owner: Owner, supervisor: Supervisor, actor: Actor
) -> DesignSnapshot:
    """Regenerate the design with the answers given, when the reader asks for it.

    One change for every answer, so three answers cost one run. At a pending
    review it is the review's "request changes", recorded with the answers as
    its note; otherwise a change note like any other.
    """
    project = await require_project(conn, project_id, owner)
    if not any(question.answer for question in (await compose(conn, project)).questions):
        raise Conflict("there are no answers to apply: answer a question first")
    queued_run = await _apply_answers(conn, project_id, supervisor, by=actor)
    snapshot = await _snapshot(conn, project_id, owner)
    if queued_run is not None and supervisor is not None:
        from .projects import _after_commit

        _after_commit(supervisor, queued_run["id"])
    return snapshot


async def _apply_answers(
    conn: Any, project_id: str, supervisor: Any, *, by: str
) -> dict[str, Any] | None:
    """Every answered question as one change note, which the design regenerates from.

    At the design review this is the review's own "request changes", because a
    note that arrives while a decision is pending only queues until the decision
    lands, and answering is not a decision about the design. While the run is
    paused on the questions it is continuing with the answers. Elsewhere it is a
    change note like any other. Returns the run a change note started, which the
    caller hands to the supervisor once its transaction has committed.
    """
    if await store.pending_gate(conn, project_id=project_id, kind=QUESTIONS_GATE_KIND):
        # Paused for them, the run goes on with them: no second run, and no
        # review decision, since the review has not been reached.
        await _continue_from_questions(
            conn, project_id, kind="answers", by=by, supervisor=supervisor
        )
        return None
    note = await _answers_note(conn, project_id)
    if note is None:
        return None
    await store.post_thread_message(
        conn,
        project_id,
        kind="system",
        author="Design agent",
        content="The design is regenerating with your answers.",
        stage_id="requirements",
    )
    gate = await store.pending_gate(conn, project_id=project_id, kind="c1-design-review")
    if gate is not None:
        await _resolve(conn, gate, kind="changes", by=by, note=note, supervisor=supervisor)
        return None
    _, queued_run = await request_design_change(conn, project_id, note=note, by=by)
    return queued_run


async def _answers_note(conn: Any, project_id: str) -> str | None:
    """Every answered question as one note the requirements are analysed with, or None."""
    project = await store.project_without_owner_check(conn, project_id)
    if project is None:
        return None
    answered = [
        question for question in (await compose(conn, project)).questions if question.answer
    ]
    if not answered:
        return None
    return "Answers to the design's questions:\n" + "\n".join(
        f"- {question.question} {question.answer}" for question in answered
    )


@router.post("/projects/{project_id}/design/questions/continue")
async def continue_from_questions(
    project_id: str,
    body: ContinueIn,
    conn: Db,
    owner: Owner,
    supervisor: Supervisor,
    actor: Actor,
) -> DesignSnapshot:
    """Go on from the design's questions, with the answers or with the assumptions.

    The run paused after Requirements Analysis because it asked them. With the
    answers, the requirements are analysed again with them, and with any note
    written while it waited; with the assumptions, the rest is built on what
    the analysis assumed, and the questions stay open to answer at the review.
    """
    await require_project(conn, project_id, owner)
    await _continue_from_questions(
        conn, project_id, kind=body.kind, by=actor, supervisor=supervisor
    )
    return await _snapshot(conn, project_id, owner)


async def _continue_from_questions(
    conn: Any, project_id: str, *, kind: str, by: str, supervisor: Any
) -> None:
    """Record how the design goes on from its questions, and hand the run back.

    Not a review, so it is not `_resolve`: nothing is approved and no change is
    requested. "changes" carries the answers at a version the store allocates,
    which claims the notes written during the pause too; "approved" builds the
    rest at the version the questions were asked in.
    """
    gate = await store.pending_gate(conn, project_id=project_id, kind=QUESTIONS_GATE_KIND)
    if gate is None:
        raise Conflict("the design is not waiting on its questions")
    note = None
    if kind == "answers":
        note = await _answers_note(conn, project_id)
        if note is None and not await store.queued_notes(conn, project_id):
            raise Conflict(
                "answer a question first, or write a note, or continue with the assumptions"
            )
    resolved = await store.resolve_gate(
        conn,
        gate["id"],
        decision="changes" if kind == "answers" else "approved",
        by=by,
        note=note,  # type: ignore[arg-type]
    )
    if resolved is None:
        raise Conflict("that decision was already recorded")

    version = int(gate["requirements_version"])
    resume: dict[str, Any] = {"kind": "approved" if kind == "assumptions" else "changes"}
    if kind == "answers":
        version, notes = await store.claim_next_version(conn, project_id, note=note, by=by)
        resume |= {"version": version, "notes": notes}
        await store.set_run_version(conn, gate["run_id"], version)
        await store.set_stages(conn, project_id, list(GENERATING_STAGE_IDS), status="generating")
    else:
        await store.set_stages(
            conn,
            project_id,
            [stage for stage in GENERATING_STAGE_IDS if stage != "requirements"],
            status="generating",
        )
    await store.post_thread_message(
        conn,
        project_id,
        kind="system",
        author=by,
        content=(
            "Continued with the answers: the requirements are analysed again with them."
            if kind == "answers"
            else "Continued with the assumptions: the rest of the design is built on them."
        ),
        stage_id="requirements",
    )
    await store.record(
        conn,
        actor=by,
        action=(
            "Continued with the answers" if kind == "answers" else "Continued with the assumptions"
        ),
        target=f"version {version}",
        detail=(note or "")[:500],
        project_id=project_id,
        run_id=gate["run_id"],
    )
    await store.set_run_state(conn, gate["run_id"], "queued", resume_payload=resume)
    if supervisor is not None:
        from .projects import _after_commit

        _after_commit(supervisor, gate["run_id"])


@router.post("/projects/{project_id}/design/architecture/select")
async def select_architecture(
    project_id: str, body: SelectIn, conn: Db, owner: Owner, actor: Actor
) -> DesignSnapshot:
    await require_project(conn, project_id, owner)
    version = await store.current_version(conn, project_id)
    await _refuse_once_approved(conn, project_id, version)
    await store.put_overlay(
        conn,
        project_id=project_id,
        version=version,
        kind="architecture_selection",
        target_id="selection",
        value=body.candidate_id,
        by=actor,
    )
    await store.record(
        conn,
        actor=actor,
        action="Selected an architecture",
        target=body.candidate_id,
        detail="Recorded against the current requirements version.",
        project_id=project_id,
    )
    return await _snapshot(conn, project_id, owner)


@router.patch("/projects/{project_id}/design/graph/nodes/{node_id}")
async def rename_node(
    project_id: str, node_id: str, body: LabelIn, conn: Db, owner: Owner, actor: Actor
) -> DesignSnapshot:
    """Rename a graph node.

    The domain model and the diagrams are projections over this graph, so they
    follow on their own, and Code Generation reads the renamed graph.
    """
    await require_project(conn, project_id, owner)
    version = await _editable(conn, project_id, "architecture-graph")
    await store.put_overlay(
        conn,
        project_id=project_id,
        version=version,
        kind="node_label",
        target_id=node_id,
        value=body.label,
        by=actor,
    )
    return await _snapshot(conn, project_id, owner)


@router.post("/projects/{project_id}/design/wireframes/{flow_id}/refine")
async def refine_flow(
    project_id: str,
    flow_id: str,
    body: NoteIn,
    conn: Db,
    owner: Owner,
    supervisor: Supervisor,
    actor: Actor,
) -> DesignSnapshot:
    """Ask for a flow to be drawn differently: a change to the design like any other.

    It was kept beside the flow and read by nothing, while the page promised the
    flow would be redrawn. Now it is a change note naming the flow, which opens a
    version and regenerates the design (or waits for the review's decision).
    """
    await require_project(conn, project_id, owner)
    artefacts = await store.latest_artefacts(conn, project_id)
    flows = (artefacts.get("wireframes") or {}).get("body", {}).get("flows", [])
    flow = next((one for one in flows if one.get("id") == flow_id), None)
    if flow is None:
        raise NotFound("flow", flow_id)
    note = f"Refine the {flow.get('name') or flow_id} flow: {body.note}"
    _, queued_run = await request_design_change(conn, project_id, note=note, by=actor)
    snapshot = await _snapshot(conn, project_id, owner)
    if queued_run is not None and supervisor is not None:
        from .projects import _after_commit

        _after_commit(supervisor, queued_run["id"])
    return snapshot


@router.post("/projects/{project_id}/design/stages/{stage_id}/retry")
async def retry_stage(
    project_id: str,
    stage_id: str,
    conn: Db,
    owner: Owner,
    supervisor: Supervisor,
    actor: Actor,
) -> DesignSnapshot:
    if stage_id not in DESIGN_STAGE_IDS:
        raise NotFound("stage", stage_id)
    if stage_id not in spec_for("c1").stage_nodes():
        # A projection has no node to rerun. Before this check, retrying one
        # answered 200, then the runner failed the run with "not a stage a
        # component produces" and the row it had flipped to generating was
        # stranded there for good.
        raise Conflict(
            f"{stage_id} is a projection over other artefacts; there is nothing "
            "to regenerate. Retry the stage that produces what it reads."
        )
    await require_project(conn, project_id, owner)
    version = await store.current_version(conn, project_id)
    if await store.version_is_approved(
        conn, project_id, gate_kind="c1-design-review", version=version
    ):
        # A retry rewrites one artefact at the current version. Once that
        # version carries an approval, rewriting it means the record says a
        # reader approved something that is no longer there.
        #
        # The refusal belongs here rather than at the write. `put_artefact`
        # also refuses, and must, because it is the last line before the row;
        # but by then the node has already called the model, so the reader
        # would pay for a regeneration and then be told it could not be kept.
        raise Conflict(
            f"version {version} was approved, so {stage_id} cannot be regenerated in place. "
            "Request a change instead: that opens a new version, regenerates what the change "
            "touches, and asks you to approve the result."
        )
    # A stage may be retried while the review waits, but not while a run is
    # working: a second click started a second run of the stage, paying for
    # its model calls twice.
    await store.lock_run_axis(conn, project_id, "c1")
    # Try again on the stage that stopped the phase's run goes on with that
    # run, to the review, rather than regenerating the one stage and stopping.
    continued = await continue_if_stopped_here(conn, project_id, spec_for("c1"), stage_id, by=actor)
    if continued is not None:
        if supervisor is not None:
            from .projects import _after_commit

            _after_commit(supervisor, continued["id"])
        return await _snapshot(conn, project_id, owner)
    if await store.active_run(conn, project_id, component="c1", states=store.WORKING_RUN_STATES):
        raise Conflict(
            "a design run is already working on this project; wait for it to finish "
            "before retrying a stage"
        )
    await store.set_stage(conn, project_id, stage_id, status="generating")  # type: ignore[arg-type]
    # Narrowed to this one stage. A full run would walk every node and rewrite
    # five artefacts the reader has already read, to fix the one they asked
    # about, and it would cost six model calls to do it.
    run = await store.create_run(
        conn, project_id=project_id, requirements_version=version, only_stage=stage_id
    )
    if supervisor is not None:
        from .projects import _after_commit

        _after_commit(supervisor, run["id"])
    return await _snapshot(conn, project_id, owner)


async def request_design_change(
    conn: Any, project_id: str, *, note: str, by: str
) -> tuple[int, dict[str, Any] | None]:
    """Open a design version carrying a change note, and start or queue its run.

    The one path a change note takes into the design phase, whoever wrote it: a
    person at the design review, or a feedback item a person sent from
    production (M5). C1's input at a version is the requirement text plus every
    applied note up to it, so a note opened here is in the next run's input.
    Returns the version and the run it started, which is None when the note
    queued behind a run in flight. The caller hands that run to the supervisor
    once its transaction has committed.
    """
    # This component's runs only. A code run paused at its own gate is not the
    # design phase being busy: the two axes are separate threads, and the code
    # snapshot reports the design version it generated from, so a design that
    # moves on says so rather than being blocked.
    # Any run on the axis, not the newest: a stage retry is a run of its own that
    # finishes in a moment, and asking only the newest missed a full run still
    # paused at its review beneath it, so a second full run started beside it.
    # awaiting_gate is in flight too: its run is paused on a thread that a
    # second run would collide with at the gate index. A note that arrives
    # while a decision is pending queues, and drains when the decision lands.
    await store.lock_run_axis(conn, project_id, "c1")
    in_flight = await store.active_run(conn, project_id, component="c1") is not None
    if not in_flight:
        # A note queued behind a run that then stopped is this version's too.
        await store.claim_queued(conn, project_id)

    version = await store.open_version(conn, project_id, note=note, by=by, applied=not in_flight)
    await store.post_thread_message(
        conn,
        project_id,
        kind="user_note",
        author=by,
        content=note,
        stage_id="requirements",
    )
    await store.record(
        conn,
        actor=by,
        action="Requested a change",
        target=f"version {version}",
        detail=note[:500],
        project_id=project_id,
    )

    queued_run = None
    if in_flight:
        # Waits for the loop point. The run that is going will pick it up.
        await store.record(
            conn,
            actor="system",
            action="Queued the change",
            target=f"version {version}",
            detail="A run is already in flight, so the note waits rather than racing it.",
            project_id=project_id,
        )
    else:
        # Everything downstream of requirements analysis regenerates. Which
        # stages a wording change really affects is not knowable without a
        # dependency graph we do not have, so nothing pretends otherwise.
        await store.set_stages(
            conn,
            project_id,
            list(ARTEFACT_STAGE_IDS),
            status="generating",
        )
        queued_run = await store.create_run(
            conn, project_id=project_id, requirements_version=version
        )
    return version, queued_run


@router.post("/projects/{project_id}/design/changes")
async def submit_change(
    project_id: str, body: ChangeIn, conn: Db, owner: Owner, supervisor: Supervisor, actor: Actor
) -> DesignSnapshot:
    """Add a change, which bumps the requirements version.

    Returns immediately with the later stages marked generating; the work happens
    in the background. If a run is already in flight the note is queued rather
    than started, because two graphs must never run on one thread id.
    """
    await require_project(conn, project_id, owner)
    _, queued_run = await request_design_change(conn, project_id, note=body.note, by=actor)
    snapshot = await _snapshot(conn, project_id, owner)
    if queued_run is not None and supervisor is not None:
        from .projects import _after_commit

        _after_commit(supervisor, queued_run["id"])
    return snapshot


@router.post("/projects/{project_id}/design/decision")
async def submit_decision(
    project_id: str, body: DecisionIn, conn: Db, owner: Owner, supervisor: Supervisor, actor: Actor
) -> DesignSnapshot:
    """The phase gate, reached from the browser.

    Resolves the pending gate on this project's current run. The same act is
    available as `POST /gates/{id}/approve`; this is the read model's door to it.
    """
    await require_project(conn, project_id, owner)
    gate = await store.pending_gate(conn, project_id=project_id, kind="c1-design-review")
    if gate is None:
        raise Conflict("there is no decision waiting on this project")
    if body.kind == "changes" and not (body.note or "").strip():
        raise Conflict("requesting changes needs a note saying what to change")
    if body.kind == "approved":
        # Refused whatever the note says: no note gives Code Generation a
        # sprint plan to build from.
        blocker = await _unbuildable(conn, project_id, int(gate["requirements_version"]))
        if blocker is not None:
            raise Conflict(blocker)
    if body.kind == "approved" and not (body.note or "").strip():
        concerns = _approval_concerns(await _snapshot(conn, project_id, owner))
        if concerns:
            raise Conflict(
                f"Approving with {' and '.join(concerns)} needs a note saying why it is "
                "right to approve as it is."
            )

    await _resolve(conn, gate, kind=body.kind, by=actor, note=body.note, supervisor=supervisor)
    return await _snapshot(conn, project_id, owner)


#: What Code Generation cannot build without, by the stage that writes it. It
#: reads the wireframes when they are there and builds without them, so failed
#: Wireframes stay a concern a note answers ("drawn by hand this sprint").
_CODE_BUILDS_FROM = ("sprint-plan",)


async def _unbuildable(conn: Any, project_id: str, version: int) -> str | None:
    """Why approving this design version would leave Code Generation stuck, or None.

    Approving over a failed stage needs a note, and a failed Sprint Planning was
    approved with one: Code Generation then failed with "no sprint plan at the
    design version this run pinned", and the only way on was to request changes.
    A stage still generating is refused for the same reason: its artefact is
    not there yet.
    """
    generating = [
        stage_label(row["stage_id"])
        for row in await store.stage_states(conn, project_id)
        if row["stage_id"] in DESIGN_STAGE_IDS and row["status"] == "generating"
    ]
    if generating:
        many = len(generating) != 1
        return (
            f"{' and '.join(generating)} {'are' if many else 'is'} still generating, so there is "
            f"nothing settled to approve yet. Approve once {'they finish' if many else 'it finishes'}"
        )
    found = await store.artefacts_at(conn, project_id, version=version, kinds=_CODE_BUILDS_FROM)
    missing = [stage_label(kind) for kind in _CODE_BUILDS_FROM if kind not in found]
    if missing:
        many = len(missing) != 1
        return (
            f"design version {version} has no {' and no '.join(missing)}, which Code Generation "
            f"builds from, so approving it would leave nothing to build. Try "
            f"{'those stages' if many else 'that stage'} again first"
        )
    return None


def _approval_concerns(snapshot: DesignSnapshot) -> list[str]:
    """What failed or is still open, which approving over needs a note for.

    Approving was one click whatever had failed: eighteen live projects sat at
    an open design review with a failed stage. The page says the same before it
    sends the approval (`requirements/model/gate.ts`), with the stages named.
    """
    failed = sum(1 for state in snapshot.stages.values() if state.status == "failed")
    errors = sum(1 for finding in snapshot.consistency if finding.severity == "error")
    # Answering records an answer; only applying it reaches the design and the
    # code. An approval with answers given and never applied lost them: the bar
    # read "every question answered", and nothing downstream ever saw them.
    unapplied = sum(1 for question in snapshot.questions if question.answer)
    concerns = []
    if failed:
        concerns.append(f"{failed} failed {'stage' if failed == 1 else 'stages'}")
    if errors:
        concerns.append(f"{errors} consistency {'error' if errors == 1 else 'errors'}")
    if unapplied:
        concerns.append(
            f"{unapplied} {'answer' if unapplied == 1 else 'answers'} given and not applied "
            "to the design"
        )
    return concerns


async def _open_findings(conn: Any, project_id: str) -> str:
    """The cross artefact findings still open, in one phrase, or nothing.

    Composed rather than counted from a column, for the reason every derived
    field here is: a stored count is a number that starts disagreeing with what
    it describes.
    """
    project = await store.project_without_owner_check(conn, project_id)
    if project is None:
        return ""
    snapshot = await compose(conn, project)
    errors = [f for f in snapshot.consistency if f.severity == "error"]
    warnings = [f for f in snapshot.consistency if f.severity == "warning"]
    if not errors and not warnings:
        return "No consistency findings were open."
    parts = []
    if errors:
        parts.append(f"{len(errors)} consistency {'error' if len(errors) == 1 else 'errors'}")
    if warnings:
        parts.append(f"{len(warnings)} {'warning' if len(warnings) == 1 else 'warnings'}")
    return f"Open at the time of this decision: {', '.join(parts)}."


async def _resolve(
    conn: Any,
    gate: store.Row,
    *,
    kind: str,
    by: str,
    note: str | None,
    supervisor: Any,
) -> None:
    """Record a decision and hand the run back to the graph.

    The resume payload is written before the graph is touched, so a crash between
    the response and the resume loses nothing: the poller finds the run and
    replays the same resume.
    """
    if gate["kind"] != "c1-design-review":
        # The funnel claims a design version and flips design stages, which is
        # meaningless for another phase's gate. The code review gate gets its
        # own decision route with C2; until then this is the honest refusal.
        raise Conflict(
            f"this is a {gate['kind']} gate; it is decided in its own phase, "
            "not through the design decision routes"
        )
    resolved = await store.resolve_gate(
        conn,
        gate["id"],
        decision=kind,
        by=by,
        note=note,  # type: ignore[arg-type]
    )
    if resolved is None:
        raise Conflict("that decision was already recorded")

    project_id = gate["project_id"]
    # What was known when the decision was made, recorded with it.
    #
    # The cold chain design was approved over thirty nine consistency errors.
    # The rules had fired, the panel had them, and the record afterwards said
    # only "Approved the design", so nothing distinguished that approval from
    # one made over a clean report. A reader is allowed to approve a design
    # they know is imperfect; they are not served by a log that forgets which
    # kind it was.
    open_findings = await _open_findings(conn, project_id)
    await store.post_thread_message(
        conn,
        project_id,
        kind="system",
        author=by,
        content=(
            "Approved the design. Code Generation can start."
            if kind == "approved"
            else f"Requested changes: {note}"
        ),
        stage_id="design-review",
    )
    await store.record(
        conn,
        actor=by,
        action="Approved the design" if kind == "approved" else "Requested changes",
        target=f"version {gate['requirements_version']}",
        detail=" ".join(filter(None, [(note or "")[:500], open_findings])),
        project_id=project_id,
        run_id=gate["run_id"],
        category="approval",
    )

    resume: dict[str, Any] = {"kind": kind, "note": note}
    if kind == "changes":
        # The store allocates the version, here, before the graph is touched. It
        # also drains any notes that arrived while the run was in flight, so they
        # are applied by this regeneration rather than waiting for another one.
        version, notes = await store.claim_next_version(conn, project_id, note=note, by=by)
        resume["version"] = version
        resume["notes"] = notes
        await store.set_run_version(conn, gate["run_id"], version)
        await store.set_stages(
            conn,
            project_id,
            list(ARTEFACT_STAGE_IDS),
            status="generating",
        )

    await store.set_run_state(
        conn,
        gate["run_id"],
        "queued",
        resume_payload=resume,
    )
    if supervisor is not None:
        from .projects import _after_commit

        _after_commit(supervisor, gate["run_id"])
