"""The code phase's nodes.

C1's two rules hold here unchanged: nodes compute and persist idempotently and
never write run or gate lifecycle rows, and the gate node contains nothing but
`interrupt()` because LangGraph re-executes an interrupted node on resume.

Three things are C2's own.

**Two version axes.** Every design artefact is read at the design version the
run pinned, never the latest, so a design regenerated while a code run is in
flight cannot change what the code was generated from halfway through
generating it. Everything C2 writes goes to the code version.

**Human choices are inputs, not overrides.** Scope, stack and arm are stored
as overlays and read here, newest per target across versions, so a decision
survives a regeneration. What the stage stores already has the decision in it,
which is why the read model can serve the artefact without knowing overlays
exist.

**One artefact, three writers.** The frontend, backend and build stages all
write `code-repository`: the first two add their manifest rows, the third adds
the build report and the push result. Each merge reads, replaces its own
stage's rows and writes back in one transaction, so two stages finishing close
together cannot lose one another's work.

Which stages can fail a run follows one rule: a stage is load bearing when a
later stage cannot proceed without it. That is the scope (the contract and the
frontend read it) and the contract (everything after it reads it). The stack,
the two code stages, the agreement and the build are leaves: nothing
downstream reads them, and a run that died on any of them would take away the
reader's chance to decide about code that already exists.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import Any, Literal

from langgraph.types import Command, interrupt
from psycopg_pool import AsyncConnectionPool
from sdlc_contracts import (
    ApiContract,
    ApiContractArtefact,
    ArchitectureGraph,
    ArchitectureRecommendation,
    CodeRepository,
    EarlierPage,
    ManifestRow,
    RequirementsArtefact,
    SprintPlan,
    SprintScope,
    WireframesArtefact,
)

from ..carrying import Carrying, carry_fixes
from ..checks.coverage import with_coverage
from ..clients.c2 import C2Client, FilesOutcome, LandOutcome, PushOutcome, StageOutcome
from ..db import store
from ..errors import readable_failure
from ..model_use import stage_model_use
from ..readmodel.assemble import apply_design_edits, selected_architecture
from ..sprints import choice_of, scope_name
from ..wording import phase_name, readable_notes, stage_label
from .state import C2RunState

#: The design artefacts a code run reads, all at the pinned design version.
DESIGN_KINDS = (
    "architecture-graph",
    "architecture-recommendation",
    "wireframes",
    "sprint-plan",
    "requirements",
)

AUTHOR = "Code agent"
CATEGORY = "code"


# ------------------------------------------------------------------- reading


async def _design_bodies(pool: AsyncConnectionPool, state: C2RunState) -> dict[str, Any]:
    async with pool.connection() as conn:
        rows = await store.artefacts_at(
            conn, state["project_id"], version=state["design_version"], kinds=DESIGN_KINDS
        )
    return {kind: row["body"] for kind, row in rows.items()}


async def _code_body(
    pool: AsyncConnectionPool, state: C2RunState, kind: str
) -> dict[str, Any] | None:
    async with pool.connection() as conn:
        rows = await store.artefacts_at(
            conn, state["project_id"], version=state["code_version"], kinds=(kind,)
        )
    found = rows.get(kind)
    return found["body"] if found else None


async def _choices(pool: AsyncConnectionPool, project_id: str) -> dict[tuple[str, str], store.Row]:
    """The human's code phase decisions, newest per target across versions.

    Across versions on purpose: choosing the LLM arm at version 2 and then
    changing the scope should regenerate version 3 with the LLM arm still
    chosen. A decision that had to be made again after every regeneration
    would not be a decision, it would be a setting nobody could keep.
    """
    async with pool.connection() as conn:
        rows = await store.overlays(conn, project_id)
    latest: dict[tuple[str, str], store.Row] = {}
    for row in rows:  # ordered by version then time, so the last write wins
        latest[(row["kind"], row["target_id"])] = row
    return latest


async def _design(pool: AsyncConnectionPool, state: C2RunState):
    """The graph, the wireframes with coverage filled in, and the sprint plan.

    Coverage is derived by the read model and never stored, so a run reading
    the wireframes artefact straight out of the table sees flows that cover no
    story and a scope traced to no screen. Deriving it here is what makes the
    contract's screen traces real.
    """
    bodies = await _design_bodies(pool, state)
    graph = (
        ArchitectureGraph.model_validate(bodies["architecture-graph"])
        if "architecture-graph" in bodies
        else ArchitectureGraph()
    )
    wireframes = (
        WireframesArtefact.model_validate(bodies["wireframes"])
        if "wireframes" in bodies
        else WireframesArtefact()
    )
    sprint = SprintPlan.model_validate(bodies["sprint-plan"]) if "sprint-plan" in bodies else None
    recommendation = (
        ArchitectureRecommendation.model_validate(bodies["architecture-recommendation"])
        if "architecture-recommendation" in bodies
        else None
    )
    async with pool.connection() as conn:
        rows = await store.overlays(conn, state["project_id"])
    # The nodes as the reviewer renamed them at this design version: renaming
    # changed the page and nothing that was built.
    graph, _ = apply_design_edits(graph, [], rows, state["design_version"])
    # The reviewer's choice, made at the design version this run reads. The
    # stored recommendation carries none (the choice is an overlay beside it),
    # so the stack proposal always fell back to the machine's own pick.
    if recommendation is not None:
        chosen = selected_architecture(rows, state["design_version"], recommendation)
        if chosen is not None:
            recommendation = recommendation.model_copy(
                update={"selected_candidate_id": chosen["value"]}
            )
    return graph, with_coverage(wireframes, sprint, graph), sprint, recommendation


async def _requirements(pool: AsyncConnectionPool, state: C2RunState) -> list[Any]:
    """The requirements as approved: the generated text with the reviewer's corrections."""
    bodies = await _design_bodies(pool, state)
    if "requirements" not in bodies:
        return []
    generated = RequirementsArtefact.model_validate(bodies["requirements"]).requirements
    async with pool.connection() as conn:
        rows = await store.overlays(conn, state["project_id"])
    _, corrected = apply_design_edits(ArchitectureGraph(), generated, rows, state["design_version"])
    return corrected


