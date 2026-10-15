"""The code read model, the mutations that move it, and the code review gate.

The design routes' shape, for the code phase: every route answers with a whole
snapshot, which is what lets the client write one response into its cache and
never re-derive partial state.

Generation is explicit. A code run costs minutes and money, so nothing starts
one by being navigated to: the reader presses generate, and only on a project
whose design has been approved. Everything after that follows one rule, which
is the difference between the two kinds of change a reader can make:

- Changing what gets built (the scope, the contract arm) allocates a new code
  version and regenerates, because the output would otherwise disagree with
  the decision.
- Choosing between things already generated (the stack) is an overlay the read
  model lays on, and costs no run, exactly as choosing an architecture does in
  the design phase.

File bodies are behind their own route, one at a time, because the snapshot is
polled while anything is generating and a run writes tens of files.
"""

import io
import zipfile
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sdlc_contracts import (
    CODE_GENERATING_STAGE_IDS,
    CODE_STAGE_IDS,
    ApiContractArtefact,
    CodeSnapshot,
    RepositoryPointer,
    SprintPlan,
    SprintScope,
)
from sdlc_contracts.openapi import to_openapi

from ..components import spec_for
from ..db import store
from ..errors import Conflict, NotFound, readable_failure
from ..previews import PreviewRefused
from ..readmodel.code import GATE_KIND, compose_code, design_blocker, prefetch_code
from ..sprints import StoryChoice, choice_value, latest_choices, latest_sprint, next_sprint
from .continuing import continue_if_stopped_here
from .deps import Actor, Components, Db, Owner, Supervisor, require_project
from .stale_reviews import close_stale_review

router = APIRouter(tags=["code"])


class ScopeIn(BaseModel):
    in_scope: bool = Field(alias="inScope")
    #: Start a new version over an approved one; see `_regenerate`.
    supersede: bool = False


class GenerateIn(BaseModel):
    #: Start a new version over an approved one; see `_regenerate`.
    supersede: bool = False


class NextSprintIn(BaseModel):
    #: Start a new version over an approved one; see `_regenerate`.
    supersede: bool = False


class SelectIn(BaseModel):
    stack_id: str = Field(min_length=1, alias="stackId")


class ArmIn(BaseModel):
    arm: str = Field(pattern="^(rule|llm|merged)$")
    #: Start a new version over an approved one; see `_regenerate`.
    supersede: bool = False


class DecisionIn(BaseModel):
    kind: str = Field(pattern="^(approved|changes)$")
    note: str | None = None


async def _snapshot(conn: Any, project_id: str, owner: str) -> CodeSnapshot:
    """The phase as the request leaves it, read in a few round trips (see design's)."""
    async with store.reads_only(conn):
        await prefetch_code(conn, project_id, owner)
        return await compose_code(conn, await require_project(conn, project_id, owner))


