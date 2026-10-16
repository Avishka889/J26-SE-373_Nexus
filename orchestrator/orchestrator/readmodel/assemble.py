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

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
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
    DesignChanges,
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
    diff_requirements,
    diff_stories,
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
    out: list[ParsedRequirement] = []
    for requirement in requirements:
        edit = edits.get(requirement.id)
        if edit is None:
            out.append(requirement)
        else:
            out.append(requirement.model_copy(update={"text": edit, "adjusted": True}))
    return with_corrected_priorities(out, rows)


def with_corrected_priorities(
    requirements: list[ParsedRequirement], rows: list[store.Row]
) -> list[ParsedRequirement]:
    """The priorities a person set, over what the rule read (review item C1-2).

    Kept against the requirement's id, which later versions carry, so a
    correction follows its requirement as a corrected text does. The newest wins:
    the rows come oldest first.
    """
    set_by_a_person = {
        row["target_id"]: row["value"] for row in rows if row["kind"] == "requirement_priority"
    }
    return [
        requirement.model_copy(
            update={"priority": set_by_a_person[requirement.id], "priority_corrected": True}
        )
        if requirement.id in set_by_a_person
        else requirement
        for requirement in requirements
    ]


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


#: The edits that are read against the artefact they were made to, and the
#: artefact each is made to. A requirement keeps its id when it is reworded, and
#: a node's id and an assumption's are their places in a list, so none of these
#: can be laid over a later version by the id alone. A requirement's priority is
#: not here: it is a judgement of the requirement, whose id is carried, and not
#: of its wording.
_FOLLOWED: dict[str, str] = {
    "requirement_text": "requirements",
    "assumption_text": "requirements",
    "assumption_dismissed": "requirements",
    "node_label": "architecture-graph",
}

#: What `_FOLLOWED` reads, for the one query that fetches it.
FOLLOWED_KINDS = ("requirements", "architecture-graph")


@dataclass(frozen=True)
class HeldEdits:
    """A person's edits as they stand at one design version."""

    #: The edits that hold, oldest first, each naming its target by the id this
    #: version gives it.
    rows: list[store.Row]
    #: Corrections not laid over a requirement because it was changed since they
    #: were made, by the requirement's id. Kept so the page can say so.
    set_aside: dict[str, str] = field(default_factory=dict)


def _same(left: str, right: str) -> bool:
    return " ".join(left.casefold().split()) == " ".join(right.casefold().split())


def _now_called(row: store.Row, made_to: dict[str, Any], now: dict[str, Any]) -> str | None:
    """The id, in the artefact as it is now, of what this edit was made to.

    None when it is no longer there as it was: reworded, removed, or become
    something else. The artefacts are as generated, so the comparison is of the
    machine's words on both sides and a person's edit never moves it.
    """
    target = row["target_id"]
    if row["kind"] == "requirement_text":
        was = _text_of(made_to.get("requirements", []), target)
        return target if was is not None and _is(now.get("requirements", []), target, was) else None
    if row["kind"] == "node_label":
        was_node = next((one for one in made_to.get("nodes", []) if one["id"] == target), None)
        if was_node is None:
            return None
        same = [
            one["id"]
            for one in now.get("nodes", [])
            if one["kind"] == was_node["kind"] and _same(one["label"], was_node["label"])
        ]
        return same[0] if len(same) == 1 else None
    was = _text_of(made_to.get("assumptions", []), target)
    if was is None:
        return None
    same = [one["id"] for one in now.get("assumptions", []) if _same(one["text"], was)]
    return same[0] if len(same) == 1 else None


def _text_of(items: list[dict[str, Any]], item_id: str) -> str | None:
    return next((one["text"] for one in items if one["id"] == item_id), None)


def _is(items: list[dict[str, Any]], item_id: str, text: str) -> bool:
    found = _text_of(items, item_id)
    return found is not None and _same(found, text)


def edits_holding(rows: list[store.Row], history: list[store.Row], version: int) -> HeldEdits:
    """The edits made up to one design version that still hold at it.

    An edit made to this version's artefact goes by its id. One made to an
    earlier version's is read against that version: it holds when what it was
    made to is still there as the machine wrote it, and it is laid on the id
    that thing has now. Otherwise it is left off, because laid over by the id
    alone it covered a requirement a change had reworded, and renamed or
    dismissed whatever stood in the same place of a new list (review items C1-8
    and C1-9).
    """

    def newest(kind: str, upto: int) -> store.Row | None:
        found = [one for one in history if one["kind"] == kind and one["version"] <= upto]
        return max(found, key=lambda one: one["version"], default=None)

    held: list[store.Row] = []
    set_aside: dict[str, str] = {}
    for row in rows:
        if row["version"] > version:
            continue
        kind = _FOLLOWED.get(row["kind"])
        made_to = newest(kind, row["version"]) if kind else None
        now = newest(kind, version) if kind else None
        if made_to is None or now is None or made_to["version"] == now["version"]:
            held.append(row)
            if row["kind"] == "requirement_text":
                set_aside.pop(row["target_id"], None)
            continue
        called = _now_called(row, made_to["body"], now["body"])
        if called is not None:
            held.append({**row, "target_id": called})
        elif row["kind"] == "requirement_text" and _text_of(
            now["body"].get("requirements", []), row["target_id"]
        ):
            set_aside[row["target_id"]] = row["value"]
    return HeldEdits(rows=held, set_aside=set_aside)


