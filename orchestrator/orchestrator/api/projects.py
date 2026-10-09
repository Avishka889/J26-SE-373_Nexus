"""Projects, and the one place a run begins.

There is no "start the pipeline" endpoint, because the frontend never had one:
it PATCHes the project with the requirement text. So that PATCH is the start
signal. Requirement text going from empty to non empty queues run 1, which means
the existing UI starts a real run without a new call, and the client side stage
ticker it used to fake becomes a set of harmless no ops that can be deleted
calmly rather than in lockstep.
"""

from typing import Any

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sdlc_contracts import GENERATING_STAGE_IDS

from .. import workspaces
from ..config import get_settings
from ..db import store
from ..deploy.adapters import local_docker
from ..errors import Conflict
from ..readmodel.assemble import project_view
from .deps import Actor, Db, Owner, Supervisor, require_project

router = APIRouter(tags=["projects"])


class CreateProject(BaseModel):
    """A new project, with the text that starts its design run if there is any.

    One request, so one transaction: it was a POST and then a PATCH carrying
    the text, and a PATCH that failed left a project with no requirements in
    the list, which the reader's retry then duplicated.
    """

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1)
    description: str = ""
    requirement_text: str = Field(default="", alias="requirementText")
    files: list[str] = Field(default_factory=list)


class ChatMessageIn(BaseModel):
    role: str
    type: str
    content: str


def _project_fields(project: store.Row, stacks: dict[str, list[str]]) -> dict[str, Any]:
    """The plain columns, shared so a list row and a single project cannot drift.

    The stack a person set wins; otherwise the one Code Generation chose. A
    project still on the colour every project once had takes its own.
    """
    color = project["color"]
    return {
        "id": project["id"],
        "name": project["name"],
        "description": project["description"],
        "createdAt": project["created_at"].isoformat(),
        "updatedAt": project["updated_at"].isoformat(),
        "requirementText": project["requirement_text"],
        "files": project["files"],
        "techStack": project["tech_stack"] or stacks.get(project["id"], []),
        "color": store.colour_for(project["id"]) if color == store.LEGACY_PROJECT_COLOR else color,
    }


async def _project_response(conn: Any, project: store.Row) -> dict[str, Any]:
    """A project, with the derived fields the client reads.

    `reqPhase`, `progress`, `phaseProgress` and `status` are computed from stage
    and gate state every time. They are not columns, so nothing can PATCH the
    project into a state the run disagrees with.
    """
    # The list's facts and the list's derivation, for one project: the two
    # derived it differently and disagreed, and this one composed a whole design
    # snapshot to read eight stage statuses.
    facts = await store.project_progress(
        conn, owner_id=project["owner_id"], project_id=project["id"]
    )
    derived = project_view(facts[project["id"]])
    messages = await store.chat_messages(conn, project["id"])
    stacks = await store.chosen_stacks(conn, project["owner_id"], project["id"])

    return {
        **_project_fields(project, stacks),
        "requirementChat": [
            {
                "id": str(m["id"]),
                "role": m["role"],
                "type": m["type"],
                "content": m["content"],
                "createdAt": m["created_at"].isoformat(),
            }
            for m in messages
        ],
        **derived,
    }


@router.get("/projects")
async def list_projects(conn: Db, owner: Owner) -> list[dict[str, Any]]:
    """Every project, without composing a single design snapshot.

    This is the call the browser blocks its first paint on, so what it costs is
    what a refresh costs. It used to reach its three derived fields by composing
    a whole snapshot per project, serially, which read every artefact of every
    project to look at eight stage statuses: twenty one seconds on a development
    branch, twenty one seconds of blank page.

    The statuses and the gate now arrive in one query for all projects, and the
    chat is left out entirely: a list never renders it.
    """
    # One round trip for the list and every fact its statuses come from.
    await store.prefetch(
        conn,
        store.list_projects_query(owner),
        *store.project_progress_queries(owner),
        *store.chosen_stacks_queries(owner),
    )
    projects = await store.list_projects(conn, owner_id=owner)
    progress = await store.project_progress(conn, owner_id=owner)
    stacks = await store.chosen_stacks(conn, owner)
    return [
        {
            **_project_fields(project, stacks),
            "requirementChat": [],
            **project_view(progress[project["id"]]),
        }
        for project in projects
        # A project created between the two reads has no facts yet; the next
        # read lists it.
        if project["id"] in progress
    ]


@router.post("/projects", status_code=status.HTTP_201_CREATED)
async def create_project(
    body: CreateProject, conn: Db, owner: Owner, supervisor: Supervisor, actor: Actor
) -> dict[str, Any]:
    project = await store.create_project(
        conn, name=body.name, description=body.description, owner_id=owner
    )
    queued_run = None
    if body.requirement_text.strip() or body.files:
        patch: dict[str, Any] = {"files": body.files}
        if body.requirement_text.strip():
            patch["requirement_text"] = body.requirement_text
        project = await store.patch_project(conn, project["id"], patch) or project
        if body.requirement_text.strip():
            queued_run = await _start_design(conn, project["id"], body.requirement_text, actor)
    response = await _project_response(conn, project)
    if queued_run is not None and supervisor is not None:
        _after_commit(supervisor, queued_run["id"])
    return response