async def _scope(pool: AsyncConnectionPool, state: C2RunState) -> SprintScope | None:
    body = await _code_body(pool, state, "sprint-scope")
    return SprintScope.model_validate(body) if body else None


async def _contract(pool: AsyncConnectionPool, state: C2RunState) -> ApiContract | None:
    body = await _code_body(pool, state, "api-contract")
    return ApiContractArtefact.model_validate(body).contract if body else None


async def _arm(pool: AsyncConnectionPool, state: C2RunState) -> str:
    """The chosen contract arm. `rule` until somebody chooses otherwise: it is
    the arm that always exists and never fails."""
    choice = (await _choices(pool, state["project_id"])).get(("contract_arm_choice", "arm"))
    value = str(choice["value"]) if choice else "rule"
    return value if value in {"rule", "llm", "merged"} else "rule"


# ------------------------------------------------------------------- writing


async def _persist(
    pool: AsyncConnectionPool,
    state: C2RunState,
    *,
    stage_id: str,
    kind: str,
    outcome: StageOutcome[Any],
) -> None:
    """One stage's artefact and everything that says it happened, in one
    transaction, so a crash cannot leave a stage complete with nothing behind
    it."""
    async with pool.connection() as conn:
        await store.put_artefact(
            conn,
            project_id=state["project_id"],
            kind=kind,  # type: ignore[arg-type]
            version=state["code_version"],
            body=outcome.artefact.model_dump(by_alias=True, mode="json"),
            run_id=uuid.UUID(state["run_id"]),
        )
        await _complete(
            conn, state, stage_id, outcome.summary, model_use=stage_model_use(outcome.notes)
        )
        await store.record(
            conn,
            actor=AUTHOR,
            action=f"Generated {stage_label(stage_id)}",
            target=f"code version {state['code_version']}",
            detail=readable_notes(outcome.notes),
            project_id=state["project_id"],
            run_id=uuid.UUID(state["run_id"]),
            category=CATEGORY,
        )


