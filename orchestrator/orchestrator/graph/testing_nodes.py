"""The testing phase's nodes.

Named `testing_nodes` rather than `test_nodes`, which would have been the
parallel of `code_nodes`: pytest collects `test_*.py` anywhere under the
configured paths, and this package is one of them, so the obvious name would
have turned a production module into a test module and `test_gate` into a test.

C1's two rules hold unchanged: nodes compute and persist idempotently and never
write run or gate lifecycle rows, and the gate node contains nothing but
`interrupt()` because LangGraph re-executes an interrupted node on resume.

Three things are C3's own.

**One report, three writers.** Generation, execution and quality all write
`test-report`. Generation writes it with every case at `not-run`, which is not
a placeholder: the tests exist and have not run, and that is exactly what
`not-run` means. Execution replaces the outcomes; quality adds the mutation
result. A reader watching the stages move sees the suite appear, then go green
or red, then acquire a mutation score, and each of those is true when it is
shown.

**Which stages can fail a run.** The same rule as C2: a stage is load bearing
when a later stage cannot proceed without it. Only generation and execution
qualify, because healing reads the failures execution found. Quality, healing,
scanning and remediation are leaves: a reader with a red suite and a failed
mutation pass can still decide, and a reader whose run died has nothing to
decide about. Healing being a leaf matters most of all, since the loop is the
part most likely to meet something it cannot classify.

**The upstream axis is the code version.** Every artefact this phase reads is
read at the code version the run pinned, never the latest, so code regenerated
while a testing run is in flight cannot change what the tests were run against
halfway through running them.
"""

import difflib
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

from langgraph.graph import END
from langgraph.types import Command, interrupt
from psycopg_pool import AsyncConnectionPool
from sdlc_contracts import (
    ApiContract,
    ApiContractArtefact,
    ChangedCode,
    ContractDiff,
    RemediationProposals,
    RequirementDiff,
    RequirementsArtefact,
    SprintPlan,
    SprintScope,
    TestReport,
    diff_contracts,
    diff_requirements,
)
from sdlc_contracts.openapi import to_openapi

from .. import workspaces
from ..clients.c3 import C3Client, StageNotApplicable, TargetRef
from ..db import store
from ..errors import readable_failure
from ..model_use import stage_model_use
from ..wording import readable_notes, stage_label
from .state import C3RunState

AUTHOR = "Testing agent"
CATEGORY = "testing"

#: What a testing run reads off the code axis.
CODE_KINDS = ("api-contract", "code-repository")


# ------------------------------------------------------------------- reading


async def _code_body(
    pool: AsyncConnectionPool, state: C3RunState, kind: str
) -> dict[str, Any] | None:
    async with pool.connection() as conn:
        rows = await store.artefacts_at(
            conn, state["project_id"], version=state["code_version"], kinds=(kind,)
        )
    found = rows.get(kind)
    return found["body"] if found else None


async def _test_body(
    pool: AsyncConnectionPool, state: C3RunState, kind: str
) -> dict[str, Any] | None:
    async with pool.connection() as conn:
        rows = await store.artefacts_at(
            conn, state["project_id"], version=state["test_version"], kinds=(kind,)
        )
    found = rows.get(kind)
    return found["body"] if found else None


async def _contract(pool: AsyncConnectionPool, state: C3RunState) -> ApiContract | None:
    body = await _code_body(pool, state, "api-contract")
    return ApiContractArtefact.model_validate(body).contract if body else None


async def _sprint(pool: AsyncConnectionPool, state: C3RunState) -> SprintPlan | None:
    """The plan the code was generated from, at the design version it read, as the build scoped it.

    Two hops rather than one: this run pins a code version, and that code run
    pinned a design version. Reading the latest sprint plan instead would let
    a design that moved on rewrite the acceptance criteria the tests came from.

    A code version written by applying an accepted security fix has no code run
    of its own, and inherits the provenance of the version it patched. Without
    that hop the run after a remediation has no acceptance criteria and fails
    at its first stage, which is exactly where the loop used to stop.

    The stories come from the plan, which holds their acceptance criteria, and
    which of them count is the code's scope (`scoped`): the tests followed the
    plan's proposed list whatever the build held, so a backlog story moved into
    the build got no acceptance tests, and a proposed one moved out kept them.
    """
    async with pool.connection() as conn:
        design_version = await store.design_version_for_code(
            conn, state["project_id"], state["code_version"]
        )
        if not design_version:
            return None
        rows = await store.artefacts_at(
            conn, state["project_id"], version=design_version, kinds=("sprint-plan",)
        )
        scope = await store.scope_for_code(conn, state["project_id"], state["code_version"])
    found = rows.get("sprint-plan")
    if not found:
        return None
    plan = SprintPlan.model_validate(found["body"])
    return scoped(plan, SprintScope.model_validate(scope)) if scope else plan