async def _regenerate(
    conn: Any,
    project_id: str,
    supervisor: Any,
    *,
    reason: str,
    by: str,
    supersede: bool = False,
) -> store.Row:
    """Make the code catch up with a decision, whatever state the phase is in.

    Three cases, and the middle one is the reason this is not just "start a
    run". A reader changes the scope or the arm while looking at the review,
    which means the gate is pending on a run paused inside the graph. Starting
    a second run there would open a second gate on a project the index allows
    one for, so the change *is* the answer to the pending review: the gate is
    resolved as changes, with the change itself as the note, and the paused
    run resumes at a new code version. Anything else would make the reader
    dismiss a review before they were allowed to act on what it showed.
    """
    # One request at a time decides whether this starts a run, so a double
    # click finds the first one's run instead of starting a second.
    await store.lock_run_axis(conn, project_id, "c2")
    # From the current design version, approved and settled, and from nothing
    # else; the snapshot carries the same reason so the page can say it first.
    blocker = await design_blocker(conn, project_id)
    if blocker is not None:
        raise Conflict(blocker)

    # Approved code is replaced only on purpose. A new version leaves the
    # approved one behind, and with it whatever Testing measured and Deployment
    # released, so a click that did not say so is refused with the version it
    # would replace, which the page turns into a confirmation.
    current = await store.current_code_version(conn, project_id)
    if (
        current
        and not supersede
        and await store.code_version_is_approved(conn, project_id, current)
    ):
        raise Conflict(
            f"code version {current} is approved; a new version replaces it, and Testing and "
            "Deployment start again from the new one",
            detail={"approvedVersion": current, "supersede": "required"},
        )

    gate = await store.pending_gate(conn, project_id=project_id, kind=GATE_KIND)
    if gate is not None:
        moved = await _design_moved_past(conn, project_id, gate)
        if moved is None:
            return await _resume_through_gate(
                conn, project_id, supervisor, gate, reason=reason, by=by
            )
        # The waiting run reads the design it began from, and a newer one has
        # been approved since: resuming it regenerated from the older design,
        # while the page said generating again reads the newer one. The review
        # closes, and a run of its own starts on the current design below.
        pinned, newer = moved
        await close_stale_review(
            conn,
            project_id,
            gate,
            by=by,
            reason=(
                f"{reason} This code was generated from design version {pinned}, and design "
                f"version {newer} has been approved since, so this review closes and the "
                f"code is generated from version {newer}."
            ),
            stage_id="code-review",
            category="code",
            what=f"code version {gate['requirements_version']}",
        )

    if await store.active_run(conn, project_id, component="c2") is not None:
        raise Conflict(
            "a code run is already in flight on this project; wait for it to "
            "reach the review before changing what it is building"
        )

    design_version = await store.current_version(conn, project_id)
    code_version = await store.next_code_version(conn, project_id)
    # The tests written against the previous version come with it. The code
    # generator writes only its own files, so without this a regeneration
    # leaves the new version with no tests: a suite a reader approved would
    # vanish, and the testing phase would generate fresh ones against the new
    # code every time, which is how a stale test becomes impossible.
    carried = await store.carry_tests_forward(conn, project_id, to_version=code_version)
    await store.seed_code_stages(conn, project_id)
    await store.set_stages(conn, project_id, list(CODE_GENERATING_STAGE_IDS), status="generating")
    run = await store.create_run(
        conn,
        project_id=project_id,
        requirements_version=code_version,
        component="c2",
        source_version=design_version,
    )
    await store.record(
        conn,
        actor="system",
        action="Started a code run",
        target=f"code version {code_version}",
        detail=(
            f"{reason} Generating from design version {design_version}."
            + (f" {carried} test files came forward from the previous version." if carried else "")
        ),
        project_id=project_id,
        run_id=run["id"],
        category="code",
    )
    if supervisor is not None:
        from .projects import _after_commit

        _after_commit(supervisor, run["id"])
    return run


async def _design_moved_past(conn: Any, project_id: str, gate: store.Row) -> tuple[int, int] | None:
    """The waiting run's design version and the newer approved one, if the design moved on.

    Only a settled design counts (`design_blocker`): one still regenerating or
    waiting on its own review is not yet something to generate code from.
    """
    run = await store.get_run(conn, gate["run_id"])
    pinned = int((run or {}).get("source_version") or 0)
    current = await store.current_version(conn, project_id)
    if pinned and current > pinned and await design_blocker(conn, project_id) is None:
        return pinned, current
    return None


async def _resume_through_gate(
    conn: Any, project_id: str, supervisor: Any, gate: store.Row, *, reason: str, by: str
) -> store.Row:
    """Answer the pending review with the change, and resume its run."""
    resolved = await store.resolve_gate(
        conn,
        gate["id"],
        decision="changes",
        by=by,
        note=reason,
    )
    if resolved is None:
        raise Conflict("that review was decided while this change was being made")

    version = await store.next_code_version(conn, project_id)
    await store.carry_tests_forward(conn, project_id, to_version=version)
    await store.set_run_version(conn, gate["run_id"], version)
    await store.set_stages(conn, project_id, list(CODE_GENERATING_STAGE_IDS), status="generating")
    await store.record(
        conn,
        actor=by,
        action="Requested code changes",
        target=f"code version {version}",
        detail=reason,
        project_id=project_id,
        run_id=gate["run_id"],
        category="approval",
    )
    await store.set_run_state(
        conn,
        gate["run_id"],
        "queued",
        resume_payload={"kind": "changes", "note": reason, "version": version},
    )
    if supervisor is not None:
        from .projects import _after_commit

        _after_commit(supervisor, gate["run_id"])
    run = await store.get_run(conn, gate["run_id"])
    assert run is not None
    return run