async def _complete(
    conn: Any,
    state: C2RunState,
    stage_id: str,
    summary: str,
    *,
    model_use: dict[str, Any] | None = None,
) -> None:
    await store.set_stage(
        conn,
        state["project_id"],
        stage_id,  # type: ignore[arg-type]
        status="complete",
        version=state["code_version"],
        summary=summary,
        model_use=model_use,
    )
    await store.post_thread_message(
        conn,
        state["project_id"],
        kind="stage_summary",
        author=AUTHOR,
        content=summary,
        stage_id=stage_id,  # type: ignore[arg-type]
    )


async def _fail(
    pool: AsyncConnectionPool, state: C2RunState, stage_id: str, error: Exception
) -> None:
    async with pool.connection() as conn:
        await store.set_stage(
            conn,
            state["project_id"],
            stage_id,  # type: ignore[arg-type]
            status="failed",
            error=readable_failure(error),
        )
        await store.record(
            conn,
            actor=AUTHOR,
            action=f"Failed to generate {stage_label(stage_id)}",
            target=f"code version {state['code_version']}",
            detail=readable_failure(error),
            project_id=state["project_id"],
            run_id=uuid.UUID(state["run_id"]),
            category=CATEGORY,
        )


async def _beat(pool: AsyncConnectionPool, state: C2RunState) -> None:
    """Tell the poller this run is alive.

    Code stages are minutes rather than seconds, and the build is the longest
    thing this platform does, so the window is wider than C1's and the build
    bumps it again between steps.
    """
    async with pool.connection() as conn:
        await store.heartbeat(conn, uuid.UUID(state["run_id"]))


@asynccontextmanager
async def _recording_failure(
    pool: AsyncConnectionPool, state: C2RunState, stage_id: str
) -> AsyncIterator[None]:
    """Mark a load bearing stage failed on the way out, then fail the run.

    C1's shape: the run row records that the run failed, and only the node
    knows which stage broke and why. Without this the stage sits at generating
    forever, which is the one state a reader cannot act on.
    """
    await _beat(pool, state)
    try:
        yield
    except Exception as error:
        await _fail(pool, state, stage_id, error)
        raise


def _leaf(stage_id: str, pool: AsyncConnectionPool, call):
    """A stage nothing downstream reads.

    Its failure is recorded and the run carries on to the gate, because a
    reader with generated code and a failed report can still decide, and a
    reader whose run died has nothing to decide about.
    """

    async def node(state: C2RunState) -> C2RunState:
        await _beat(pool, state)
        try:
            await call(state)
        except Exception as error:
            await _fail(pool, state, stage_id, error)
        return {}

    return node


async def _merge_repository(
    pool: AsyncConnectionPool,
    state: C2RunState,
    *,
    stage_id: str,
    rows: list[ManifestRow] | None = None,
    build: Any = None,
    pointer: Any = None,
    not_pushed_reason: str | None = None,
) -> CodeRepository:
    """Add this stage's part to the one repository artefact.

    Read, replace this stage's rows, write, all inside one transaction: three
    stages write this artefact and two of them can finish close together.
    Replacing by stage rather than appending is what keeps the manifest and
    the file store naming the same set of files.
    """
    async with pool.connection() as conn:
        found = await store.artefacts_at(
            conn,
            state["project_id"],
            version=state["code_version"],
            kinds=("code-repository",),
        )
        current = (
            CodeRepository.model_validate(found["code-repository"]["body"])
            if "code-repository" in found
            else CodeRepository(version=state["code_version"])
        )
        manifest = list(current.manifest)
        if rows is not None:
            manifest = [row for row in manifest if row.stage != stage_id] + rows
        update: dict[str, Any] = {"manifest": manifest}
        if build is not None:
            update["build"] = build
        if pointer is not None:
            # Pushed now, so whatever said it was not is no longer true.
            update.update(repository=pointer, not_pushed_reason=None)
        elif not_pushed_reason is not None and current.repository is None:
            update["not_pushed_reason"] = not_pushed_reason
        # A push that fails after an earlier one took leaves the version where
        # that one put it: the commit is still there. Either side left beside
        # the other stored a record its own contract refuses, and the Code page
        # could not load. Validated before it is stored, which `model_copy`
        # alone never did.
        merged = CodeRepository.model_validate(
            current.model_copy(update=update).model_dump(by_alias=True, mode="json")
        )
        await store.put_artefact(
            conn,
            project_id=state["project_id"],
            kind="code-repository",
            version=state["code_version"],
            body=merged.model_dump(by_alias=True, mode="json"),
            run_id=uuid.UUID(state["run_id"]),
        )
    return merged