def scoped(plan: SprintPlan, scope: SprintScope) -> SprintPlan:
    """The plan as the build holds it: what is in scope proposed, everything else backlog.

    In the plan's own order, which runs by priority within each list, and with
    the points recounted, so the plan still says what it holds.
    """
    built = set(scope.in_scope_ids)
    stories = [*plan.proposed, *plan.backlog]
    proposed = [story for story in stories if story.id in built]
    return plan.model_copy(
        update={
            "proposed": proposed,
            "backlog": [story for story in stories if story.id not in built],
            "estimated_points": sum(story.points for story in proposed),
        }
    )


async def _choices(pool: AsyncConnectionPool, project_id: str) -> dict[tuple[str, str], store.Row]:
    """The human's testing decisions, newest per target across versions.

    Across versions for C2's reason: a choice that had to be made again after
    every regeneration would be a setting nobody could keep.
    """
    async with pool.connection() as conn:
        rows = await store.overlays(conn, project_id)
    latest: dict[tuple[str, str], store.Row] = {}
    for row in rows:
        latest[(row["kind"], row["target_id"])] = row
    return latest


async def _target(pool: AsyncConnectionPool, state: C3RunState) -> TargetRef:
    """Which repository this run works on, written out and ready to run.

    The generated monorepo unless a human said otherwise. A sample is the other
    one that matters day to day, and it is a choice rather than a guess because
    the two lanes measure different things. The overlay's value is either
    `generated` or `sample:<name>`.

    The generated case is materialised here rather than referenced, because the
    component has no database access: it works on a directory, and turning a
    version of the file store into one is this side's job. Every stage does it
    again, which costs the writing of a few dozen small files and buys the
    guarantee that what runs is exactly the version the run pinned, even if a
    regeneration landed while this run was in flight.
    """
    from ..config import get_settings

    choice = (await _choices(pool, state["project_id"])).get(("target_selection", "target"))
    value = str(choice["value"]) if choice else "generated"
    if value == "generated":
        path = await workspaces.materialise(
            pool,
            state["project_id"],
            code_version=state["code_version"],
            base=get_settings().c3_workspace_root,
        )
        return TargetRef(kind="generated", code_version=state["code_version"], path=str(path))
    kind, _, name = value.partition(":")
    return TargetRef(kind=kind, path=name)


async def _contract_at(
    pool: AsyncConnectionPool, project_id: str, version: int
) -> ApiContract | None:
    async with pool.connection() as conn:
        rows = await store.artefacts_at(conn, project_id, version=version, kinds=("api-contract",))
    found = rows.get("api-contract")
    return ApiContractArtefact.model_validate(found["body"]).contract if found else None


async def _contract_diff(
    pool: AsyncConnectionPool, state: C3RunState, previous: int
) -> ContractDiff | None:
    """What the API promised then against what it promises now.

    Half of the healing classifier's signal, and it is a pure contract function
    over two stored artefacts rather than anything this component infers.
    """
    before = await _contract_at(pool, state["project_id"], previous)
    after = await _contract_at(pool, state["project_id"], state["code_version"])
    if before is None or after is None:
        return None
    return diff_contracts(before, after)


#: A test file, by its path, at whichever stage a version filed it under: an
#: applied fix files every file of its version under the backend stage.
_TEST_PATH = re.compile(r"(^|/)__tests__/|\.(test|spec)\.[cm]?[jt]sx?$")