@router.get("/projects/{project_id}/code")
async def get_code(project_id: str, conn: Db, owner: Owner) -> CodeSnapshot:
    return await _snapshot(conn, project_id, owner)


@router.get("/projects/{project_id}/code/files/{path:path}")
async def get_code_file(
    project_id: str, path: str, conn: Db, owner: Owner, version: int | None = None
) -> dict[str, Any]:
    """One generated file, by path.

    Its own route rather than a field on the snapshot, which is polled every
    1.2 seconds while a run is in flight and would otherwise carry every
    source file the run wrote on every poll.
    """
    await require_project(conn, project_id, owner)
    at = version or await store.current_code_version(conn, project_id)
    content = await store.code_file(conn, project_id, version=at, path=path)
    if content is None:
        raise NotFound("file", path)
    return {"path": path, "version": at, "content": content}


async def _generated_files(conn: Any, project_id: str, version: int) -> dict[str, str]:
    """What Code Generation wrote at a version, without the tests Testing wrote beside it."""
    files = await store.code_files(conn, project_id, version=version)
    tests = await store.code_files(conn, project_id, version=version, stage_id="test-generation")
    return {path: content for path, content in files.items() if path not in tests}


@router.get("/projects/{project_id}/code/archive")
async def get_code_archive(
    project_id: str, conn: Db, owner: Owner, version: int | None = None
) -> Response:
    """A version's generated files as a zip, with or without GitHub.

    Without a connection nothing was pushed, and the only way to the code was
    a whole new run. The files are the version's as stored, so the archive is
    what its build and its review read.
    """
    project = await require_project(conn, project_id, owner)
    at = version or await store.current_code_version(conn, project_id)
    files = await _generated_files(conn, project_id, at) if at else {}
    if not files:
        raise NotFound("generated code", f"{project_id} at version {at}")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in sorted(files.items()):
            archive.writestr(path, content)
    stem = "".join(c if c.isalnum() else "-" for c in project["name"].lower()).strip("-")
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{stem or "project"}-code-v{at}.zip"'
        },
    )


class PushIn(BaseModel):
    version: int | None = Field(default=None, ge=1)


@router.post("/projects/{project_id}/code/push")
async def push_version(
    project_id: str,
    body: PushIn,
    conn: Db,
    owner: Owner,
    components: Components,
    actor: Actor,
) -> CodeSnapshot:
    """Push a version that was never pushed, and land it if its review approved it.

    Without GitHub at build time nothing was pushed, and the only remedy was a
    whole new run. This pushes the stored files to the version's own branch;
    an approved version also lands on the default branch, as an approval does.
    A version an accepted security fix wrote counts as approved when the
    version it patched was.
    """
    project = await require_project(conn, project_id, owner)
    version = body.version or await store.current_code_version(conn, project_id)
    found = await store.artefacts_at(conn, project_id, version=version, kinds=("code-repository",))
    if "code-repository" not in found:
        raise Conflict(f"code version {version} has no generated code to push")
    stored = found["code-repository"]["body"]
    pointer = stored.get("repository")
    if pointer:
        raise Conflict(
            f"code version {version} is on {pointer.get('url')}, branch "
            f"{pointer.get('branch') or pointer.get('defaultBranch')}, already"
        )
    pushed, said = await push_stored_version(
        conn, project, version=version, owner=owner, c2=components["c2"]
    )
    if pushed is None:
        raise Conflict(said)
    await store.record(
        conn,
        actor=actor,
        action="Pushed a code version",
        target=f"code version {version}",
        detail=f"To {pushed.url}, branch {pushed.branch}.{said}",
        project_id=project_id,
        category="code",
    )
    await store.post_thread_message(
        conn,
        project_id,
        kind="system",
        author=actor,
        content=f"Pushed code version {version} to {pushed.url}, branch {pushed.branch}.{said}",
        stage_id="build",
    )
    return await _snapshot(conn, project_id, owner)


