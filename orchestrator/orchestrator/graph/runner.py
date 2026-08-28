"""Driving the graph, and owning run and gate lifecycle.

This is the only place `ainvoke` is called, and the only place that writes to
`runs` and `gates`. The reason is the resume rule: an interrupted node
re-executes, so a node that inserted a gate row would open a second gate every
time somebody answered the first. Here, after `ainvoke` returns, we know whether
we have an interrupt or a result, and we write once.

Background work is an in process supervisor with a durable job row. Not
`BackgroundTasks`, which delays shutdown and dies leaving stages stuck at
`generating` with nothing to recover them. Not a broker, which would add a
service, a process and a deployment target to a system that has none of them.
The durability comes from `runs`: a queued row is picked up, a running row whose
heartbeat stopped is reclaimed, and both survive a restart.
"""

import asyncio
import contextlib
import logging
import uuid
from typing import Any

from langgraph.types import Command
from psycopg_pool import AsyncConnectionPool
from sdlc_contracts import GENERATING_STAGE_IDS

from ..clients.thinking import RUN_THINKING, level_recorded
from ..components import (
    QUESTIONS_GATE_KIND,
    ComponentSpec,
    spec_for,
    stale_windows,
    where_it_stopped,
)
from ..db import store
from ..errors import readable_failure
from ..wording import phase_name, run_setup_words, stage_label

log = logging.getLogger(__name__)

#: How often the supervisor looks for work it has not been handed directly.
POLL_SECONDS = 5.0

#: Mirrors `NAME_LIMIT` in entities/project/naming.ts. A provisional name longer
#: than this is one the client truncated, and only a truncated name is worth a
#: model call to replace. The duplication across the seam is deliberate and
#: harmless: if the two drift, the cost is a naming call skipped or spent
#: needlessly, never a wrong name.
PROVISIONAL_NAME_LIMIT = 48

#: How long the naming call may take before the run gives up on it.
#:
#: This is the one model call the start of a run waits on. By the time it is
#: made, the request that started the run has already flipped six stage rows to
#: generating and the browser is polling every 1.2 seconds, so every second
#: spent here is a second of "everything generating, nothing moving" with no
#: stage to attribute it to. Left unbounded it inherits whatever the client
#: does: five minutes in HTTP mode, which is right for a stage with a repair
#: loop behind it and wrong for a title, and nothing at all in process, where
#: live runs were measured sitting here for six and thirteen minutes. A title is
#: worth a second or two of a reader's time, not a minute of it. Timing out is
#: caught the same way a refusal is, and keeps the provisional name.
NAMING_TIMEOUT_SECONDS = 20.0


def should_title(name: str, requirements_version: int, files: list[str] | None) -> bool:
    """Whether this run should replace the project's name with a real title.

    The first run only, because a project whose name changes under the reader
    every time they submit a change note is worse than one that is slightly
    stale.

    What is left alone after that is a name the reader wrote themselves and
    which is short enough to read as a label. "Build a simple calculator app" is
    one of those, and rewriting it would spend a call to change nothing.

    A filename is neither of those things. `projectName` falls back to the first
    attachment when nothing was typed, so a document attached with no prompt
    gives a project called "FOMMP-BRD.pdf": thirteen characters, so length alone
    never sees it, and nobody chose it. There is no rename anywhere in the UI
    and no later run retries this, so left ungated that project is named after a
    file forever, including as the breadcrumb root in the wireframe player. That
    is the headline case for this feature, so it is titled whatever its length.

    `files` is the row's JSONB column, which may be empty and, on a row written
    before it existed, absent.
    """
    if requirements_version != 1:
        return False
    if len(name) > PROVISIONAL_NAME_LIMIT:
        return True
    return name in (files or ())


def _sentence(text: str) -> str:
    """A reason as a sentence: capitalised, and ending in a full stop."""
    text = text.strip()
    if not text:
        return "No reason was recorded."
    text = text[0].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else text + "."