async def _changed_code(
    pool: AsyncConnectionPool, state: C3RunState, previous: int
) -> list[ChangedCode]:
    """The production lines that changed between the two tested versions.

    Where the honesty guard breaks the code first: a repaired test has to
    notice a fault in the code whose change made it fail, so that is where the
    fault goes. Read from the file store at both versions as the code stages
    wrote them, with the tests left out, since a test is never the code a test
    is about. Each stretch is lines of the newer version; a stretch the newer
    version only removed is marked at the line where it was.
    """
    project_id = state["project_id"]
    async with pool.connection() as conn:
        before = await store.code_files(conn, project_id, version=previous)
        after = await store.code_files(conn, project_id, version=state["code_version"])
        tests = set(
            await store.code_files(
                conn, project_id, version=previous, stage_id=store.TEST_FILE_STAGE
            )
        ) | set(
            await store.code_files(
                conn, project_id, version=state["code_version"], stage_id=store.TEST_FILE_STAGE
            )
        )
    changed: list[ChangedCode] = []
    for path, content in sorted(after.items()):
        if path in tests or _TEST_PATH.search(path) or before.get(path) == content:
            continue
        newer = content.splitlines()
        if not newer:
            continue
        older = (before.get(path) or "").splitlines()
        matcher = difflib.SequenceMatcher(a=older, b=newer, autojunk=False)
        for tag, _start, _end, first, last in matcher.get_opcodes():
            if tag == "equal":
                continue
            if last > first:
                changed.append(ChangedCode(path=path, start=first + 1, end=last))
            else:
                at = min(first + 1, len(newer))
                changed.append(ChangedCode(path=path, start=at, end=at))
    return changed


async def _design_version_for(
    pool: AsyncConnectionPool, project_id: str, code_version: int
) -> int | None:
    async with pool.connection() as conn:
        return await store.design_version_for_code(conn, project_id, code_version)


async def _requirement_diff(
    pool: AsyncConnectionPool, state: C3RunState, previous: int
) -> RequirementDiff | None:
    """What was asked for then against what is asked for now.

    The other half, and the one two hops away: a code version pins the design
    version it was generated from, so comparing requirements means comparing
    the design versions behind the two code versions rather than the newest
    one, which may have moved on since either.
    """
    project_id = state["project_id"]
    before_version = await _design_version_for(pool, project_id, previous)
    after_version = await _design_version_for(pool, project_id, state["code_version"])
    if not before_version or not after_version or before_version == after_version:
        return None
    async with pool.connection() as conn:
        before_rows = await store.artefacts_at(
            conn, project_id, version=before_version, kinds=("requirements",)
        )
        after_rows = await store.artefacts_at(
            conn, project_id, version=after_version, kinds=("requirements",)
        )
    if "requirements" not in before_rows or "requirements" not in after_rows:
        return None
    return diff_requirements(
        RequirementsArtefact.model_validate(before_rows["requirements"]["body"]),
        RequirementsArtefact.model_validate(after_rows["requirements"]["body"]),
        from_version=before_version,
        to_version=after_version,
    )


# ------------------------------------------------------------------- writing


async def _beat(pool: AsyncConnectionPool, state: C3RunState) -> None:
    """Say the run is alive before a step that may take minutes.

    Mutation and a cold Maven wrapper both outlast a poller's patience, and a
    reclaimed run would run the whole phase twice.
    """
    async with pool.connection() as conn:
        await store.heartbeat(conn, uuid.UUID(state["run_id"]))


async def _complete(
    conn: Any,
    state: C3RunState,
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
        version=state["test_version"],
        summary=summary,
        model_use=model_use,
    )


async def _persist(
    pool: AsyncConnectionPool,
    state: C3RunState,
    *,
    stage_id: str,
    kind: str,
    body: dict[str, Any],
    summary: str,
    notes: dict[str, Any],
    entries: list[tuple[str, str, str]] | None = None,
) -> None:
    """One stage's artefact and everything that says it happened, in one
    transaction, so a crash cannot leave a stage complete with nothing behind
    it.

    `entries` are extra audit rows the stage wants beside its own, as action,
    target and detail. The healing stage uses them to record every heal and
    every refusal individually: a run that says "3 healed, 1 refused" and
    cannot say which is not an audit trail.
    """
    async with pool.connection() as conn:
        await store.put_artefact(
            conn,
            project_id=state["project_id"],
            kind=kind,  # type: ignore[arg-type]
            version=state["test_version"],
            body=body,
            run_id=uuid.UUID(state["run_id"]),
        )
        await _complete(conn, state, stage_id, summary, model_use=stage_model_use(notes))
        await store.record(
            conn,
            actor=AUTHOR,
            action=f"Generated {stage_label(stage_id)}",
            target=f"test version {state['test_version']}",
            detail=readable_notes(notes),
            project_id=state["project_id"],
            run_id=uuid.UUID(state["run_id"]),
            category=CATEGORY,
        )
        for action, target, detail in entries or []:
            await store.record(
                conn,
                actor=AUTHOR,
                action=action,
                target=target,
                detail=detail,
                project_id=state["project_id"],
                run_id=uuid.UUID(state["run_id"]),
                category=CATEGORY,
            )


