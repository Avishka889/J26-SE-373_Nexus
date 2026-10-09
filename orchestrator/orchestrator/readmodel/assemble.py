"""Compose a DesignSnapshot from the rows that hold it.

The snapshot is a view model, not a stored document. Each artefact lives in its
own versioned row validated against its own schema, and this puts them together
with run, gate, stage and thread state into the one payload the browser reads.

Three fields are derived here and never stored, because storing them is how a
number starts disagreeing with the thing it describes:

- wireframe coverage, recomputed from the flows against the sprint plan
- `changedNodeIds`, the nodes the current version touched
- the project's `reqPhase`, `progress` and `status`, which are a function of
  stage and gate state rather than something a client may set
"""

from collections.abc import Collection
from datetime import datetime
from typing import Any

from psycopg import AsyncConnection
from sdlc_contracts import (
    CODE_STAGE_IDS,
    DEPLOY_RUNNER_STAGE_IDS,
    DEPLOY_STAGE_IDS,
    DESIGN_STAGE_IDS,
    TEST_STAGE_IDS,
    ArchitectureGraph,
    ArchitectureRecommendation,
    AskedQuestion,
    Assumption,
    ClarifyingQuestion,
    DesignSnapshot,
    DesignStageId,
    DesignThreadMessage,
    GateDecision,
    GateState,
    ParsedRequirement,
    RequirementsArtefact,
    SprintPlan,
    StageState,
    UmlArtefact,
    WireframesArtefact,
)

from ..checks.consistency import Design, check_design
from ..checks.coverage import with_coverage
from ..components import QUESTIONS_GATE_KIND
from ..db import store
from ..model_use import kept_model_use
from .runs import run_status

#: Every overlay kind, and which part of the snapshot it lands on.
_REQUIREMENT_OVERLAYS = {"requirement_text"}
_ASSUMPTION_OVERLAYS = {"assumption_text", "assumption_dismissed"}


def _stage_row_to_model(row: store.Row) -> StageState:
    return StageState(
        id=row["stage_id"],
        status=row["status"],
        generated_from_version=row["generated_from_version"],
        generated_at=row["generated_at"],
        summary=row["summary"],
        error=row["error"],
        model_use=kept_model_use(row),
    )


def _gate_row_to_decision(row: store.Row) -> GateDecision:
    return GateDecision(
        kind=row["decision"],
        at=row["decided_at"],
        by=row["decided_by"],
        version=row["requirements_version"],
        note=row["note"],
    )


def _gate_state(history_rows: list[store.Row], version: int) -> GateState:
    """The decision that covers this version, with every other one behind it.

    A decision is recorded against the version it was made about, and the
    contract says so in as many words: "the requirements version this decision
    covers, and nothing later. When the requirements move on, the decision goes
    to history and the phase asks again."

    Reporting the newest decision whatever its version meant the phase never
    asked again. Once any version had been approved, `decision` was non null
    for ever, the page read it as decided and drew no decision bar, and the run
    waiting at its gate waited for good. Invisible until versions started
    accumulating, which they only really did once a version stopped being
    overwritten in place.
    """
    current = next(
        (row for row in reversed(history_rows) if row["requirements_version"] == version),
        None,
    )
    current_id = current["id"] if current else None
    return GateState(
        decision=_gate_row_to_decision(current) if current else None,
        history=[_gate_row_to_decision(row) for row in history_rows if row["id"] != current_id],
    )


def _apply_requirement_overlays(
    requirements: list[ParsedRequirement], rows: list[store.Row]
) -> list[ParsedRequirement]:
    """Lay human corrections over what the machine produced.

    The artefact itself is untouched, so the generated text stays recoverable and
    the correction rate stays measurable.
    """
    edits = {row["target_id"]: row["value"] for row in rows if row["kind"] in _REQUIREMENT_OVERLAYS}
    if not edits:
        return requirements
    out: list[ParsedRequirement] = []
    for requirement in requirements:
        edit = edits.get(requirement.id)
        if edit is None:
            out.append(requirement)
        else:
            out.append(requirement.model_copy(update={"text": edit, "adjusted": True}))
    return out