async def _store_files(
    pool: AsyncConnectionPool, state: C2RunState, *, stage_id: str, outcome: FilesOutcome
) -> FilesOutcome:
    """Store one code stage's files, with every applied security fix they keep carried in.

    Carried here because every way a code stage's files are stored comes
    through here, a whole generation and a stage retried on its own alike, so
    none can store regenerated files without the fixes. In the files'
    transaction, so a crash cannot leave them stored without the report of
    what was carried. Returns the outcome as stored: its manifest names the
    fixes each file carries.
    """
    async with pool.connection() as conn:
        carrying = await carry_fixes(
            conn,
            state["project_id"],
            stage_id=stage_id,
            version=state["code_version"],
            files=outcome.files,
            manifest=outcome.manifest,
        )
        outcome = _with_fixes(outcome, carrying)
        await store.put_code_files(
            conn,
            state["project_id"],
            version=state["code_version"],
            stage_id=stage_id,
            files=outcome.files,
        )
        await _complete(
            conn, state, stage_id, outcome.summary, model_use=stage_model_use(outcome.notes)
        )
        await store.record(
            conn,
            actor=AUTHOR,
            action=f"Generated {stage_label(stage_id)}",
            target=f"code version {state['code_version']}",
            detail=readable_notes({**outcome.notes, "files": len(outcome.files)}),
            project_id=state["project_id"],
            run_id=uuid.UUID(state["run_id"]),
            category=CATEGORY,
        )
        await _report_fixes(conn, state, stage_id, carrying)
    return outcome


def _with_fixes(outcome: FilesOutcome, carrying: Carrying) -> FilesOutcome:
    """The outcome with the carried fixes in its files and manifest, and said in its summary."""
    if not carrying.carried and not carrying.not_carried:
        return outcome
    said = []
    if carrying.carried:
        count = len(carrying.carried)
        said.append(f"{count} applied security {'fix' if count == 1 else 'fixes'} carried")
    if carrying.not_carried:
        said.append(f"{len(carrying.not_carried)} not carried")
    return replace(
        outcome,
        files=carrying.files,
        manifest=carrying.manifest,
        summary=f"{outcome.summary}, {' and '.join(said)}",
        notes={
            **outcome.notes,
            "security_fixes_carried": len(carrying.carried),
            "security_fixes_not_carried": len(carrying.not_carried),
        },
    )


async def _report_fixes(conn: Any, state: C2RunState, stage_id: str, carrying: Carrying) -> None:
    """Each fix carried or not on the record, and each one not carried in the conversation.

    The conversation is where the review is read, and a fix that did not carry
    is a decision the reviewer is now making, so it is said there with what to
    do about it.
    """
    version = state["code_version"]
    for fix in carrying.carried:
        await store.record(
            conn,
            actor=AUTHOR,
            action="Carried a security fix",
            target=f"{fix.cwe or 'a fix'} from code version {fix.version} into code version {version}",
            detail=", ".join(fix.paths)[:500],
            project_id=state["project_id"],
            run_id=uuid.UUID(state["run_id"]),
            category=CATEGORY,
        )
    for fix, reason in carrying.not_carried:
        await store.post_thread_message(
            conn,
            state["project_id"],
            kind="system",
            author=AUTHOR,
            content=(
                f"The {fix.cwe or 'security'} fix applied as code version {fix.version} was not "
                f"carried into code version {version}: {reason}. The {stage_label(stage_id)} files "
                f"are as generated. Scan this version in {phase_name('c3')} to find the weakness "
                "again if it is still there. Approving this version without the fix lets it go."
            ),
            stage_id=stage_id,  # type: ignore[arg-type]
        )
        await store.record(
            conn,
            actor=AUTHOR,
            action="Did not carry a security fix",
            target=f"{fix.cwe or 'a fix'} from code version {fix.version} into code version {version}",
            detail=reason[:500],
            project_id=state["project_id"],
            run_id=uuid.UUID(state["run_id"]),
            category=CATEGORY,
        )