async def _skip(pool: AsyncConnectionPool, state: C3RunState, stage_id: str, reason: str) -> None:
    """Record a stage that had nothing to do here, and carry on.

    The reason goes in the summary rather than the error, because nothing went
    wrong: the stage was asked to do something that does not exist on this
    target. It is audited like any other outcome, since a stage that did not
    run and does not say so is indistinguishable from one that quietly did
    nothing.
    """
    async with pool.connection() as conn:
        await store.set_stage(
            conn,
            state["project_id"],
            stage_id,  # type: ignore[arg-type]
            status="skipped",
            summary=reason,
        )
        await store.record(
            conn,
            actor=AUTHOR,
            action=f"Skipped {stage_label(stage_id)}",
            target=f"test version {state['test_version']}",
            detail=reason,
            project_id=state["project_id"],
            run_id=uuid.UUID(state["run_id"]),
            category=CATEGORY,
        )


async def _fail(
    pool: AsyncConnectionPool, state: C3RunState, stage_id: str, error: Exception
) -> None:
    reason = readable_failure(error)
    async with pool.connection() as conn:
        await store.set_stage(
            conn,
            state["project_id"],
            stage_id,  # type: ignore[arg-type]
            status="failed",
            error=reason,
        )
        await store.record(
            conn,
            actor=AUTHOR,
            action=f"Failed to generate {stage_label(stage_id)}",
            target=f"test version {state['test_version']}",
            detail=reason,
            project_id=state["project_id"],
            run_id=uuid.UUID(state["run_id"]),
            category=CATEGORY,
        )


@asynccontextmanager
async def _recording_failure(
    pool: AsyncConnectionPool, state: C3RunState, stage_id: str
) -> AsyncIterator[None]:
    """Mark a load bearing stage failed on the way out, then fail the run.

    A stage that does not apply to this target is not a failure and does not
    stop the run. Test generation writes TypeScript from the API contract, so a
    Java repository gives it nothing to write, and failing there meant such a
    repository could never reach the security stage at all.
    """
    await _beat(pool, state)
    try:
        yield
    except StageNotApplicable as skip:
        await _skip(pool, state, stage_id, skip.reason)
    except Exception as error:
        await _fail(pool, state, stage_id, error)
        raise


def _leaf(stage_id: str, pool: AsyncConnectionPool, call):
    """A stage nothing downstream reads.

    Its failure is recorded and the run carries on to the gate, because a
    reader with a test report and a failed scan can still decide.
    """

    async def node(state: C3RunState) -> C3RunState:
        await _beat(pool, state)
        try:
            await call(state)
        except StageNotApplicable as skip:
            await _skip(pool, state, stage_id, skip.reason)
        except Exception as error:
            await _fail(pool, state, stage_id, error)
        return state

    node.__name__ = stage_id.replace("-", "_")
    return node


# --------------------------------------------------------------------- nodes


def make_test_generation(pool: AsyncConnectionPool, c3: C3Client):
    """Tests from the acceptance criteria and the contract.

    Load bearing: execution has nothing to run without it. The report it writes
    has every case at `not-run`, which is the literal truth rather than a
    placeholder, and the next stage replaces those outcomes with what happened.
    """

    async def test_generation(state: C3RunState) -> C3RunState:
        async with _recording_failure(pool, state, "test-generation"):
            sprint = await _sprint(pool, state)
            contract = await _contract(pool, state)
            if sprint is None or contract is None:
                # Named rather than lumped: the two come from different axes,
                # so "both or neither" would send the reader to the wrong one.
                missing = " and ".join(
                    name
                    for name, found in (("sprint plan", sprint), ("api contract", contract))
                    if found is None
                )
                raise ValueError(
                    f"this project has no {missing} for the code version this run "
                    f"pinned (v{state['code_version']}), so there is nothing to "
                    "derive tests from"
                )
            target = await _target(pool, state)
            openapi = to_openapi(contract, title="the generated app")
            outcome = await c3.generate_tests(
                target, sprint, contract, openapi, version=state["test_version"]
            )

            async with pool.connection() as conn:
                await store.put_code_files(
                    conn,
                    state["project_id"],
                    version=state["code_version"],
                    stage_id="test-generation",
                    files=outcome.files,
                )
            await _persist(
                pool,
                state,
                stage_id="test-generation",
                kind="test-report",
                body=outcome.notes.get("report", {}),
                summary=outcome.summary,
                notes={k: v for k, v in outcome.notes.items() if k != "report"},
            )
        return state

    return test_generation