def _apply_assumption_overlays(
    assumptions: list[Assumption], rows: list[store.Row]
) -> list[Assumption]:
    texts = {r["target_id"]: r["value"] for r in rows if r["kind"] == "assumption_text"}
    dismissed = {r["target_id"]: r["value"] for r in rows if r["kind"] == "assumption_dismissed"}
    out: list[Assumption] = []
    for assumption in assumptions:
        update: dict[str, Any] = {}
        if assumption.id in texts:
            update["text"] = texts[assumption.id]
            update["edited"] = True
        if assumption.id in dismissed:
            update["dismissed"] = bool(dismissed[assumption.id])
        out.append(assumption.model_copy(update=update) if update else assumption)
    return out


def _edits_to(rows: list[store.Row], artefact: store.Row | None) -> list[store.Row]:
    """The edits made to this version of an artefact, and no other."""
    if artefact is None:
        return []
    return [row for row in rows if row["version"] == artefact["version"]]


def apply_design_edits(
    graph: ArchitectureGraph,
    requirements: list[ParsedRequirement],
    rows: list[store.Row],
    version: int,
) -> tuple[ArchitectureGraph, list[ParsedRequirement]]:
    """The renames and corrections made up to one design version, laid over its artefacts.

    For Code Generation, which read the artefacts as generated: a renamed node
    or a corrected requirement changed the page and nothing that was built. Up to
    the version, as the design page lays them: the ids carry across versions.
    """
    at = [row for row in rows if row["version"] <= version]
    return _apply_node_label_overlays(graph, at), _apply_requirement_overlays(requirements, at)


def _apply_question_overlays(
    questions: list[ClarifyingQuestion], rows: list[store.Row]
) -> list[ClarifyingQuestion]:
    answers = {
        r["target_id"]: (r["value"], r["at"]) for r in rows if r["kind"] == "question_answer"
    }
    out: list[ClarifyingQuestion] = []
    for question in questions:
        found = answers.get(question.id)
        if found is None:
            out.append(question)
        else:
            answer, at = found
            out.append(question.model_copy(update={"answer": answer, "answered_at": at}))
    return out


def _answered_questions(
    asked_rows: list[store.Row], overlay_rows: list[store.Row]
) -> dict[tuple[datetime, str], AskedQuestion]:
    """The question each answer in the conversation answers, keyed as its message is.

    An answer is written twice, in one transaction: the record the design reads
    (a `question_answer` edit at the version the question was asked in) and its
    message in the conversation, which names no question. Both take the
    transaction's time, so a message pairs with its record by time and words,
    and the record says which question, read from the version it was asked in.
    An answer given again replaces its record, and the earlier message then
    pairs with nothing and shows alone.
    """
    asked: dict[tuple[int, str], AskedQuestion] = {}
    for row in asked_rows:
        for found in row["questions"] or []:
            question = ClarifyingQuestion.model_validate(found)
            asked[(row["version"], question.id)] = AskedQuestion(
                id=question.id,
                question=question.question,
                traces=question.traces,
                asked_at=row["created_at"],
            )
    paired: dict[tuple[datetime, str], AskedQuestion] = {}
    for row in overlay_rows:
        if row["kind"] != "question_answer":
            continue
        question = asked.get((row["version"], row["target_id"]))
        if question is not None:
            paired[(row["at"], row["value"])] = question
    return paired


def _apply_node_label_overlays(
    graph: ArchitectureGraph, rows: list[store.Row]
) -> ArchitectureGraph:
    labels = {r["target_id"]: r["value"] for r in rows if r["kind"] == "node_label"}
    if not labels:
        return graph
    nodes = [
        node.model_copy(update={"label": labels[node.id]}) if node.id in labels else node
        for node in graph.nodes
    ]
    return graph.model_copy(update={"nodes": nodes})