async def _pause_for_questions(
    conn: Any, *, project_id: str, run_id: uuid.UUID, version: int, asked: int, spec: ComponentSpec
) -> None:
    """The design waits on its questions, and every place that shows it says so.

    The stages after Requirements Analysis were marked generating when the run
    began; nothing builds them while it waits, so they go back to pending until
    the reader continues. The review is not reached, so its stage is left alone.
    """
    await store.set_stages(
        conn,
        project_id,
        [stage for stage in spec.generating_stage_ids if stage != "requirements"],
        status="pending",
    )
    asking = "One question" if asked == 1 else f"{asked} questions"
    await store.post_thread_message(
        conn,
        project_id,
        kind="system",
        author="Design agent",
        content=(
            f"{asking} before the rest of the design is built. Answer "
            f"{'it' if asked == 1 else 'them'} here, then continue with your answers, or "
            "continue with the assumptions."
        ),
        stage_id="requirements",
    )
    await store.record(
        conn,
        actor="system",
        action="Paused for the design's questions",
        target=f"version {version}",
        detail=(
            f"Requirements Analysis asked {asking.lower()}. The rest of the design waits "
            "for the answers, or for the assumptions to be accepted."
        ),
        project_id=project_id,
        run_id=run_id,
        category=spec.audit_category,
    )


