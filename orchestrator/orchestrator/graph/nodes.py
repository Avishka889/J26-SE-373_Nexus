"""The graph's nodes.

Two rules, and the second is the one that bites if it is forgotten.

Nodes compute and persist artefacts idempotently. They never write run or gate
lifecycle rows: the runner does that, because it is the only place that knows
whether `ainvoke` returned an interrupt or a result.

**The interrupted node re-executes from its start on resume.** LangGraph replays
it, so anything before `interrupt()` runs a second time. The gate node therefore
contains nothing else at all: no database read, no audit write, no payload
assembly beyond what is already in checkpointed state. A test asserts its body
stays that way.

One node per stage rather than one node for the component, and the reason is what
a reader sees. Six artefact families through a model is a minute or three, and a
single node means eight stages sit at generating and then all flip to complete at
once. Per stage, each one finishes on its own, the snapshot says so immediately,
and a crash costs the stage that was running rather than the whole run.

Failure is not uniform, and that is deliberate. Requirements and the graph are
load bearing: everything downstream reads them, so failing one fails the run.
The other four are leaves. A wireframe stage that dies should not take the sprint
plan with it, so those record the failure on their own stage and let the run
carry on. The reader gets five stages and one marked failed with a reason, and a
retry button that regenerates only that one.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

from langgraph.graph import END
from langgraph.types import Command, interrupt
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel
from sdlc_contracts import (
    ArchitectureGraph,
    ArtefactKind,
    Carry,
    ParsedRequirement,
    RequirementsArtefact,
    SprintPlan,
    carry_requirement_ids,
    carry_story_ids,
)

from ..clients.c1 import C1Client, StageOutcome
from ..components import QUESTIONS_GATE_KIND
from ..db import store
from ..errors import readable_failure
from ..model_use import stage_model_use
from ..wording import readable_notes, stage_label
from .state import C1RunState


def input_for(state: C1RunState) -> str:
    """What this run reads: the original text plus every note since.

    A revision note is part of the input rather than a separate channel, so the
    second run sees what the first saw and what the reader asked for, in order.
    """
    text = state.get("input_text", "")
    notes = state.get("revision_notes") or []
    return text + "\n\n" + "\n\n".join(notes) if notes else text


async def _load(pool: AsyncConnectionPool, project_id: str, kind: str) -> dict[str, Any] | None:
    async with pool.connection() as conn:
        artefacts = await store.latest_artefacts(conn, project_id)
    found = artefacts.get(kind)
    return found["body"] if found else None


async def _persist(
    pool: AsyncConnectionPool,
    state: C1RunState,
    *,
    kind: ArtefactKind,
    outcome: StageOutcome[Any],
) -> None:
    """Store one stage's artefact and everything that says it happened.

    One transaction, so a crash between the artefact and the stage row cannot
    leave a stage reading complete with nothing behind it.
    """
    async with pool.connection() as conn:
        await store.put_artefact(
            conn,
            project_id=state["project_id"],
            kind=kind,
            version=state["requirements_version"],
            body=outcome.artefact.model_dump(by_alias=True, mode="json"),
            run_id=uuid.UUID(state["run_id"]),
        )
        await store.set_stage(
            conn,
            state["project_id"],
            kind,  # type: ignore[arg-type]
            status="complete",
            version=state["requirements_version"],
            summary=outcome.summary,
            model_use=stage_model_use(outcome.notes),
        )
        await store.post_thread_message(
            conn,
            state["project_id"],
            kind="stage_summary",
            author="Design agent",
            content=outcome.summary,
            stage_id=kind,  # type: ignore[arg-type]
        )
        await store.record(
            conn,
            actor="Design agent",
            action=f"Generated {stage_label(kind)}",
            target=f"version {state['requirements_version']}",
            # The honesty metrics land here rather than in the artefact: how many
            # attempts a stage took is a fact about the run, and putting it in
            # the artefact would make two runs that produced the same design
            # compare as different.
            detail=readable_notes(outcome.notes),
            project_id=state["project_id"],
            run_id=uuid.UUID(state["run_id"]),
        )


async def _fail(
    pool: AsyncConnectionPool, state: C1RunState, kind: ArtefactKind, error: Exception
) -> None:
    """Mark one stage failed, in words a reader can act on."""
    async with pool.connection() as conn:
        await store.set_stage(
            conn,
            state["project_id"],
            kind,  # type: ignore[arg-type]
            status="failed",
            error=readable_failure(error),
        )
        await store.record(
            conn,
            actor="Design agent",
            action=f"Failed to generate {stage_label(kind)}",
            target=f"version {state['requirements_version']}",
            detail=readable_failure(error),
            project_id=state["project_id"],
            run_id=uuid.UUID(state["run_id"]),
        )


async def _requirements_of(pool: AsyncConnectionPool, project_id: str) -> list[ParsedRequirement]:
    body = await _load(pool, project_id, "requirements")
    return RequirementsArtefact.model_validate(body).requirements if body else []


async def _graph_of(pool: AsyncConnectionPool, project_id: str) -> ArchitectureGraph:
    body = await _load(pool, project_id, "architecture-graph")
    return ArchitectureGraph.model_validate(body) if body else ArchitectureGraph()


async def _history[T: BaseModel](
    pool: AsyncConnectionPool, state: C1RunState, *, kind: ArtefactKind, model: type[T]
) -> list[T]:
    """Every earlier version of one artefact, oldest first, as its own type."""
    async with pool.connection() as conn:
        rows = await store.artefact_history(
            conn, state["project_id"], kind, before=state["requirements_version"]
        )
    return [model.model_validate(row["body"]) for row in rows]


def _with_carried_ids[T](outcome: StageOutcome[Any], artefact: T, carry: Carry) -> StageOutcome[T]:
    """The same outcome with stabilised ids, and the carry in the honesty notes.

    The counts go in the audit note rather than the artefact for the reason
    every other honesty metric does: how an id was decided is a fact about this
    run, and putting it in the artefact would make two runs that produced the
    same design compare as different.
    """
    return StageOutcome(
        artefact=artefact, summary=outcome.summary, notes={**outcome.notes, **carry.notes}
    )


def make_parse_requirements(pool: AsyncConnectionPool, c1: C1Client):
    """Read the input. Load bearing: a failure here fails the run.

    The ids C1 returns are positional: the first requirement it read is R-1.
    They are replaced here with the ids this project already uses, because the
    component is stateless and sees one brief where identity is a fact about the
    project's history. Everything downstream reads the requirements back out of
    the store, so this is the only place it has to happen: the graph, the
    wireframes and the sprint plan all trace to the stable ids without knowing
    that anything was decided.
    """

    async def parse_requirements(state: C1RunState) -> C1RunState:
        async with _recording_failure(pool, state, "requirements"):
            outcome = await c1.parse_requirements(input_for(state))
            stable, carry = carry_requirement_ids(
                outcome.artefact,
                await _history(pool, state, kind="requirements", model=RequirementsArtefact),
            )
            await _persist(
                pool, state, kind="requirements", outcome=_with_carried_ids(outcome, stable, carry)
            )
        return {"attempt": state.get("attempt", 0) + 1, "asked": len(stable.questions)}

    return parse_requirements


def make_build_graph(pool: AsyncConnectionPool, c1: C1Client):
    """Build the one graph everything else reads. Also load bearing."""

    async def build_graph(state: C1RunState) -> C1RunState:
        async with _recording_failure(pool, state, "architecture-graph"):
            requirements = await _requirements_of(pool, state["project_id"])
            outcome = await c1.build_graph(requirements, text=input_for(state))
            await _persist(pool, state, kind="architecture-graph", outcome=outcome)
            await _complete_domain_model(pool, state, outcome.artefact)
        return {}

    return build_graph


async def _beat(pool: AsyncConnectionPool, state: C1RunState) -> None:
    """Tell the poller this run is alive.

    `claimable_runs` reclaims a running row whose heartbeat went quiet, and
    before this the only bump was `set_run_state` at the top of `advance`, so
    a run was reclaimable the moment its stages together outlasted the stale
    window. One bump per stage keeps a progressing run its own.
    """
    async with pool.connection() as conn:
        await store.heartbeat(conn, uuid.UUID(state["run_id"]))


@asynccontextmanager
async def _recording_failure(
    pool: AsyncConnectionPool, state: C1RunState, kind: ArtefactKind
) -> AsyncIterator[None]:
    """Mark a load bearing stage failed on the way out, then let it fail the run.

    A leaf stage swallows its own failure; these two must not, because nothing
    downstream is meaningful without them. But they still have to say which stage
    broke and why before the exception leaves: the run row records that the run
    failed, and only the node knows which of the six it was.

    Without this the stage sat at generating forever, which is the one state a
    reader cannot act on. The plan's own warning about background work dying and
    leaving stages stuck was about exactly this shape.
    """
    await _beat(pool, state)
    try:
        yield
    except Exception as error:
        await _fail(pool, state, kind, error)
        raise


async def _complete_domain_model(
    pool: AsyncConnectionPool, state: C1RunState, graph: ArchitectureGraph
) -> None:
    """Mark the domain model, which is a projection and has no artefact of its own.

    A projection is exactly as complete as the thing it projects. Nothing generates
    this stage, so nothing was flipping it, and it sat at pending for the life of
    the project while the page it names rendered perfectly well from the graph.

    That was not cosmetic. The client decides the gate is waiting by asking whether
    every stage is complete, so one stage stuck at pending meant the decision bar
    never appeared and no design could ever be approved or sent back. The gate is
    the whole point of the phase, and it was unreachable outside fixtures.

    The summary is counted from the graph rather than written, the same way every
    other stage's is, so it cannot claim a number the design does not have.
    """
    actors = [n for n in graph.nodes if n.kind == "actor" and n.actor_kind != "external_system"]
    external = [n for n in graph.nodes if n.kind == "actor" and n.actor_kind == "external_system"]
    entities = [n for n in graph.nodes if n.kind == "entity"]
    summary = (
        f"Domain model ready: {_plural(len(entities), 'entity', 'entities')}, "
        f"{_plural(len(actors), 'actor')}, {_plural(len(external), 'external system')}"
    )
    async with pool.connection() as conn:
        await store.set_stage(
            conn,
            state["project_id"],
            "domain-model",
            status="complete",
            version=state["requirements_version"],
            summary=summary,
        )


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _leaf(kind: ArtefactKind, pool: AsyncConnectionPool, call):
    """A stage nothing downstream depends on.

    Its failure is recorded and the run continues, because taking the sprint
    plan down because a diagram failed would cost the reader five good artefacts
    to report one bad one.
    """

    async def node(state: C1RunState) -> C1RunState:
        await _beat(pool, state)
        try:
            outcome = await call(state)
        except Exception as error:
            await _fail(pool, state, kind, error)
            return {}
        await _persist(pool, state, kind=kind, outcome=outcome)
        return {}

    return node


def make_recommend(pool: AsyncConnectionPool, c1: C1Client):
    async def call(state: C1RunState):
        project_id = state["project_id"]
        return await c1.recommend(
            await _requirements_of(pool, project_id), await _graph_of(pool, project_id)
        )

    return _leaf("architecture-recommendation", pool, call)


def make_write_uml(pool: AsyncConnectionPool, c1: C1Client):
    async def call(state: C1RunState):
        return await c1.write_uml(await _graph_of(pool, state["project_id"]))

    return _leaf("uml-diagrams", pool, call)


def make_draw_wireframes(pool: AsyncConnectionPool, c1: C1Client):
    async def call(state: C1RunState):
        project_id = state["project_id"]
        requirements = await _requirements_of(pool, project_id)
        return await c1.draw_wireframes(
            await _graph_of(pool, project_id),
            requirement_ids=[r.id for r in requirements],
            version=f"v{state['requirements_version']}",
            # What each requirement says, which the drawer reads beside the graph.
            requirements=requirements,
        )

    return _leaf("wireframes", pool, call)


def make_plan_sprint(pool: AsyncConnectionPool, c1: C1Client):
    """Plan the sprint, then give the stories the ids this project already uses.

    Story ids are positional too, and worse: C1 numbers them down the priority
    ranking, so a story nobody touched is renumbered when the note above it
    changes priority. A test traces to a story id, so the same reallocation that
    breaks the requirement diff breaks the trace from a test to the work it was
    written for.

    A story's identity is the set of requirements it realises, which is why this
    runs after the requirement ids are settled rather than beside them: those ids
    are stable by now, so the strongest rung reads no wording at all.
    """

    async def call(state: C1RunState):
        project_id = state["project_id"]
        outcome = await c1.plan_sprint(
            await _requirements_of(pool, project_id), await _graph_of(pool, project_id)
        )
        stable, carry = carry_story_ids(
            outcome.artefact,
            await _history(pool, state, kind="sprint-plan", model=SprintPlan),
        )
        return _with_carried_ids(outcome, stable, carry)

    return _leaf("sprint-plan", pool, call)


#: Pauses for questions in one generation: the first, and one follow-up after the
#: answers are read. A model can almost always find something more to ask, so a
#: third would be a loop rather than a conversation.
MAX_QUESTION_PAUSES = 2


def questions_gate(state: C1RunState) -> Command[Literal["parse_requirements", "build_graph"]]:
    """Ask the design's questions before the rest of it is built, and never block.

    A run built every stage on the assumptions it stated, and applying the
    answers built every stage again: two designs, the first reviewed and thrown
    away. So a generation whose analysis asked questions pauses here. "changes"
    carries the answers, at the version the store allocated, and analyses the
    requirements again with them; "approved" builds the rest on the assumptions,
    with the questions still open to answer at the review.

    Everything above the `interrupt()` call re-runs when the reader decides, and
    it reads checkpointed state only, so it decides the same way again.
    """
    asked = state.get("asked", 0)
    paused = state.get("paused", 0)
    if asked == 0 or paused >= MAX_QUESTION_PAUSES:
        return Command(goto="build_graph")
    decision: dict[str, Any] = interrupt(
        {
            "kind": QUESTIONS_GATE_KIND,
            "projectId": state["project_id"],
            "runId": state["run_id"],
            "requirementsVersion": state["requirements_version"],
            "asked": asked,
        }
    )
    if decision.get("kind") == "approved":
        return Command(goto="build_graph", update={"paused": paused + 1})
    # As at the review, the version is the store's, never computed here.
    version = decision.get("version")
    if not isinstance(version, int):
        raise ValueError(
            "continuing with the answers carried no version; only the store allocates "
            "version numbers, so there is nothing safe to analyse again at"
        )
    return Command(
        goto="parse_requirements",
        update={
            "revision_notes": [n for n in (decision.get("notes") or []) if n],
            "requirements_version": version,
            "paused": paused + 1,
        },
    )


def design_gate(state: C1RunState) -> Command[Literal["parse_requirements", "__end__"]]:
    """The phase gate, and deliberately nothing else.

    Everything above the `interrupt()` call re-runs when a human answers, so
    there is nothing above it. The payload comes from checkpointed state, and the
    runner writes the gate row after `ainvoke` returns.
    """
    decision: dict[str, Any] = interrupt(
        {
            "kind": "c1-design-review",
            "projectId": state["project_id"],
            "runId": state["run_id"],
            "requirementsVersion": state["requirements_version"],
        }
    )

    if decision.get("kind") == "approved":
        return Command(goto=END)

    # Changes requested: the notes join the input and the design regenerates at
    # the version the store allocated when the decision was recorded.
    #
    # The version is taken from the payload and never computed here. `+ 1` looks
    # right and is not: `design_versions` allocates numbers, and a node that
    # guessed one would collide with the next real change note, whose artefacts
    # would then upsert over these.
    version = decision.get("version")
    if not isinstance(version, int):
        raise ValueError(
            "the changes decision carried no version; only the store allocates "
            "version numbers, so there is nothing safe to regenerate at"
        )

    return Command(
        goto="parse_requirements",
        update={
            "revision_notes": [n for n in (decision.get("notes") or []) if n],
            "requirements_version": version,
            # A new generation, which may ask its own questions first.
            "paused": 0,
        },
    )