def selected_architecture(
    rows: list[store.Row], version: int, architecture: ArchitectureRecommendation | None
) -> store.Row | None:
    """The architecture chosen at this design version, when it names one of its candidates.

    The first selection across every version used to win (the rows come oldest
    first), so after any regeneration a new choice was hidden behind the first
    one, and a stale id could name a candidate the new version does not have.
    A choice belongs to the version it was made at.
    """
    if architecture is None:
        return None
    candidates = {candidate.id for candidate in architecture.candidates}
    for row in reversed(rows):
        if (
            row["kind"] == "architecture_selection"
            and row["version"] == version
            and row["value"] in candidates
        ):
            return row
    return None


async def prefetch_design(conn: AsyncConnection, project_id: str, owner: str) -> None:
    """Ask, in one round trip, what composing this snapshot asks one by one.

    Only a read-only request is answered from it (`store.prefetch` does nothing
    for one that writes), and a read the list misses is still asked on its own.
    """
    await store.prefetch(
        conn,
        store.get_project_query(project_id, owner),
        store.latest_artefacts_query(project_id),
        store.stage_states_query(project_id),
        store.overlays_query(project_id),
        store.asked_questions_query(project_id),
        store.thread_query(project_id),
        store.gate_history_query(project_id, "c1-design-review"),
        store.pending_gate_query(project_id, QUESTIONS_GATE_KIND),
        store.current_version_query(project_id),
        store.queued_notes_query(project_id),
        store.latest_full_run_query(project_id, "c1"),
    )