# --------------------------------------------------------------------- nodes


def make_sprint_scope(pool: AsyncConnectionPool, c2: C2Client):
    """What this build covers. Load bearing: the contract and the frontend
    both read it."""

    async def sprint_scope(state: C2RunState) -> C2RunState:
        async with _recording_failure(pool, state, "sprint-scope"):
            _graph, wireframes, sprint, _ = await _design(pool, state)
            if sprint is None:
                raise ValueError(
                    "this project has no sprint plan at the design version this run "
                    "pinned, so there is nothing to scope"
                )
            outcome = await c2.derive_scope(sprint, wireframes)

            # The human's in and out decisions are inputs to the stage, so what
            # is stored already has them: the read model never has to know that
            # overlays exist. Each names the sprint it was planned in, and the
            # scope is named for the sprints it now covers.
            choices = await _choices(pool, state["project_id"])
            stories = []
            for story in outcome.artefact.stories:
                choice = choices.get(("story_scope", story.id))
                if choice is None:
                    stories.append(story)
                    continue
                decided = choice_of(choice["value"])
                stories.append(
                    story.model_copy(
                        update={
                            "in_scope": decided.in_scope,
                            "sprint": decided.sprint,
                            "decided_by": choice["by"],
                        }
                    )
                )
            scope = outcome.artefact.model_copy(
                update={
                    "stories": stories,
                    "sprint_name": scope_name(
                        outcome.artefact.sprint_name,
                        (story.sprint for story in stories if story.in_scope),
                    ),
                }
            )
            await _persist(
                pool,
                state,
                stage_id="sprint-scope",
                kind="sprint-scope",
                outcome=StageOutcome(artefact=scope, summary=outcome.summary, notes=outcome.notes),
            )
        return {"attempt": state.get("attempt", 0) + 1}

    return sprint_scope


def make_tech_stack(pool: AsyncConnectionPool, c2: C2Client):
    """The stack proposal. A leaf: the generators build MERN today whatever is
    selected, so nothing downstream reads this and a failure costs the
    proposal rather than the run."""

    async def call(state: C2RunState) -> None:
        graph, _w, _s, recommendation = await _design(pool, state)
        outcome = await c2.propose_stack(graph, recommendation)
        # The human's selection is not applied here, unlike the scope and the
        # arm. Nothing downstream reads the stack (the generators build MERN
        # whatever is selected), so choosing one changes a decision rather than
        # an output: the read model lays it over the proposal, exactly as C1
        # does with the architecture selection, and choosing costs no run.
        await _persist(pool, state, stage_id="tech-stack", kind="tech-stack", outcome=outcome)

    return _leaf("tech-stack", pool, call)


def make_api_contract(pool: AsyncConnectionPool, c2: C2Client):
    """The research core's artefact. Load bearing: everything after it reads
    the contract."""

    async def api_contract(state: C2RunState) -> C2RunState:
        async with _recording_failure(pool, state, "api-contract"):
            graph, wireframes, _sprint, _ = await _design(pool, state)
            scope = await _scope(pool, state)
            if scope is None:
                raise ValueError("the scope stage produced nothing, so there is nothing to infer")
            outcome = await c2.infer_contract(
                state["code_version"],
                graph,
                wireframes,
                scope,
                arm=await _arm(pool, state),  # type: ignore[arg-type]
            )
            await _persist(
                pool, state, stage_id="api-contract", kind="api-contract", outcome=outcome
            )
        return {}

    return api_contract