async def push_stored_version(
    conn: Any, project: store.Row, *, version: int, owner: str, c2: Any
) -> tuple[RepositoryPointer | None, str]:
    """Push a stored version's generated files to its own branch, and land it if approved.

    The pointer GitHub took, with what happened to the default branch said;
    or no pointer, with why nothing was pushed: no working GitHub connection,
    or GitHub refusing the push. The pointer is recorded on the version where
    none was. Shared by Push and by applying an accepted security fix, whose
    version is pushed as every version is.
    """
    from ..config import get_settings
    from ..crypto import decrypt
    from ..graph.code_nodes import _repository_name, version_branch

    project_id = project["id"]
    ciphertext = await store.get_secret(conn, f"{owner}:github")
    token = None
    if ciphertext is not None:
        try:
            token = decrypt(get_settings().secret_key, ciphertext)
        except Exception:
            token = None
    if token is None:
        return None, "there is no working GitHub connection: connect GitHub in Settings first"
    files = await _generated_files(conn, project_id, version)
    pushed = await store.pushed_repository(conn, project_id)
    name = pushed["name"] if pushed else _repository_name(project["name"], project_id)
    try:
        outcome = await c2.push(
            files,
            name=name,
            token=token,
            message=f"Generate code version {version}",
            branch=version_branch(version),
        )
    except Exception as error:
        return None, f"GitHub did not take the push: {readable_failure(error)}"
    if outcome.pointer is None:
        return None, outcome.reason or "GitHub did not take the push"
    await store.record_late_push(
        conn,
        project_id,
        version=version,
        pointer=outcome.pointer.model_dump(by_alias=True, mode="json"),
    )
    landed_note = ""
    if await store.code_version_is_approved(conn, project_id, version):
        landed = await c2.land(
            outcome.pointer, token=token, message=f"Code version {version}, approved"
        )
        landed_note = (
            f" {outcome.pointer.default_branch} now carries it."
            if landed.commit_sha
            else f" {outcome.pointer.default_branch} could not move to it: {landed.reason}."
        )
    return outcome.pointer, landed_note


@router.get("/projects/{project_id}/code/openapi")
async def get_code_openapi(
    project_id: str, conn: Db, owner: Owner, version: int | None = None
) -> dict[str, Any]:
    """The api-contract as an OpenAPI 3.1 document.

    A translation of a stored artefact rather than a second source of truth:
    nothing is persisted, so the document cannot drift from the contract it
    describes. C3 reads this to derive API test skeletons, and a person can
    read it in any OpenAPI tool, which is what makes the proposal's OpenAPI
    claim something other than a word.

    `version` selects an older contract, because the self healing classifier
    compares two of these and needs both.
    """
    project = await require_project(conn, project_id, owner)
    at = version or await store.current_code_version(conn, project_id)
    if not at:
        raise NotFound("api-contract", project_id)
    artefacts = await store.artefacts_at(conn, project_id, version=at, kinds=("api-contract",))
    stored = artefacts.get("api-contract")
    if stored is None:
        raise NotFound("api-contract", f"{project_id} at version {at}")
    artefact = ApiContractArtefact.model_validate(stored["body"])
    return to_openapi(artefact.contract, title=project["name"], version=f"{at}.0.0")


# ------------------------------------------------------------------ preview


def _previews(request: Request) -> Any:
    return getattr(request.app.state, "previews", None)


@router.get("/projects/{project_id}/code/preview")
async def get_preview(project_id: str, request: Request, conn: Db, owner: Owner) -> dict[str, Any]:
    """What is running, if anything.

    Its own route rather than a field on the snapshot: a preview is a process,
    not an artefact, and reading it is also what tells the idle sweep somebody
    is still looking.
    """
    await require_project(conn, project_id, owner)
    supervisor = _previews(request)
    if supervisor is None:
        return {"status": "unavailable", "reason": "previews are not enabled here"}
    view = await supervisor.view(project_id)
    return view.as_dict() if view else {"status": "none"}