def make_test_run(pool: AsyncConnectionPool, c3: C3Client):
    """The suite, executed. Load bearing: healing reads what failed.

    The generation stage's report is read first and handed back, because this
    stage writes `test-report` at the same version and the write is an upsert.
    A runner reports names and outcomes and knows nothing about stories or
    criteria, so without it the traces the generator wrote were not merely absent
    from the result, they were destroyed by the stage that replaced them.

    That silently disabled the healing classifier on every real run. Its first
    signal is what a failing test traces to, and an empty trace is an honest
    `undecided` rather than a wrong answer, so nothing failed: the loop reported
    that it could not classify what it was given and the reason was one stage
    overwriting another's work. `untraced` on the report is the count that would
    have said so.
    """

    async def test_run(state: C3RunState) -> C3RunState:
        async with _recording_failure(pool, state, "test-run"):
            target = await _target(pool, state)
            body = await _test_body(pool, state, "test-report")
            declared = TestReport.model_validate(body) if body else None
            outcome = await c3.run_tests(target, version=state["test_version"], declared=declared)
            await _persist(
                pool,
                state,
                stage_id="test-run",
                kind="test-report",
                body=outcome.artefact.model_dump(by_alias=True, mode="json"),
                summary=outcome.summary,
                notes=outcome.notes,
            )
        return state

    return test_run


def make_test_quality(pool: AsyncConnectionPool, c3: C3Client):
    """Mutation, over the files the run touched rather than the workspace."""

    async def call(state: C3RunState) -> None:
        body = await _test_body(pool, state, "test-report")
        if body is None:
            raise ValueError("no test report at this version, so there is nothing to mutate")
        report = TestReport.model_validate(body)
        target = await _target(pool, state)
        # The files the tests actually touched, not the test files: mutating a
        # test asks whether the tests test the tests. Code nothing touched is a
        # coverage finding rather than a mutation one, and every mutant in it
        # would survive by construction and cost minutes to prove it.
        scope = sorted({entry.module for entry in report.coverage if entry.lines_covered > 0})
        outcome = await c3.measure_quality(target, report, scope, version=state["test_version"])
        await _persist(
            pool,
            state,
            stage_id="test-quality",
            kind="test-report",
            body=outcome.artefact.model_dump(by_alias=True, mode="json"),
            summary=outcome.summary,
            notes=outcome.notes,
        )

    return _leaf("test-quality", pool, call)


def make_self_healing(pool: AsyncConnectionPool, c3: C3Client):
    """The honesty guarded loop, over whatever the run left failing.

    A leaf on purpose. This is the stage most likely to meet a failure it
    cannot classify, and a run that died here would take away the reader's
    chance to decide about a suite that already ran.
    """

    async def call(state: C3RunState) -> None:
        body = await _test_body(pool, state, "test-report")
        if body is None:
            raise ValueError("no test report at this version, so there is nothing to heal")
        report = TestReport.model_validate(body)
        target = await _target(pool, state)

        async with pool.connection() as conn:
            previous = await store.previous_tested_code_version(
                conn, state["project_id"], before=state["code_version"]
            )
        if previous is None:
            # Nothing to compare against, so nothing can be called brittle: the
            # trace based classifier's whole signal is the difference between
            # two versions. Said rather than guessed.
            async with pool.connection() as conn:
                await _complete(
                    conn,
                    state,
                    "self-healing",
                    "No earlier tested code version, so no failure can be called brittle yet.",
                )
            return

        contract_diff = await _contract_diff(pool, state, previous)
        requirement_diff = await _requirement_diff(pool, state, previous)
        outcome = await c3.heal(
            target,
            report,
            from_code_version=previous,
            to_code_version=state["code_version"],
            contract_diff=contract_diff,
            requirement_diff=requirement_diff,
            changed_code=await _changed_code(pool, state, previous),
            version=state["test_version"],
        )
        await _persist(
            pool,
            state,
            stage_id="self-healing",
            kind="heal-report",
            body=outcome.artefact.model_dump(by_alias=True, mode="json"),
            summary=outcome.summary,
            notes=outcome.notes,
            entries=_healing_entries(outcome.artefact),
        )

    return _leaf("self-healing", pool, call)