async def _earlier_pages(pool: AsyncConnectionPool, state: C2RunState) -> list[EarlierPage]:
    """What the previous generation made of each page, for an unchanged page to keep.

    The newest earlier version the generator wrote pages at. A version an
    applied fix wrote is passed over: it carries the record of the version it
    patched, but not that version's files as the generator wrote them, and the
    fix itself is carried into the new code separately. So is a version whose
    page stage made nothing. A page that was itself kept from an earlier
    version passes on the version that wrote it, so "no change since" names
    where it came from.
    """
    async with pool.connection() as conn:
        fixed = await store.patch_provenance(conn, state["project_id"])
        for version in range(state["code_version"] - 1, 0, -1):
            if version in fixed:
                continue
            found = await store.artefacts_at(
                conn, state["project_id"], version=version, kinds=("code-repository",)
            )
            if "code-repository" not in found:
                continue
            manifest = CodeRepository.model_validate(found["code-repository"]["body"]).manifest
            rows = [
                row
                for row in manifest
                if row.stage == "frontend-code"
                and row.written_from
                and row.generator in ("rule", "model")
            ]
            if not rows:
                continue
            files = await store.code_files(
                conn, state["project_id"], version=version, stage_id="frontend-code"
            )
            return [
                EarlierPage(
                    path=row.path,
                    written_from=row.written_from,
                    generator=row.generator,  # type: ignore[arg-type]
                    content=files[row.path],
                    version=row.reused_from_version or version,
                )
                for row in rows
                if row.path in files
            ]
    return []


def make_frontend_code(pool: AsyncConnectionPool, c2: C2Client):
    async def call(state: C2RunState) -> None:
        contract = await _contract(pool, state)
        scope = await _scope(pool, state)
        if contract is None or scope is None:
            raise ValueError("there is no contract to generate a frontend from")
        from ..config import get_settings

        _graph, wireframes, _sprint, _ = await _design(pool, state)
        async with pool.connection() as conn:
            project = await store.project_without_owner_check(conn, state["project_id"])
        requirements = await _requirements(pool, state)
        outcome = await c2.generate_frontend(
            (project or {}).get("name") or "Generated app",
            contract,
            wireframes,
            scope,
            design_version=state["design_version"],
            arm=await _arm(pool, state),
            # The page writer, told what each page's flow was drawn for.
            fill=get_settings().c2_page_fill,
            requirements=requirements,
            earlier=await _earlier_pages(pool, state),
        )
        stored = await _store_files(pool, state, stage_id="frontend-code", outcome=outcome)
        await _merge_repository(pool, state, stage_id="frontend-code", rows=stored.manifest)

    return _leaf("frontend-code", pool, call)


def make_backend_code(pool: AsyncConnectionPool, c2: C2Client):
    async def call(state: C2RunState) -> None:
        contract = await _contract(pool, state)
        if contract is None:
            raise ValueError("there is no contract to generate a backend from")
        outcome = await c2.generate_backend(contract, arm=await _arm(pool, state))
        stored = await _store_files(pool, state, stage_id="backend-code", outcome=outcome)
        await _merge_repository(pool, state, stage_id="backend-code", rows=stored.manifest)

    return _leaf("backend-code", pool, call)


def make_contract_agreement(pool: AsyncConnectionPool, c2: C2Client):
    """Validation before execution: the novelty, and a leaf.

    After both code stages on purpose, so a leaf failure upstream yields an
    honest report about what is missing rather than no report at all.
    """

    async def call(state: C2RunState) -> None:
        contract = await _contract(pool, state)
        if contract is None:
            raise ValueError("there is no contract to check the code against")
        async with pool.connection() as conn:
            sources = await store.code_files(
                conn, state["project_id"], version=state["code_version"]
            )
        outcome = await c2.check_agreement(contract, sources)
        await _persist(
            pool,
            state,
            stage_id="contract-agreement",
            kind="contract-agreement",
            outcome=outcome,
        )

    return _leaf("contract-agreement", pool, call)