@router.post("/projects/{project_id}/code/preview")
async def start_preview(
    project_id: str, request: Request, conn: Db, owner: Owner, actor: Actor
) -> dict[str, Any]:
    """Install, build and serve this project's current code on this machine.

    Refused when the build did not pass: previewing code that failed its own
    typecheck would be showing something that does not exist.
    """
    await require_project(conn, project_id, owner)
    supervisor = _previews(request)
    if supervisor is None:
        raise Conflict("previews are not enabled on this orchestrator")

    version = await store.current_code_version(conn, project_id)
    if not version:
        raise Conflict("nothing has been generated for this project yet")
    # A version an accepted fix wrote was not built on its own: the build that
    # stands for it is the one of the version it patched.
    build, _ = await store.repository_field_through_patches(conn, project_id, version, "build")
    steps = (build or {}).get("steps") or []
    if not steps or any(step.get("outcome") != "passed" for step in steps):
        raise Conflict(
            "this code version did not build, so there is nothing to preview. "
            "Read the build stage, fix what it reports, and generate again."
        )

    sources = await store.code_files(conn, project_id, version=version)
    try:
        view = await supervisor.start(project_id, code_version=version, sources=sources)
    except PreviewRefused as refused:
        raise Conflict(str(refused)) from None
    await store.record(
        conn,
        actor=actor,
        action="Started a preview",
        target=f"code version {version}",
        detail=f"Serving on {view.url or 'no url: ' + (view.error or 'it did not start')}.",
        project_id=project_id,
        category="code",
    )
    return view.as_dict()


@router.delete("/projects/{project_id}/code/preview", status_code=204)
async def stop_preview(
    project_id: str, request: Request, conn: Db, owner: Owner, actor: Actor
) -> None:
    await require_project(conn, project_id, owner)
    supervisor = _previews(request)
    if supervisor is not None:
        await supervisor.stop(project_id)
    await store.record(
        conn,
        actor=actor,
        action="Stopped the preview",
        target=project_id,
        detail="The server was stopped and its build directory removed.",
        project_id=project_id,
        category="code",
    )


@router.post("/projects/{project_id}/code/generate")
async def generate(
    project_id: str,
    conn: Db,
    owner: Owner,
    supervisor: Supervisor,
    actor: Actor,
    body: GenerateIn | None = None,
) -> CodeSnapshot:
    await require_project(conn, project_id, owner)
    await _regenerate(
        conn,
        project_id,
        supervisor,
        reason="Requested from Code Generation.",
        by=actor,
        supersede=bool(body and body.supersede),
    )
    return await _snapshot(conn, project_id, owner)


@router.post("/projects/{project_id}/code/scope/{story_id}")
async def set_story_scope(
    project_id: str,
    story_id: str,
    body: ScopeIn,
    conn: Db,
    owner: Owner,
    supervisor: Supervisor,
    actor: Actor,
) -> CodeSnapshot:
    """Move a story in or out of the build, and regenerate.

    A scope change changes what the contract covers and what the code
    implements, so leaving the artefacts as they were would leave the reader
    looking at code for a story they had just removed.
    """
    await require_project(conn, project_id, owner)
    version = await store.current_code_version(conn, project_id)
    # A story moved in on its own joins the newest sprint planned.
    plan = await _sprint_plan(conn, project_id)
    sprint = (
        latest_sprint(plan, latest_choices(await store.overlays(conn, project_id)))
        if plan is not None
        else 1
    )
    await store.put_overlay(
        conn,
        project_id=project_id,
        version=version or 1,
        kind="story_scope",
        target_id=story_id,
        value=choice_value(StoryChoice(body.in_scope, sprint if body.in_scope else 0)),
        by=actor,
    )
    await store.post_thread_message(
        conn,
        project_id,
        kind="user_note",
        author=actor,
        content=f"{'Added' if body.in_scope else 'Removed'} {story_id} {'to' if body.in_scope else 'from'} the build.",
        stage_id="sprint-scope",
    )
    await store.record(
        conn,
        actor=actor,
        action="Changed the sprint scope",
        target=story_id,
        detail=f"in scope: {body.in_scope}",
        project_id=project_id,
        category="code",
    )
    await _regenerate(
        conn,
        project_id,
        supervisor,
        reason=f"Scope changed for {story_id}.",
        by=actor,
        supersede=body.supersede,
    )
    return await _snapshot(conn, project_id, owner)


async def _sprint_plan(conn: Any, project_id: str) -> SprintPlan | None:
    """The sprint plan at the current design version, which generating reads."""
    version = await store.current_version(conn, project_id)
    found = await store.artefacts_at(conn, project_id, version=version, kinds=("sprint-plan",))
    return (
        SprintPlan.model_validate(found["sprint-plan"]["body"]) if "sprint-plan" in found else None
    )