async def compose(conn: AsyncConnection, project: store.Row) -> DesignSnapshot:
    """Read everything for one project and assemble the snapshot."""
    project_id = project["id"]

    artefacts = await store.latest_artefacts(conn, project_id)
    stage_rows = await store.stage_states(conn, project_id)
    overlay_rows = await store.overlays(conn, project_id)
    thread_rows = await store.thread(conn, project_id)
    answered = _answered_questions(await store.asked_questions(conn, project_id), overlay_rows)
    history_rows = await store.gate_history(conn, project_id, kind="c1-design-review")
    version = await store.current_version(conn, project_id)

    def body(kind: str) -> dict[str, Any] | None:
        found = artefacts.get(kind)
        return found["body"] if found else None

    requirements_body = body("requirements")
    parsed = (
        RequirementsArtefact.model_validate(requirements_body)
        if requirements_body
        else RequirementsArtefact()
    )

    graph_body = body("architecture-graph")
    graph = ArchitectureGraph.model_validate(graph_body) if graph_body else ArchitectureGraph()

    recommendation_body = body("architecture-recommendation")
    architecture = (
        ArchitectureRecommendation.model_validate(recommendation_body)
        if recommendation_body
        else None
    )

    uml_body = body("uml-diagrams")
    uml = UmlArtefact.model_validate(uml_body) if uml_body else UmlArtefact()

    wireframes_body = body("wireframes")
    wireframes = (
        WireframesArtefact.model_validate(wireframes_body)
        if wireframes_body
        else WireframesArtefact()
    )

    sprint_body = body("sprint-plan")
    sprint = SprintPlan.model_validate(sprint_body) if sprint_body else None

    # Human edits sit on top; the artefacts underneath stay as generated. A
    # requirement's id is carried across versions (the identity tests), so a
    # correction follows its requirement into later versions, and so do renames.
    # A question's id is its place in the list, so an answer belongs only to the
    # version of the questions it answered: matched by id across versions, a
    # regenerated design's new questions arrived answered with the old answers.
    requirements = _apply_requirement_overlays(parsed.requirements, overlay_rows)
    assumptions = _apply_assumption_overlays(parsed.assumptions, overlay_rows)
    questions = _apply_question_overlays(
        parsed.questions, _edits_to(overlay_rows, artefacts.get("requirements"))
    )
    graph = _apply_node_label_overlays(graph, overlay_rows)

    selection = selected_architecture(overlay_rows, version, architecture)
    if architecture is not None and selection is not None:
        architecture = architecture.model_copy(
            update={
                "selected_candidate_id": selection["value"],
                "selected_at": selection["at"],
                "selected_by": selection["by"],
            }
        )

    refinements = {
        r["target_id"]: r["value"] for r in overlay_rows if r["kind"] == "flow_refinement"
    }
    if refinements:
        flows = [
            flow.model_copy(
                update={"pending_refinement": True, "refinement_note": refinements[flow.id]}
            )
            if flow.id in refinements
            else flow
            for flow in wireframes.flows
        ]
        wireframes = wireframes.model_copy(update={"flows": flows})

    # Both derived here: nothing writes `coversStoryIds`, because a flow is
    # drawn before a sprint plan exists and from the graph rather than from
    # the stories. The link is trace overlap, computed when it is read.
    #
    # The graph goes in too, because whether a story should have a screen at all
    # depends on whether an actor performs it, and the graph is where the actors
    # are named.
    wireframes = with_coverage(wireframes, sprint, graph)
    graph = graph.model_copy(
        update={
            "changed_node_ids": [
                node.id for node in graph.nodes if node.changed_in_version == version
            ]
        }
    )

    # Only the design vocabulary: stage_states holds the code phase's rows too
    # once C2 exists, and StageState's id is a Literal over the eight design
    # ids, so an unfiltered build was a ValidationError on the first C2 row.
    stages: dict[DesignStageId, StageState] = {
        row["stage_id"]: _stage_row_to_model(row)
        for row in stage_rows
        if row["stage_id"] in DESIGN_STAGE_IDS
    }
    # A project created before a stage id existed would be missing a row. Fill
    # rather than fail: the contract says all eight are present.
    for stage_id in DESIGN_STAGE_IDS:
        stages.setdefault(stage_id, StageState(id=stage_id))

    consistency = check_design(
        Design(
            requirements=requirements,
            graph=graph,
            uml=uml,
            wireframes=wireframes,
            sprint=sprint,
        )
    )

    queued = [row["note"] for row in await store.queued_notes(conn, project_id) if row["note"]]
    paused = await store.pending_gate(conn, project_id=project_id, kind=QUESTIONS_GATE_KIND)

    return DesignSnapshot(
        project_id=project_id,
        app_name=project["name"],
        requirements_version=version,
        queued_changes=queued,
        questions_pending=paused is not None,
        stages=stages,
        requirements=requirements,
        assumptions=assumptions,
        questions=questions,
        graph=graph,
        architecture=architecture,
        uml=uml,
        wireframes=wireframes,
        sprint=sprint,
        gate=_gate_state(history_rows, version),
        run=await run_status(conn, project_id, component="c1"),
        consistency=list(consistency.findings),
        # The design conversation only. A stage summary posted by a code run
        # names a code stage, and this snapshot's message type cannot carry it;
        # the code snapshot has its own thread view.
        thread=[
            DesignThreadMessage(
                id=str(row["id"]),
                kind=row["kind"],
                stage_id=row["stage_id"],
                author=row["author"],
                content=row["content"],
                at=row["at"],
                question=(
                    answered.get((row["at"], row["content"])) if row["kind"] == "answer" else None
                ),
            )
            for row in thread_rows
            if row["stage_id"] is None or row["stage_id"] in DESIGN_STAGE_IDS
        ],
    )


#: The stages each phase's progress counts. Deployment leaves out the two its
#: runner executes: a verified release is what finishes that phase, and it is
#: counted as the finish rather than as two more stages.
_PHASE_STAGES: dict[str, tuple[str, ...]] = {
    "design": DESIGN_STAGE_IDS,
    "code": CODE_STAGE_IDS,
    "testing": TEST_STAGE_IDS,
    "deployment": tuple(
        stage for stage in DEPLOY_STAGE_IDS if stage not in DEPLOY_RUNNER_STAGE_IDS
    ),
}

#: A stage that ran, or was decided not to apply, is behind the project.
_DONE = frozenset({"complete", "skipped"})