async def _github_token(pool: AsyncConnectionPool, project_id: str) -> str | None:
    """The owner's GitHub token, decrypted, or None.

    None is an outcome rather than an error at every step: no project, no
    connection, no encryption key, or a token that will not decrypt all mean
    the same thing to the build stage, which records that nothing was pushed
    and why instead of inventing a repository URL.
    """
    from ..config import get_settings
    from ..crypto import decrypt

    async with pool.connection() as conn:
        project = await store.project_without_owner_check(conn, project_id)
        if project is None:
            return None
        ciphertext = await store.get_secret(conn, f"{project['owner_id']}:github")
    if ciphertext is None:
        return None
    try:
        return decrypt(get_settings().secret_key, ciphertext)
    except Exception:
        return None


def make_build(pool: AsyncConnectionPool, c2: C2Client):
    """Install, typecheck, test, then push. A leaf: a failed build is a
    reported outcome, and the reader decides at the gate."""

    async def call(state: C2RunState) -> None:
        async with pool.connection() as conn:
            sources = await store.code_files(
                conn, state["project_id"], version=state["code_version"]
            )
            project = await store.project_without_owner_check(conn, state["project_id"])

        loop = asyncio.get_running_loop()

        def on_step(_name: str) -> None:
            # The sandbox runs in a worker thread, so the heartbeat is handed
            # back to the loop rather than awaited here. Without it a build
            # whose steps outlast the stale window is reclaimed and run twice.
            asyncio.run_coroutine_threadsafe(_beat(pool, state), loop)

        outcome = await c2.build(sources, on_step=on_step)

        token = await _github_token(pool, state["project_id"])
        name = await _repository_for(
            pool, state["project_id"], (project or {}).get("name") or "generated-app"
        )
        # To the version's own branch: every version went to the default branch,
        # unreviewed and failing ones included. The default branch moves to a
        # version when its review approves it (`make_land`).
        try:
            push = await c2.push(
                sources,
                name=name,
                token=token,
                message=f"Generate code version {state['code_version']}",
                branch=version_branch(state["code_version"]),
            )
        except Exception as error:
            # GitHub refusing (a token without the workflow scope, a 5xx) is an
            # outcome as no connection is. Raised, it took the finished build
            # with it: no build report was stored, and Push and Download were
            # not offered.
            push = PushOutcome(reason=f"not pushed: {readable_failure(error)}")

        await _merge_repository(
            pool,
            state,
            stage_id="build",
            build=outcome.artefact,
            pointer=push.pointer,
            not_pushed_reason=push.reason,
        )
        summary = outcome.summary + (
            f". Pushed to {push.pointer.url}" if push.pointer else f". {push.reason}"
        )
        async with pool.connection() as conn:
            await _complete(conn, state, "build", summary)
            await store.record(
                conn,
                actor=AUTHOR,
                action="Built the generated code",
                target=f"code version {state['code_version']}",
                detail=readable_notes(outcome.notes),
                project_id=state["project_id"],
                run_id=uuid.UUID(state["run_id"]),
                category=CATEGORY,
            )

    return _leaf("build", pool, call)


def _repository_name(project_name: str, project_id: str) -> str:
    """A GitHub repository name of this project's own: its name, then its id.

    The name alone was the repository, so every project called "Calculator"
    pushed to one repository and each push replaced the last; a 422 "already
    exists" was taken for this project pushing again. The id makes it this
    project's. Lowercase, hyphens, nothing else: GitHub accepts more, but a name
    with a space in it comes back from the API renamed, and a pointer that does
    not match what was asked for is worse than a plain one. At most 100
    characters, GitHub's limit.
    """
    cleaned = "".join(
        character if character.isalnum() else "-" for character in project_name.lower()
    ).strip("-")
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    suffix = project_id.removeprefix("p_").lower()
    base = (cleaned or "generated-app")[: 100 - len(suffix) - 1].rstrip("-")
    return f"{base}-{suffix}"


async def _repository_for(pool: AsyncConnectionPool, project_id: str, project_name: str) -> str:
    """The repository this project pushes to.

    The one it pushed to before when that one is its own, so a released project
    keeps its repository and the deployment layer committed on top of it; any
    other project gets a name of its own (`_repository_name`).
    """
    async with pool.connection() as conn:
        pushed = await store.pushed_repository(conn, project_id)
    return pushed["name"] if pushed else _repository_name(project_name, project_id)