@router.post("/projects/{project_id}/code/sprints/next")
async def plan_next_sprint(
    project_id: str,
    body: NextSprintIn,
    conn: Db,
    owner: Owner,
    supervisor: Supervisor,
    actor: Actor,
) -> CodeSnapshot:
    """Put the next sprint's stories into the build, and generate once for all of them.

    The stories are the ones the page showed (`next_sprint`, from the same
    plan and the same decisions), divided as the sprint plan divides a
    sprint. Each is recorded as a decision a person made, as moving one story
    is, so the scope stage applies them and a later generation keeps them.
    The build grows: the earlier sprints' stories stay in it.
    """
    await require_project(conn, project_id, owner)
    plan = await _sprint_plan(conn, project_id)
    if plan is None:
        raise Conflict(
            "the current design version has no sprint plan, so there is no backlog to plan from"
        )
    sprint = next_sprint(plan, latest_choices(await store.overlays(conn, project_id)))
    if not sprint.stories:
        raise Conflict(
            "every story in the sprint plan is in the build already, so there is no next "
            "sprint to plan"
        )
    # Generating through an open review resolves it as requested changes, which
    # is not what planning means: the next sprint goes on top of a reviewed build.
    waiting = await store.pending_gate(conn, project_id=project_id, kind=GATE_KIND)
    if waiting is not None:
        raise Conflict(
            f"the code review of version {waiting['requirements_version']} is still open. "
            f"Approve it or request changes first: sprint {sprint.number} is planned on top "
            "of a build that has been reviewed"
        )
    version = await store.current_code_version(conn, project_id)
    for story in sprint.stories:
        await store.put_overlay(
            conn,
            project_id=project_id,
            version=version or 1,
            kind="story_scope",
            target_id=story.id,
            value=choice_value(StoryChoice(True, sprint.number)),
            by=actor,
        )
    ids = ", ".join(story.id for story in sprint.stories)
    await store.post_thread_message(
        conn,
        project_id,
        kind="user_note",
        author=actor,
        content=(
            f"Planned sprint {sprint.number}: {ids}, {sprint.points} points against a velocity "
            f"assumption of {sprint.velocity}."
        ),
        stage_id="sprint-scope",
    )
    await store.record(
        conn,
        actor=actor,
        action="Planned the next sprint",
        target=f"sprint {sprint.number}",
        detail=f"{ids}, {sprint.points} points of {sprint.velocity}",
        project_id=project_id,
        category="code",
    )
    await _regenerate(
        conn,
        project_id,
        supervisor,
        reason=f"Sprint {sprint.number} planned.",
        by=actor,
        supersede=body.supersede,
    )
    return await _snapshot(conn, project_id, owner)


@router.post("/projects/{project_id}/code/stack/select")
async def select_stack(
    project_id: str, body: SelectIn, conn: Db, owner: Owner, actor: Actor
) -> CodeSnapshot:
    """Choose a stack. No run: nothing downstream reads the choice yet.

    The generators build MERN whatever is selected, and saying so by not
    regenerating is more honest than spending a run to produce identical code.
    When a second stack's generators land, this becomes a regenerating change
    and the guide says so.
    """
    await require_project(conn, project_id, owner)
    version = await store.current_code_version(conn, project_id)
    await store.put_overlay(
        conn,
        project_id=project_id,
        version=version or 1,
        kind="stack_selection",
        target_id="stack",
        value=body.stack_id,
        by=actor,
    )
    await store.record(
        conn,
        actor=actor,
        action="Selected a tech stack",
        target=body.stack_id,
        detail="Recorded against the current code version.",
        project_id=project_id,
        category="code",
    )
    return await _snapshot(conn, project_id, owner)


@router.post("/projects/{project_id}/code/arm")
async def choose_arm(
    project_id: str, body: ArmIn, conn: Db, owner: Owner, supervisor: Supervisor, actor: Actor
) -> CodeSnapshot:
    """Choose which contract arm the code is generated from, and regenerate.

    The comparison between the arms is the point of storing both, and choosing
    one is a decision about what gets built rather than about what is shown, so
    it costs a run.
    """
    await require_project(conn, project_id, owner)
    version = await store.current_code_version(conn, project_id)
    await store.put_overlay(
        conn,
        project_id=project_id,
        version=version or 1,
        kind="contract_arm_choice",
        target_id="arm",
        value=body.arm,
        by=actor,
    )
    await store.post_thread_message(
        conn,
        project_id,
        kind="user_note",
        author=actor,
        content=f"Generating from the {body.arm} arm.",
        stage_id="api-contract",
    )
    await store.record(
        conn,
        actor=actor,
        action="Chose a contract arm",
        target=body.arm,
        detail="The code regenerates from the chosen arm.",
        project_id=project_id,
        category="code",
    )
    await _regenerate(
        conn,
        project_id,
        supervisor,
        reason=f"Generating from the {body.arm} arm.",
        by=actor,
        supersede=body.supersede,
    )
    return await _snapshot(conn, project_id, owner)