class RunSupervisor:
    """Runs graphs in the background, and recovers the ones a restart dropped."""

    def __init__(
        self,
        *,
        pool: AsyncConnectionPool,
        #: One compiled graph and one client per component key. A run
        #: dispatches by its `component` column; a key with no graph fails the
        #: run readably rather than executing somebody else's pipeline.
        graphs: dict[str, Any] | None = None,
        clients: dict[str, Any] | None = None,
        #: The single component spelling, kept for the callers and tests that
        #: predate the registry: `graph=`/`c1=` is exactly `graphs={"c1": ...}`.
        graph: Any = None,
        c1: Any = None,
        workers: int = 2,
        poll_seconds: float = POLL_SECONDS,
    ) -> None:
        self._pool = pool
        self._graphs = dict(graphs or {})
        self._clients = dict(clients or {})
        if graph is not None and "c1" not in self._graphs:
            self._graphs["c1"] = graph
        if c1 is not None and "c1" not in self._clients:
            self._clients["c1"] = c1
        self._worker_count = workers
        self._poll_seconds = poll_seconds
        self._queue: asyncio.Queue[uuid.UUID] = asyncio.Queue()
        self._tasks: list[asyncio.Task[None]] = []
        self._inflight: set[uuid.UUID] = set()

    async def start(self) -> None:
        await self.stop_orphans()
        self._tasks = [
            asyncio.create_task(self._worker(i), name=f"run-worker-{i}")
            for i in range(self._worker_count)
        ]
        self._tasks.append(asyncio.create_task(self._poller(), name="run-poller"))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()

    def submit(self, run_id: uuid.UUID) -> None:
        """Hand a run straight to a worker, skipping the poll delay."""
        self._queue.put_nowait(run_id)

    async def stop_orphans(self) -> None:
        """Settle what the process before this one left running, before running anything.

        Nothing is running those runs: this process has started none. Left
        alone, each looked busy for its component's whole stale window, up to
        half an hour, and was then abandoned with "start a new run instead",
        though Continue goes on from its last saved step. Now one that saved a
        step stops at once, as a run a person can continue, and one that never
        did is queued, which starts it.
        """
        async with self._pool.connection() as conn:
            rows = await store.running_runs(conn)
        for run in rows:
            try:
                spec: ComponentSpec | None = spec_for(run["component"])
            except Exception:
                # A component this orchestrator does not run: the run goes
                # back to the queue, where dispatch fails it and says why.
                spec = None
            graph = self._graphs.get(run["component"])
            saved = False
            if graph is not None and spec is not None and not run["only_stage"]:
                config = {"configurable": {"thread_id": str(run["id"])}}
                saved = bool((await graph.aget_state(config)).values)
            if saved:
                await self._stop(
                    run,
                    "the orchestrator restarted while this run was working. Continue it to "
                    "go on from where it stopped: nothing it finished is done again",
                    action="Run stopped by a restart",
                    spec=spec,
                )
            else:
                async with self._pool.connection() as conn:
                    await store.set_run_state(conn, run["id"], "queued")

    async def _poller(self) -> None:
        """Pick up anything not handed over directly.

        This is what makes the queue an optimisation rather than the mechanism:
        if the process died between committing a run row and submitting it, or
        mid run, the row is still there and gets claimed.
        """
        while True:
            try:
                await asyncio.sleep(self._poll_seconds)
                async with self._pool.connection() as conn:
                    # Abandoned first, so a row too old to recover is marked
                    # rather than claimed and then refused a moment later.
                    abandoned = await store.abandoned_runs(conn)
                    rows = await store.claimable_runs(conn, stale_by_component=stale_windows())
                for row in abandoned:
                    await self._retire(row)
                for row in rows:
                    run_id = row["id"]
                    if run_id not in self._inflight:
                        self._queue.put_nowait(run_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("the run poller failed; it will try again")

    async def _worker(self, index: int) -> None:
        while True:
            run_id = await self._queue.get()
            if run_id in self._inflight:
                self._queue.task_done()
                continue
            self._inflight.add(run_id)
            try:
                await self.advance(run_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("run %s failed in worker %s", run_id, index)
            finally:
                self._inflight.discard(run_id)
                self._queue.task_done()

    def _setup(self, component: str, level: str | None = None) -> tuple[str | None, str | None]:
        """The model this component's client names, and what it asks about thinking.

        Read from the client rather than from settings, because the client is
        built once when the process starts and settings edited since describe a
        run that has not happened. None for what a client cannot say: a canned
        client sends no request, and a supervisor built without clients has
        none to ask.

        `level` is the run's (3B): what the client's requests say at it. Without
        one, or from a client that cannot say what a level sends, the client's
        own record at its configured level.
        """
        client = self._clients.get(component)
        model = getattr(client, "model", None)
        thinking_for = getattr(client, "thinking_for", None)
        thinking = (
            thinking_for(level)
            if level is not None and callable(thinking_for)
            else getattr(client, "thinking", None)
        )
        return (str(model) if model else None), (thinking if isinstance(thinking, str) else None)

    async def _level_at_start(self, run: store.Row, project: Any, spec: ComponentSpec) -> str:
        """The level a run starts at: its account's choice for the phase, or as configured.

        Read when the run starts and never again: a run keeps its level for its
        whole life, so a choice made while a review waits applies from the next
        run, not to the regeneration of this one.
        """
        async with self._pool.connection() as conn:
            chosen = await store.chosen_thinking(conn, project["owner_id"], spec.audit_category)
        if chosen is not None:
            return chosen
        return getattr(self._clients.get(spec.key), "level", None) or "off"

    def _model(self, component: str, level: str | None = None) -> str:
        """What produced this run, or an honest account of why that is not known.

        A supervisor can be built without clients where the graph carries its
        own, which is how the spine tests construct one. Recording nothing in
        that shape would be silent, and silence about which model produced a
        design is the exact problem this event exists to end, so the absence
        gets written down instead.
        """
        model, thinking = self._setup(component, level)
        if model is None:
            return "not recorded: this supervisor holds no component client"
        return run_setup_words(model, thinking)

    async def _record_regeneration(
        self,
        run_id: uuid.UUID,
        run: store.Row,
        spec: ComponentSpec,
        decision: dict[str, Any],
        level: str,
    ) -> None:
        """Say what a regeneration after "changes" runs on.

        It resumes the same run, so "Run started" never fires for it, and
        nothing wrote down what the new version was made with. A process
        restarted with another model since the run began would have regenerated
        on that model unnoticed, so a difference is said out loud.
        """
        version = decision.get("version")
        detail = f"{phase_name(run['component'])} regenerating" + (
            f" version {version}" if isinstance(version, int) else ""
        )
        detail += f" on {self._model(spec.key, level)}."
        model, thinking = self._setup(spec.key, level)
        started = (run.get("model"), run.get("thinking"))
        if started[0] and model and started != (model, thinking):
            detail += f" The run started on {run_setup_words(started[0], started[1])}."
        async with self._pool.connection() as conn:
            await store.record(
                conn,
                actor="system",
                action="Run resumed",
                target=str(run_id),
                detail=detail,
                project_id=run["project_id"],
                run_id=run_id,
                category=spec.audit_category,
            )

    async def _fail_run(
        self,
        run_id: uuid.UUID,
        run: store.Row,
        message: str,
        spec: ComponentSpec | None = None,
    ) -> None:
        log.error("run %s cannot proceed: %s", run_id, message)
        await self._stop(run, message, action="Run failed", spec=spec)

    async def _stop(
        self, run: store.Row, why: str, *, action: str, spec: ComponentSpec | None
    ) -> None:
        """Fail a run, and leave the page able to say so.

        Every way a run fails comes through here. Nothing it flipped to
        generating stays spinning; the audit log records why under the action
        that names the path; and a full run says it in its phase's own
        conversation, at the stage where it stopped. A failure written only to
        the audit log was a review that never came, with nothing on the page to
        say why.

        Without a spec, the component is not one this orchestrator runs, so no
        stage can be named and none is touched.
        """
        run_id = run["id"]
        project_id = run["project_id"]
        async with self._pool.connection() as conn:
            await store.set_run_state(conn, run_id, "failed", error=why)
            stranded = (
                await store.resolve_generating(conn, project_id, stage_ids=spec.stage_ids)
                if spec is not None
                else []
            )
            await store.record(
                conn,
                actor="system",
                action=action,
                target=str(run_id),
                detail=why + (f" Stages not reached: {', '.join(stranded)}." if stranded else ""),
                project_id=project_id,
                run_id=run_id,
                # Its own phase's: every run event was filed under Design.
                category=spec.audit_category if spec is not None else "design",
            )
            if spec is not None and not run.get("only_stage"):
                rows = await store.stage_states(conn, project_id)
                await store.post_thread_message(
                    conn,
                    project_id,
                    kind="system",
                    author="platform",
                    content=f"The run stopped. {_sentence(why)}",
                    stage_id=where_it_stopped(  # type: ignore[arg-type]
                        spec, {row["stage_id"]: row["status"] for row in rows}, stranded
                    ),
                )

    async def advance(self, run_id: uuid.UUID) -> None:
        """Start or resume one run, then record where it stopped."""
        async with self._pool.connection() as conn:
            run = await store.get_run(conn, run_id)
            if run is None or run["state"] in {"done", "failed", "superseded"}:
                return
            if run["state"] == "awaiting_gate" and run["resume_payload"] is None:
                # Paused at a gate with no decision recorded: there is nothing
                # to do, and the fresh start path below would walk the graph
                # again at the version the gate is about, overwriting the
                # artefacts the reader is deciding on.
                #
                # Reached by racing a decision's own transaction. The routes
                # hand the run to a worker 50ms after writing the decision, and
                # a worker that reads before that commit lands sees the row as
                # it was: still awaiting_gate, still carrying no payload, still
                # on the old version. Found on the first live code walk, where
                # a scope change resolved the gate, allocated code version 2,
                # and then regenerated version 1 on top of itself.
                #
                # Returning is safe rather than lossy: the decision leaves the
                # run queued, and `claimable_runs` picks up queued rows.
                log.info("run %s is paused at its gate; leaving it there", run_id)
                return
            project = await store.project_without_owner_check(conn, run["project_id"])
            if project is None:
                return
            resume_payload = run["resume_payload"]
            notes = await store.applied_notes(conn, run["project_id"], run["requirements_version"])
            await store.set_run_state(conn, run_id, "running")

        # The dispatch. The component column chose nothing before this existed:
        # every run walked the C1 graph, whatever it claimed to be.
        try:
            spec = spec_for(run["component"])
        except Exception as error:
            await self._fail_run(run_id, run, str(error))
            return
        graph = self._graphs.get(spec.key)
        if graph is None:
            await self._fail_run(
                run_id,
                run,
                f"this orchestrator has no {spec.key} graph configured, so the run "
                "cannot be driven here",
                spec,
            )
            return

        if run["only_stage"]:
            # A retry. One stage, no graph and no gate: the reader asked for that
            # artefact again and nothing else, and walking the whole graph would
            # rewrite five artefacts they had already read.
            await self._regenerate_one(run_id, run, project, spec)
            return

        config = {"configurable": {"thread_id": str(run_id)}}

        if resume_payload == store.CONTINUE_AFTER_STOP:
            # A person asked this stopped run to go on. With no input, LangGraph
            # goes on from the run's last saved step: the stage that broke runs
            # again, and nothing that finished before it does.
            existing = await graph.aget_state(config)
            if not existing.values:
                await self._stop(
                    run,
                    "this run stopped before it saved any progress, so there is nothing to "
                    "continue from; start it over instead",
                    action="Run failed",
                    spec=spec,
                )
                return
            level = level_recorded(run.get("thinking"))
            async with self._pool.connection() as conn:
                await store.set_run_state(conn, run_id, "running", resume_payload=None)
                await store.record(
                    conn,
                    actor="system",
                    action="Run continued",
                    target=str(run_id),
                    detail=f"{phase_name(run['component'])} on {self._model(spec.key, level)}.",
                    project_id=run["project_id"],
                    run_id=run_id,
                    category=spec.audit_category,
                )
            payload: Any = None
        elif resume_payload is None:
            # A run with a checkpoint has already executed. Starting it again
            # from the first node walks the whole graph and writes every
            # artefact a second time, at the same version, over the ones a
            # reader has been looking at.
            #
            # Found on the cold chain project: a design run from three days
            # earlier still had a stale heartbeat, the poller reclaimed it, and
            # it re-extracted requirements at version 1. Twenty nine became
            # seventeen, the version did not move, the gate still said approved,
            # and the graph was left tracing to twelve ids that no longer
            # existed. Nobody asked for it and it cost a model call.
            #
            # A checkpoint is what tells the two cases apart. A queued run that
            # never started has none, and starting it is exactly what the
            # poller is for; a run that stopped mid flight has one, and the
            # honest answer is to fail it and say why rather than guess.
            existing = await graph.aget_state(config)
            if existing.values:
                await self._abandon(
                    run_id,
                    run,
                    spec,
                    "this run had already produced artefacts and stopped without recording a "
                    "decision, so it was not restarted on its own: doing so would regenerate "
                    "over what it already wrote. Continue it to go on from where it stopped.",
                )
                return

            # Once per run, and only on a genuine start: a resume re-enters here
            # with a payload. Without this a design cannot be attributed to the
            # model that produced it, which is the difference between a provider
            # comparison and a pile of runs. On the run too, not only in a
            # sentence: a person who chooses settings later has to be able to
            # tell which run used which (0014).
            level = await self._level_at_start(run, project, spec)
            async with self._pool.connection() as conn:
                model, thinking = self._setup(spec.key, level)
                await store.record_run_setup(conn, run_id, model=model, thinking=thinking)
                await store.record(
                    conn,
                    actor="system",
                    action="Run started",
                    target=str(run_id),
                    detail=f"{phase_name(run['component'])} on {self._model(spec.key, level)}.",
                    project_id=run["project_id"],
                    run_id=run_id,
                    category=spec.audit_category,
                )
            if spec.renames_project:
                await self._title_project(project, run)
            payload = spec.initial_state(run, project, notes)
        else:
            # A decision was recorded before this call. Resuming with it is
            # idempotent: if we crashed after writing it and before resuming,
            # the poller gets here and replays the same resume.
            #
            # The checkpoint is checked first, because `Command(resume=...)` on a
            # thread the checkpointer has never seen does not fail: LangGraph
            # treats it as a fresh start and the graph runs with empty state. That
            # is worse than an error, so this turns it into one. It happens when a
            # run row outlives its checkpoint, which is how it was found.
            existing = await graph.aget_state(config)
            if not existing.values:
                await self._fail_run(
                    run_id,
                    run,
                    "this run has a decision to resume but no checkpoint, so there "
                    "is no paused graph to hand it to",
                    spec,
                )
                return
            # A regeneration keeps the level its run began at.
            level = level_recorded(run.get("thinking"))
            if isinstance(resume_payload, dict) and resume_payload.get("kind") == "changes":
                await self._record_regeneration(run_id, run, spec, resume_payload, level)
            payload = Command(resume=resume_payload)

        # Every node this graph runs asks its client at the run's level.
        asked = RUN_THINKING.set(level)
        try:
            result = await graph.ainvoke(payload, config=config)
        except Exception as exc:
            log.exception("run %s raised", run_id)
            # The stage that broke has already marked itself failed with a
            # reason; the ones after it never started, and `_stop` says pending
            # about those rather than leaving them spinning.
            await self._stop(run, readable_failure(exc), action="Run failed", spec=spec)
            return
        finally:
            RUN_THINKING.reset(asked)

        await self._settle(run_id, run["project_id"], result, spec)

    async def _retire(self, run: store.Row) -> None:
        """Say out loud that a run nobody is waiting for is over.

        Left as running it describes work that is happening, and none is: the
        process that owned it is long gone. Nothing is restarted, because
        restarting is what wrote over an approved design in the first place.
        """
        why = (
            "this run went silent for longer than any run takes and was retired without "
            "being restarted. Nothing it had not already written was written."
        )
        log.warning("retiring abandoned run %s (%s)", run["id"], run["component"])
        # This component's stages and no others. A project can have a design run
        # abandoned while a code run is genuinely generating, and clearing every
        # generating row would tell the reader that live work had stopped.
        try:
            spec: ComponentSpec | None = spec_for(run["component"])
        except Exception:
            # A component this orchestrator no longer runs. Its stages cannot be
            # named, so none are touched rather than all of them.
            spec = None
        await self._stop(run, why, action="Run retired", spec=spec)

    async def _abandon(
        self, run_id: uuid.UUID, run: store.Row, spec: ComponentSpec, why: str
    ) -> None:
        """Fail a run that must not be restarted, and leave nothing spinning.

        A stage still saying generating is the one state a reader cannot act
        on, so anything this run had flipped goes back to pending: it was never
        generated and it is not being generated now.
        """
        log.warning("run %s will not be restarted: %s", run_id, why)
        await self._stop(run, why, action="Run abandoned", spec=spec)

    async def _regenerate_one(
        self, run_id: uuid.UUID, run: store.Row, project: store.Row, spec: ComponentSpec
    ) -> None:
        """Run one stage's node directly and finish.

        The node is the same object the graph is built from, so a retried
        artefact is written by exactly the code that writes a generated one. A
        second persistence path here would be the thing that drifts.
        """
        stage_id = run["only_stage"]
        factory = spec.stage_nodes().get(stage_id)
        if factory is None:
            async with self._pool.connection() as conn:
                await store.set_run_state(
                    conn, run_id, "failed", error=f"{stage_id} is not a stage a component produces"
                )
            return

        state = spec.initial_state(run, project, await self._notes(run))
        # A retry is a run of its own, and the artefact it rewrites was made by
        # whatever this records, so it is written down as a full start is; at the
        # level the account has chosen now, as a full start reads it.
        level = await self._level_at_start(run, project, spec)
        model, thinking = self._setup(spec.key, level)
        async with self._pool.connection() as conn:
            await store.record_run_setup(conn, run_id, model=model, thinking=thinking)

        asked = RUN_THINKING.set(level)
        try:
            if spec.retry_state is not None:
                state = await spec.retry_state(self._pool, state)
            await factory(self._pool, self._clients.get(spec.key))(state)
        except Exception as exc:
            log.exception("run %s failed regenerating %s", run_id, stage_id)
            async with self._pool.connection() as conn:
                await store.set_stage(
                    conn, run["project_id"], stage_id, status="failed", error=readable_failure(exc)
                )
                await store.set_run_state(conn, run_id, "failed", error=readable_failure(exc))
            return
        finally:
            RUN_THINKING.reset(asked)

        async with self._pool.connection() as conn:
            await store.set_run_state(conn, run_id, "done")
            await store.record(
                conn,
                actor="system",
                action="Regenerated one stage",
                target=stage_label(stage_id),
                detail=(
                    f"Retried at version {run['requirements_version']} "
                    f"on {self._model(spec.key, level)}."
                ),
                project_id=run["project_id"],
                run_id=run_id,
                category=spec.audit_category,
            )

    async def _title_project(self, project: Any, run: Any) -> None:
        """Replace a truncated provisional name with a real title.

        Never raises. A naming failure is not a run failure: the provisional
        name is already on screen and already reasonable, so the right response
        to a model that will not answer is to keep it and carry on.

        The rename write is inside the same `try` as the model call, for exactly
        that reason. Every other failure path in this file writes a run state
        before it returns; this one is called from `advance` with no handler
        above it, so a pool timeout or a dropped connection during the rename
        would escape to the worker's catch-all and leave the run row running and
        six stage rows generating until the poller reclaimed them ninety seconds
        later. Nothing downstream reads the new name, so losing it costs a name.
        """
        if not should_title(project["name"], run["requirements_version"], project.get("files")):
            return
        text = project["requirement_text"].strip()
        if not text:
            return

        try:
            namer = self._clients.get("c1")
            if namer is None:
                return
            title = await asyncio.wait_for(namer.name_project(text), NAMING_TIMEOUT_SECONDS)
            async with self._pool.connection() as conn:
                # A name its owner gave it while the title was being asked for
                # stands: the provisional name is the only one this replaces.
                current = await store.project_without_owner_check(conn, project["id"])
                if current is None or current["name"] != project["name"]:
                    return
                await store.patch_project(conn, project["id"], {"name": title})
                await store.record(
                    conn,
                    actor="system",
                    action="Project titled",
                    target=project["id"],
                    detail=title,
                    project_id=project["id"],
                    # `.get`, because a production run row always carries an id
                    # and the dicts the naming tests pass do not.
                    run_id=run.get("id"),
                )
        except Exception:
            log.warning("could not title project %s, keeping its name", project["id"])

    async def _notes(self, run: store.Row) -> list[str]:
        async with self._pool.connection() as conn:
            return await store.applied_notes(conn, run["project_id"], run["requirements_version"])

    async def _settle(
        self, run_id: uuid.UUID, project_id: str, result: dict[str, Any], spec: ComponentSpec
    ) -> None:
        """Write where the graph stopped: waiting on a human, or finished.

        One transaction, so the gate row, the run state, the stage flip and the
        audit entry cannot disagree with each other.
        """
        interrupts = result.get("__interrupt__") or ()
        follow_up: uuid.UUID | None = None

        async with self._pool.connection() as conn:
            if interrupts:
                first = interrupts[0]
                value = getattr(first, "value", {}) or {}
                interrupt_id = getattr(first, "id", None)
                version = value.get("requirementsVersion") or await store.current_version(
                    conn, project_id
                )
                # The interrupt names its gate: the phase's review, or the
                # design's pause for its questions, which is not a review.
                kind = value.get("kind") or spec.gate_kind

                gate = await store.open_gate(
                    conn,
                    run_id=run_id,
                    project_id=project_id,
                    requirements_version=version,
                    payload=value,
                    interrupt_id=str(interrupt_id) if interrupt_id else None,
                    kind=kind,
                )
                if str(gate["run_id"]) != str(run_id):
                    # Compared as strings: the column is a UUID and callers
                    # hand ids straight out of API JSON, and a type mismatch
                    # here read two equal ids as different.
                    # The one pending gate per project index means the insert
                    # can hand back somebody else's pending gate. Settling this
                    # run against it would attach a decision to the wrong
                    # thread, so refuse loudly instead.
                    raise RuntimeError(
                        f"run {run_id} reached its gate while gate {gate['id']} "
                        f"(run {gate['run_id']}) is still pending on this project"
                    )
                await store.set_run_state(conn, run_id, "awaiting_gate", resume_payload=None)
                if kind == QUESTIONS_GATE_KIND:
                    # Nothing below is a pause's: it reaches no review, and a
                    # paused run has nothing to drain.
                    await _pause_for_questions(
                        conn,
                        project_id=project_id,
                        run_id=run_id,
                        version=version,
                        asked=int(value.get("asked") or 0),
                        spec=spec,
                    )
                    return
                # Reaching the gate is what makes the review stage readable: it
                # is a view over the others plus the decision, not something the
                # component generates.
                await store.set_stage(
                    conn,
                    project_id,
                    spec.gate_stage_id,
                    status="complete",
                    version=version,
                    summary="Everything generated so far is waiting on your decision",
                )
                await store.record(
                    conn,
                    actor="system",
                    action=f"Reached the {stage_label(spec.gate_stage_id)} gate",
                    target=f"version {version}",
                    detail="The run is paused and will resume on the same thread when decided.",
                    project_id=project_id,
                    run_id=run_id,
                    # Filed under its own phase: without it every phase's gate read
                    # as a design event in the activity log.
                    category=spec.audit_category,
                )
            else:
                await store.set_run_state(conn, run_id, "done", resume_payload=None)
                await store.record(
                    conn,
                    actor="system",
                    action="Run finished",
                    target=str(run_id),
                    # Every phase's run ends here, and not always by an approval: a
                    # deployment run ends after an automatic release or an analysis
                    # with nothing to release. It said "the design was approved".
                    detail="The run reached its end.",
                    project_id=project_id,
                    run_id=run_id,
                    category=spec.audit_category,
                )
                # The other loop point. A note that arrived mid run was queued
                # rather than raced, and if the run then ended by approval there
                # is nothing left to drain it: it would sit unapplied forever and
                # the person who wrote it would never see it answered.
                #
                # C1 only: queued notes belong to the design axis. A finished
                # code run neither applies nor loses one; the note waits for
                # the design run that will.
                if spec.key == "c1":
                    follow_up = await self._drain_queued(conn, project_id)

        if follow_up is not None:
            # Submitted after the transaction commits, so a worker cannot pick up
            # a run row that is not visible yet.
            self.submit(follow_up)

    async def _drain_queued(self, conn: Any, project_id: str) -> uuid.UUID | None:
        """Start a run for notes that were queued while the last one was in flight."""
        queued = await store.queued_notes(conn, project_id)
        if not queued:
            return None

        version, _notes = await store.claim_next_version(
            conn, project_id, note=None, by="the platform"
        )
        await store.set_stages(
            conn,
            project_id,
            list(GENERATING_STAGE_IDS),
            status="generating",
        )
        run = await store.create_run(conn, project_id=project_id, requirements_version=version)
        await store.record(
            conn,
            actor="system",
            action="Queued a run",
            target=f"version {version}",
            detail=f"Applying {len(queued)} change note(s) that arrived during the last run.",
            project_id=project_id,
            run_id=run["id"],
        )
        return run["id"]