def version_branch(version: int) -> str:
    """The branch a code version is pushed to: `code/v3`."""
    return f"code/v{version}"


def make_land(pool: AsyncConnectionPool, c2: C2Client):
    """After the review approves a version, the default branch carries it.

    Every version goes to a branch of its own, so nothing unreviewed is on the
    default branch, and this moves it to the approved one. Nothing here fails
    the run: the approval stands whatever GitHub says, and what happened is
    written to the thread and the audit log, with the way on when it did not.
    """

    async def call(state: C2RunState) -> dict[str, Any]:
        project_id, version = state["project_id"], state["code_version"]
        async with pool.connection() as conn:
            found = await store.artefacts_at(
                conn, project_id, version=version, kinds=("code-repository",)
            )
        body = found.get("code-repository")
        pointer = CodeRepository.model_validate(body["body"]).repository if body else None
        # Nothing pushed, or pushed to the default branch already, as every
        # version was before versions had branches of their own.
        if pointer is None or not pointer.branch or pointer.branch == pointer.default_branch:
            return {}
        try:
            landed = await c2.land(
                pointer,
                token=await _github_token(pool, project_id),
                message=f"Code version {version}, approved",
            )
        except Exception as error:  # a refusal is reported, never raised: see above
            landed = LandOutcome(reason=readable_failure(error))
        branch = pointer.default_branch
        async with pool.connection() as conn:
            if landed.commit_sha:
                how = {
                    "fast-forward": f"{branch} moved to {pointer.branch}",
                    "landing commit": (
                        f"{branch} had moved on since the version was pushed, so a commit "
                        f"carrying exactly code version {version} went on top of it"
                    ),
                    "already there": f"{branch} was already at code version {version}",
                }.get(landed.how, landed.how)
                await store.record(
                    conn,
                    actor=AUTHOR,
                    action="Landed the approved code",
                    target=f"code version {version}",
                    detail=f"{how} ({landed.commit_sha[:12]}).",
                    project_id=project_id,
                    run_id=state["run_id"],
                    category="code",
                )
                content = f"{branch} now carries code version {version}: {how}."
            else:
                await store.record(
                    conn,
                    actor=AUTHOR,
                    action="Could not land the approved code",
                    target=f"code version {version}",
                    detail=(landed.reason or "GitHub gave no reason")[:500],
                    project_id=project_id,
                    run_id=state["run_id"],
                    category="code",
                )
                content = (
                    f"{branch} could not move to code version {version}: "
                    f"{landed.reason or 'GitHub gave no reason'}. The version is on "
                    f"{pointer.branch}; Push this version on Build lands it."
                )
            await store.post_thread_message(
                conn,
                project_id,
                kind="system",
                author=AUTHOR,
                content=content,
                stage_id="code-review",
            )
        return {}

    return call


def code_gate(state: C2RunState) -> Command[Literal["sprint_scope", "code_land", "__end__"]]:
    """The phase gate, and deliberately nothing else.

    Everything above `interrupt()` re-runs when a human answers, so there is
    nothing above it. The payload comes from checkpointed state and the runner
    writes the gate row after `ainvoke` returns.
    """
    decision: dict[str, Any] = interrupt(
        {
            "kind": "c2-code-review",
            "projectId": state["project_id"],
            "runId": state["run_id"],
            "requirementsVersion": state["code_version"],
            "designVersion": state["design_version"],
        }
    )

    if decision.get("kind") == "approved":
        # The default branch carries the approved version (`make_land`).
        return Command(goto="code_land")

    # Changes requested: regenerate at the code version the store allocated
    # when the decision was recorded. Never computed here, for C1's reason:
    # only the store allocates version numbers, and a guessed one collides
    # with the next real regeneration.
    version = decision.get("version")
    if not isinstance(version, int):
        raise ValueError(
            "the changes decision carried no code version; only the store allocates "
            "version numbers, so there is nothing safe to regenerate at"
        )

    return Command(goto="sprint_scope", update={"code_version": version})