def _phase_progress(
    stages: dict[str, str],
    *,
    approved: bool,
    code_approved: bool,
    test_approved: bool,
    released: bool,
) -> dict[str, int]:
    """Each phase's own progress: its stages carry 80, its decision the last 20.

    A phase whose stages have all run is waiting on a person, not finished, so it
    reads 80 until its gate is approved, or for deployment until a release is
    verified. A later finish finishes every earlier phase, as the status ladder
    reads it: no phase's gate opens before the one before it was approved.
    """
    finished = {
        "design": approved or code_approved or test_approved or released,
        "code": code_approved or test_approved or released,
        "testing": test_approved or released,
        "deployment": released,
    }
    phases: dict[str, int] = {}
    for phase, ids in _PHASE_STAGES.items():
        if finished[phase]:
            phases[phase] = 100
            continue
        done = sum(1 for stage in ids if stages.get(stage) in _DONE)
        # Half up, as a reader rounds; `round` would show 2.5 as 2.
        phases[phase] = int(done * 80 / len(ids) + 0.5)
    return phases


def _progress(phases: dict[str, int]) -> int:
    """How far through the whole project it is, each phase a quarter of it.

    It was the current phase's own progress under a header that says "Overall":
    an approved design read 0, and every project from Testing onwards read 100,
    including one still waiting on its test review with nothing deployed. The
    phase is named by `status`, and each phase's own figure is in `phaseProgress`.
    """
    return int(sum(phases.values()) / len(phases) + 0.5)


#: Each phase's own stages, for asking whether it is generating.
_PHASE_STAGE_IDS: dict[str, tuple[str, ...]] = {
    "c1": DESIGN_STAGE_IDS,
    "c2": CODE_STAGE_IDS,
    "c3": TEST_STAGE_IDS,
    "c4": DEPLOY_STAGE_IDS,
}


def derive_project_view_from_stages(
    stages: dict[str, str],
    *,
    approved: bool,
    code_approved: bool = False,
    test_approved: bool = False,
    released: bool = False,
    started: bool | None = None,
    stopped: Collection[str] = (),
) -> dict[str, Any]:
    """`reqPhase`, `progress`, `phaseProgress`, `status` and `runStopped`.

    The one derivation, for the project list and for a project's own page:
    there were two, and they disagreed (the list never said "analyzing"). The
    flags are about each phase's current version, as `store.project_progress`
    reads them, so a phase counts only while what it approved is still what the
    project is on.

    `started` is whether anything was ever run, for telling a draft nobody
    started from a project whose first run stopped; left out, the stages say.
    `stopped` names the phases whose newest full run failed, and only the phase
    the project is in counts, and only while nothing in it is generating again.
    """
    statuses = [stages.get(stage, "pending") for stage in DESIGN_STAGE_IDS]
    req_phase = next(
        (stage for stage in reversed(DESIGN_STAGE_IDS) if stages.get(stage) == "complete"),
        "input",
    )
    phases = _phase_progress(
        stages,
        approved=approved,
        code_approved=code_approved,
        test_approved=test_approved,
        released=released,
    )
    if started is None:
        started = any(status != "pending" for status in stages.values())

    # The ladder reads newest phase first: a verified release means the project
    # is complete, an approved test review means it is in deployment, an approved
    # code review that it is in testing, an approved design review that it is in
    # code. Each rung is its own gate kind; a kind blind bool made a code
    # approval read as the design one.
    phase: str | None
    if released:
        status, phase = "complete", None
    elif test_approved:
        status, phase = "deploy", "c4"
    elif code_approved:
        status, phase = "testing", "c3"
    elif approved:
        status, phase = "code", "c2"
    elif any(status == "generating" for status in statuses):
        status, phase = "analyzing", "c1"
    elif not started:
        status, phase = "draft", "c1"
    else:
        status, phase = "design", "c1"

    generating = phase is not None and any(
        stages.get(stage) == "generating" for stage in _PHASE_STAGE_IDS[phase]
    )
    return {
        "reqPhase": req_phase,
        "progress": _progress(phases),
        "phaseProgress": phases,
        "status": status,
        "runStopped": phase is not None and phase in stopped and not generating,
    }


def project_view(facts: dict[str, Any]) -> dict[str, Any]:
    """The derived fields from one project's facts, as `store.project_progress` reads them."""
    return derive_project_view_from_stages(
        facts["stages"],
        approved=facts["approved"],
        code_approved=facts["code_approved"],
        test_approved=facts["test_approved"],
        released=facts["released"],
        started=facts["started"],
        stopped=facts["stopped"],
    )