@router.post("/projects/{project_id}/code/stages/{stage_id}/retry")
async def retry_stage(
    project_id: str,
    stage_id: str,
    conn: Db,
    owner: Owner,
    supervisor: Supervisor,
    actor: Actor,
) -> CodeSnapshot:
    if stage_id not in CODE_STAGE_IDS:
        raise NotFound("stage", stage_id)
    if stage_id not in spec_for("c2").stage_nodes():
        raise Conflict(
            f"{stage_id} is the gate; there is nothing to regenerate. Decide it instead."
        )
    await require_project(conn, project_id, owner)
    version = await store.current_code_version(conn, project_id)
    if not version:
        raise Conflict("nothing has been generated yet, so there is no stage to retry")
    if await store.code_version_is_approved(conn, project_id, version):
        # Refused here rather than at the write, which refuses too but only
        # after the model has been paid for the regeneration it cannot keep.
        # A version a fix wrote counts as its patched version's approval did,
        # and a retry would write a stage's files over the fix.
        raise Conflict(
            f"code version {version} was approved, so its stages are settled. Generate "
            "again to open a new version instead."
        )
    await store.lock_run_axis(conn, project_id, "c2")
    # Try again on the stage that stopped the phase's run goes on with that
    # run, to the review, rather than regenerating the one stage and stopping.
    continued = await continue_if_stopped_here(conn, project_id, spec_for("c2"), stage_id, by=actor)
    if continued is not None:
        if supervisor is not None:
            from .projects import _after_commit

            _after_commit(supervisor, continued["id"])
        return await _snapshot(conn, project_id, owner)
    if await store.active_run(conn, project_id, component="c2", states=store.WORKING_RUN_STATES):
        raise Conflict(
            "a code run is already working on this project; wait for it to finish "
            "before retrying a stage"
        )

    latest = await store.latest_run(conn, project_id)
    design_version = (
        latest["source_version"]
        if latest is not None and latest["component"] == "c2" and latest["source_version"]
        else await store.current_version(conn, project_id)
    )
    await store.set_stage(conn, project_id, stage_id, status="generating")
    # One stage, at the version already generated: a whole run would rewrite
    # four artefacts the reader has read to fix the one they asked about.
    run = await store.create_run(
        conn,
        project_id=project_id,
        requirements_version=version,
        component="c2",
        only_stage=stage_id,
        source_version=design_version,
    )
    if supervisor is not None:
        from .projects import _after_commit

        _after_commit(supervisor, run["id"])
    return await _snapshot(conn, project_id, owner)


def _approval_concerns(snapshot: CodeSnapshot) -> list[str]:
    """What failed or is still open, which approving over needs a note for.

    A code version was approved with its typecheck failing, in one click. The
    page says the same before it sends the approval (`code-generation/model/
    gate.ts`), with the stage and the build step named.
    """
    failed = sum(1 for state in snapshot.stages.values() if state.status == "failed")
    build = snapshot.repository.build if snapshot.repository is not None else None
    errors = len(snapshot.agreement.errors) if snapshot.agreement is not None else 0
    concerns = []
    if failed:
        concerns.append(f"{failed} failed {'stage' if failed == 1 else 'stages'}")
    if build is None:
        concerns.append("a build that did not run")
    elif not build.passed:
        concerns.append("a build that did not pass")
    if errors:
        concerns.append(f"{errors} agreement {'error' if errors == 1 else 'errors'}")
    return concerns