async def held_edits(
    conn: AsyncConnection,
    project_id: str,
    *,
    version: int,
    rows: list[store.Row] | None = None,
) -> HeldEdits:
    """`edits_holding`, reading what it needs. One more read only when an edit
    was made to an earlier version than the one asked for."""
    if rows is None:
        rows = await store.overlays(conn, project_id)
    earlier = any(row["kind"] in _FOLLOWED and row["version"] < version for row in rows)
    history = (
        await store.artefacts_upto(conn, project_id, kinds=FOLLOWED_KINDS, upto=version)
        if earlier
        else []
    )
    return edits_holding(rows, history, version)


def apply_design_edits(
    graph: ArchitectureGraph, requirements: list[ParsedRequirement], held: HeldEdits
) -> tuple[ArchitectureGraph, list[ParsedRequirement]]:
    """The renames and corrections that hold at one design version, laid over its artefacts.

    For Code Generation, which read the artefacts as generated: a renamed node
    or a corrected requirement changed the page and nothing that was built. And
    for the comparison healing reads, which has to compare what was built.
    """
    return (
        _apply_node_label_overlays(graph, held.rows),
        _apply_requirement_overlays(requirements, held.rows),
    )


def with_set_aside(
    requirements: list[ParsedRequirement], held: HeldEdits
) -> list[ParsedRequirement]:
    """Each requirement with the correction that was not laid over it, if any."""
    return [
        one.model_copy(update={"set_aside_correction": held.set_aside[one.id]})
        if one.id in held.set_aside
        else one
        for one in requirements
    ]


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


#: What a version is compared with the one before it on.
COMPARED_KINDS = ("requirements", "sprint-plan", "architecture-graph")


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
    if store.remembering(conn):
        version = await store.current_version(conn, project_id)
        if version > 1:
            await store.prefetch(
                conn, store.artefacts_at_query(project_id, version - 1, COMPARED_KINDS)
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

    # Human edits sit on top; the artefacts underneath stay as generated. An
    # edit made to an earlier version holds here only on the thing it was made
    # to (`edits_holding`): a requirement's id is carried across versions, but
    # the requirement under it can be reworded, and a node's id and an
    # assumption's are places in a list.
    # A question's id is its place in the list too, and an answer belongs only
    # to the version of the questions it answered: matched by id across versions,
    # a regenerated design's new questions arrived answered with the old answers.
    held = await held_edits(conn, project_id, version=version, rows=overlay_rows)
    requirements = with_set_aside(_apply_requirement_overlays(parsed.requirements, held.rows), held)
    assumptions = _apply_assumption_overlays(parsed.assumptions, held.rows)
    questions = _apply_question_overlays(
        parsed.questions, _edits_to(overlay_rows, artefacts.get("requirements"))
    )
    graph = _apply_node_label_overlays(graph, held.rows)

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
    # What this version changed since the one before, from the two stored sets.
    # The graph's changed nodes were read from `changedInVersion`, which nothing
    # ever set, so the list was always empty (review item C1-6).
    before = (
        await store.artefacts_at(conn, project_id, version=version - 1, kinds=COMPARED_KINDS)
        if version > 1
        else {}
    )
    changes = None
    if "requirements" in before and requirements_body:
        earlier_plan = before.get("sprint-plan")
        changes = DesignChanges(
            from_version=version - 1,
            requirements=diff_requirements(
                RequirementsArtefact.model_validate(before["requirements"]["body"]),
                parsed,
                from_version=version - 1,
                to_version=version,
            ),
            stories=diff_stories(
                SprintPlan.model_validate(earlier_plan["body"]) if earlier_plan else None, sprint
            ),
        )
    earlier_graph = before.get("architecture-graph")
    earlier_nodes = (
        {
            node.id: (node.kind, node.label, node.description)
            for node in ArchitectureGraph.model_validate(earlier_graph["body"]).nodes
        }
        if earlier_graph
        else None
    )
    graph = graph.model_copy(
        update={
            "changed_node_ids": [
                node.id
                for node in graph.nodes
                if node.changed_in_version == version
                or (
                    earlier_nodes is not None
                    and earlier_nodes.get(node.id) != (node.kind, node.label, node.description)
                )
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
        changes=changes,
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
    current: Mapping[str, bool] | None = None,
) -> dict[str, int]:
    """Each phase's own progress: its stages carry 80, its decision the last 20.

    A phase whose stages have all run is waiting on a person, not finished, so it
    reads 80 until its gate is approved, or for deployment until a release is
    verified. A later finish finishes every earlier phase, as the status ladder
    reads it: no phase's gate opens before the one before it was approved.

    `current` says which phases' stages are about the increment the project is
    on. One that is not reads 0: its stages are the increment before's, and
    counting them started the next sprint near 90% (review item X-8).
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
        if current is not None and not current.get(phase, True):
            phases[phase] = 0
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
    current: Mapping[str, bool] | None = None,
    sprint: int = 1,
    backlog_left: bool = False,
) -> dict[str, Any]:
    """`reqPhase`, `progress`, `phaseProgress`, `status`, `sprint` and `runStopped`.

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
        current=current,
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
        # Released, and the build is the whole plan only when no story waits:
        # with a backlog left the project is an increment along, not complete.
        status, phase = ("released" if backlog_left else "complete"), None
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
        "sprint": sprint,
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
        current=facts["current"],
        sprint=facts["sprint"],
        backlog_left=facts["backlog_left"],
    )