@router.get("/projects/{project_id}")
async def get_project(project_id: str, conn: Db, owner: Owner) -> dict[str, Any]:
    await store.prefetch(
        conn,
        store.get_project_query(project_id, owner),
        *store.project_progress_queries(owner, project_id),
        store.chat_messages_query(project_id),
        *store.chosen_stacks_queries(owner, project_id),
    )
    return await _project_response(conn, await require_project(conn, project_id, owner))


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: str, conn: Db, owner: Owner, actor: Actor) -> Response:
    """Delete a project, and say so in the record it leaves behind.

    Not while a run or a release is still going: the run would write into a
    project that no longer exists, and a release half done would be nobody's
    to watch or undo. The audit entries outlive it, detached from it, with one
    more saying it was deleted: the project's whole history went with its row.
    Its GitHub repository and any cloud deployments are not this platform's to
    remove, and the page says so before asking.
    """
    project = await require_project(conn, project_id, owner)
    busy = await store.work_in_progress(conn, project_id)
    if busy is not None:
        raise Conflict(f"{busy} is in progress on this project. Delete it once that has finished.")
    await store.keep_audit_trail(conn, project_id)
    await store.record(
        conn,
        owner_id=owner,
        actor=actor,
        action="Deleted a project",
        target=project["name"],
        category="settings",
        detail=(
            f"Project {project_id}. Its containers on this machine, its local release "
            "among them, were removed with it. Its GitHub repository and any Vercel or "
            "Render deployments were not touched."
        ),
    )
    await store.delete_project(conn, project_id, owner_id=owner)
    # And what it left on disk. A testing workspace holds an install, which is
    # a few hundred megabytes per code version, and nothing else would ever
    # come back for it once the rows are gone.
    workspaces.forget(get_settings().c3_workspace_root, project_id)
    # And its containers. A release kept its port from every project after it,
    # and a stopped one kept its claim on it.
    await local_docker.remove_project(project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


#: camelCase from the client to snake_case in the database. Fields the client
#: may not set (the derived ones) simply are not here, so they are ignored
#: rather than refused: the old stage ticker PATCHes `reqPhase` and must not 400.
_FIELD_MAP = {
    "name": "name",
    "description": "description",
    "requirementText": "requirement_text",
    "files": "files",
    "techStack": "tech_stack",
    "color": "color",
}


@router.patch("/projects/{project_id}")
async def patch_project(
    project_id: str,
    body: dict[str, Any],
    conn: Db,
    owner: Owner,
    supervisor: Supervisor,
    actor: Actor,
) -> dict[str, Any]:
    if "requirementText" in body:
        # The first text starts the design run, and two requests carrying it
        # both read "no text yet" and both started one. Taken before the read,
        # so the second reads the first's text.
        await store.lock_run_axis(conn, project_id, "c1")
    project = await require_project(conn, project_id, owner)
    patch = {_FIELD_MAP[k]: v for k, v in body.items() if k in _FIELD_MAP}

    had_text = bool(project["requirement_text"].strip())
    will_have_text = bool(str(patch.get("requirement_text", project["requirement_text"])).strip())
    # Text arriving starts the design, and so does text sent to a project whose
    # design never started: it had text from before, so "text going from empty
    # to written" never happened, and the start screen's submit replaced the
    # brief and started nothing.
    never_started = await store.current_version(conn, project_id) == 0
    starts_a_run = will_have_text and (
        not had_text or (never_started and "requirement_text" in patch)
    )

    updated = await store.patch_project(conn, project_id, patch) or project

    queued_run = None
    if starts_a_run:
        queued_run = await _start_design(conn, project_id, str(patch["requirement_text"]), actor)

    response = await _project_response(conn, updated)

    # Hand the run over only after the transaction that created it commits, or a
    # worker could look for a row that is not visible yet.
    if queued_run is not None and supervisor is not None:
        _after_commit(supervisor, queued_run["id"])
    return response


async def _start_design(conn: Any, project_id: str, text: str, actor: str) -> store.Row:
    """Queue the first design run on the requirement text that just arrived.

    The text arriving is the start signal, on a create or on the first PATCH
    that carries it. Version 1 is applied immediately: it is the input, not a
    change to it.
    """
    version = await store.open_version(conn, project_id, note=None, by=actor, applied=True)
    await store.set_stages(conn, project_id, list(GENERATING_STAGE_IDS), status="generating")
    await store.post_thread_message(
        conn,
        project_id,
        kind="user_note",
        author=actor,
        content=text,
        stage_id="requirements",
    )
    return await store.create_run(conn, project_id=project_id, requirements_version=version)


def _after_commit(supervisor: Any, run_id: Any) -> None:
    """Submit once this request's transaction has landed."""
    import asyncio

    async def hand_over() -> None:
        # A short yield is enough: the dependency closes the transaction as the
        # response is returned, and the supervisor re-polls regardless, so this
        # is an optimisation rather than the mechanism.
        await asyncio.sleep(0.05)
        supervisor.submit(run_id)

    task = asyncio.create_task(hand_over())
    # Hold a reference so the task is not garbage collected mid flight.
    _PENDING.add(task)
    task.add_done_callback(_PENDING.discard)


_PENDING: set[Any] = set()


@router.post("/projects/{project_id}/requirement-chat")
async def append_chat(
    project_id: str, body: ChatMessageIn, conn: Db, owner: Owner
) -> dict[str, Any]:
    project = await require_project(conn, project_id, owner)
    await store.append_chat_message(
        conn, project_id, role=body.role, type_=body.type, content=body.content
    )
    return await _project_response(conn, project)