async def _keep_the_build(conn: Any, project_id: str, *, version: int, by: str) -> None:
    """Record what an approved build covers, story by story, as decisions.

    A story was in the build by default until somebody moved it. So a design
    regenerated after the code was approved, whose new plan put an already built
    story in the backlog, took it out of the next build, and a backlog story the
    new plan proposed joined it without being planned (review item C1-4). Once a
    build is approved, what is in it and what is not is a decision, which only a
    person moving a story or planning the next sprint changes.
    """
    scope = (
        await store.artefacts_at(conn, project_id, version=version, kinds=("sprint-scope",))
    ).get("sprint-scope")
    if scope is None:
        return
    decided = latest_choices(await store.overlays(conn, project_id))
    for story in SprintScope.model_validate(scope["body"]).stories:
        if story.id in decided:
            continue
        await store.put_overlay(
            conn,
            project_id=project_id,
            version=version,
            kind="story_scope",
            target_id=story.id,
            value=choice_value(StoryChoice(story.in_scope, story.sprint if story.in_scope else 0)),
            by=by,
        )


@router.post("/projects/{project_id}/code/decision")
async def submit_decision(
    project_id: str, body: DecisionIn, conn: Db, owner: Owner, supervisor: Supervisor, actor: Actor
) -> CodeSnapshot:
    """The code review gate, reached from the browser."""
    await require_project(conn, project_id, owner)
    gate = await store.pending_gate(conn, project_id=project_id, kind=GATE_KIND)
    if gate is None:
        raise Conflict("there is no code decision waiting on this project")
    if body.kind == "changes" and not (body.note or "").strip():
        raise Conflict("requesting changes needs a note saying what to change")
    # Neither decision helps at a review the design moved past: changes would
    # regenerate from the older design, and an approval announced Testing and
    # landed code that no longer follows the design, which the project's
    # status then ignored. Generating again closes the review.
    moved = await _design_moved_past(conn, project_id, gate)
    if moved is not None:
        pinned, current = moved
        would = (
            "requested changes would regenerate it from the older design"
            if body.kind == "changes"
            else "approving it would send code that no longer follows the design on to Testing"
        )
        raise Conflict(
            f"this code was generated from design version {pinned}, and design version "
            f"{current} has been approved since, so {would}. Generate again instead: it "
            f"closes this review and generates the code from version {current}"
        )
    if body.kind == "approved" and not (body.note or "").strip():
        concerns = _approval_concerns(await _snapshot(conn, project_id, owner))
        if concerns:
            raise Conflict(
                f"Approving with {' and '.join(concerns)} needs a note saying why it is "
                "right to approve as it is."
            )

    resolved = await store.resolve_gate(
        conn,
        gate["id"],
        decision=body.kind,  # type: ignore[arg-type]
        by=actor,
        note=body.note,  # type: ignore[arg-type]
    )
    if resolved is None:
        raise Conflict("that decision was already recorded")

    if body.kind == "approved":
        await _keep_the_build(conn, project_id, version=int(gate["requirements_version"]), by=actor)

    await store.post_thread_message(
        conn,
        project_id,
        kind="system",
        author=actor,
        content=(
            "Approved the code. Testing and Security can start."
            if body.kind == "approved"
            else f"Requested changes: {body.note}"
        ),
        stage_id="code-review",
    )
    resume: dict[str, Any] = {"kind": body.kind, "note": body.note}
    carried = 0
    if body.kind == "changes":
        # The store allocates the version, here, before the graph is touched.
        # A node that guessed one would collide with the next real change.
        version = await store.next_code_version(conn, project_id)
        # The tests come with it, as they do when the code is generated again
        # (`_regenerate`): this path left them behind, so the next testing run
        # wrote every acceptance test from scratch and the healing loop had no
        # earlier test to call stale.
        carried = await store.carry_tests_forward(conn, project_id, to_version=version)
        resume["version"] = version
        await store.set_run_version(conn, gate["run_id"], version)
        await store.set_stages(
            conn, project_id, list(CODE_GENERATING_STAGE_IDS), status="generating"
        )

    await store.record(
        conn,
        actor=actor,
        action="Approved the code" if body.kind == "approved" else "Requested code changes",
        target=f"code version {gate['requirements_version']}",
        detail=(body.note or "")[:500]
        + (
            f" {carried} test {'file' if carried == 1 else 'files'} came forward to the next "
            "version."
            if carried
            else ""
        ),
        project_id=project_id,
        run_id=gate["run_id"],
        category="approval",
    )

    await store.set_run_state(conn, gate["run_id"], "queued", resume_payload=resume)
    if supervisor is not None:
        from .projects import _after_commit

        _after_commit(supervisor, gate["run_id"])
    return await _snapshot(conn, project_id, owner)