def make_security_scan(pool: AsyncConnectionPool, c3: C3Client):
    """Three detectors over the same code, merged with their origins kept."""

    async def call(state: C3RunState) -> None:
        target = await _target(pool, state)
        outcome = await c3.scan(target, version=state["test_version"])
        await _persist(
            pool,
            state,
            stage_id="security-scan",
            kind="validation-report",
            body=outcome.artefact.model_dump(by_alias=True, mode="json"),
            summary=outcome.summary,
            notes=outcome.notes,
        )

    return _leaf("security-scan", pool, call)


def make_remediation(pool: AsyncConnectionPool, c3: C3Client):
    """Proposals, for findings whose evidence resolved."""

    async def call(state: C3RunState) -> None:
        body = await _test_body(pool, state, "validation-report")
        if body is None:
            raise ValueError("no validation report at this version, so there is nothing to fix")
        from sdlc_contracts import ValidationReport

        report = ValidationReport.model_validate(body)
        target = await _target(pool, state)
        outcome = await c3.propose_remediation(target, report)
        plan = RemediationProposals(
            version=state["test_version"],
            generated_at=store.now(),
            # The kind, not the display name the component produced. The apply
            # path reads this to decide whether the platform owns what is being
            # patched: it writes a new code version of the generated
            # application, and a sample is a checked in fixture in the
            # component's own repository rather than code this project made.
            target=target.kind,
            proposals=outcome.artefact,
        )
        await _persist(
            pool,
            state,
            stage_id="remediation",
            kind="remediation-proposal",
            body=plan.model_dump(by_alias=True, mode="json"),
            summary=outcome.summary,
            notes=outcome.notes,
        )

    return _leaf("remediation", pool, call)


def _healing_entries(report: Any) -> list[tuple[str, str, str]]:
    """One audit row per attempt, saying which and why.

    A refusal is recorded as loudly as a heal, and carries its diff, because
    the refusals are what this component is judged on and an audit trail that
    only holds the successes is measuring its own optimism.
    """
    entries: list[tuple[str, str, str]] = []
    for attempt in report.attempts:
        if attempt.accepted:
            action = "Healed a stale test"
            detail = (
                f"classified {attempt.classification} by {attempt.classified_by}; "
                f"killed {', '.join(attempt.killed_mutant_ids) or 'a mutant'}\n"
                f"{attempt.diff.diff if attempt.diff else ''}"
            )
        elif attempt.refusal_reason is not None:
            action = "Refused a repair"
            detail = (
                f"{attempt.refusal_reason}: "
                + "; ".join(
                    f"{check.name} {'passed' if check.passed else 'failed'}, {check.detail}"
                    for check in attempt.checks
                )
                + (f"\n{attempt.diff.diff}" if attempt.diff else "")
            )
        elif attempt.classification == "regression":
            action = "Flagged a regression"
            detail = (
                f"traces to {', '.join(attempt.evidence.traced_to) or 'nothing recorded'}, "
                "none of which changed between the two versions, so the code is wrong "
                "rather than the test"
            )
        else:
            action = "Left a failure undecided"
            detail = attempt.evidence.referee_reasoning or (
                "the rules could not classify it and no referee settled it"
            )
        entries.append((action, f"{attempt.suite_path}::{attempt.test_name}", detail))
    return entries


def test_gate(state: C3RunState) -> Command[Literal["test_generation", "__end__"]]:
    """The phase gate, and deliberately nothing else.

    Everything above `interrupt()` re-runs when a human answers, so there is
    nothing above it. The payload comes from checkpointed state and the runner
    writes the gate row after `ainvoke` returns.
    """
    decision: dict[str, Any] = interrupt(
        {
            "kind": "c3-test-review",
            "projectId": state["project_id"],
            "runId": state["run_id"],
            "requirementsVersion": state["test_version"],
            "codeVersion": state["code_version"],
        }
    )

    if decision.get("kind") == "approved":
        return Command(goto=END)

    version = decision.get("version")
    if not isinstance(version, int):
        raise ValueError(
            "the changes decision carried no test version; only the store allocates "
            "version numbers, so there is nothing safe to regenerate at"
        )

    return Command(goto="test_generation", update={"test_version": version})


# The name is a pytest collection hazard, not a test.
test_gate.__test__ = False  # type: ignore[attr-defined]
