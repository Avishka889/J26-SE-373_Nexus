"""The testing read model, the runs that move it, and the two decision tiers.

The code routes' shape for the testing phase, with one thing this phase needs
that neither of the others does: **decisions at two levels**.

The phase decision at `test-review` is the same gate C1 and C2 have. Above it
sit per item decisions a reader makes while still inside the stage: dismissing
a security finding as not applicable here, accepting or rejecting a proposed
fix, overriding what the healing loop did with one test. Those are overlays, so
the machine's own output is never edited, and every one carries who decided and
when.

**Why a dismissal needs a reason and an acceptance does not.** Accepting a
finding is agreeing with the machine, and the machine's reasoning is already on
the artefact. Dismissing one is overruling it, and a security finding overruled
without a note is a decision nobody can review later, which is exactly the
decision most worth reviewing.

**Why a run is explicit.** A testing run installs packages, runs a suite, and
may run a mutation pass that takes forty minutes. Nothing starts one by being
navigated to: the reader presses run, and only on a project whose code has been
approved, because testing an unapproved build measures something nobody agreed
to ship.
"""

import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sdlc_contracts import (
    CODE_ARTEFACT_KINDS,
    TEST_GENERATING_STAGE_IDS,
    TEST_STAGE_IDS,
    DiffSpan,
    HealAttempt,
    HealReport,
    RemediationProposals,
    TestCase,
    TestReport,
    TestSnapshot,
    ValidationReport,
)

from ..components import spec_for
from ..db import store
from ..errors import Conflict, NotFound
from ..patching import PatchRefused, apply_all, apply_to, reverse
from ..readmodel.testing import (
    DEFAULT_TARGET,
    GATE_KIND,
    compose_testing,
    heal_decisions,
    measured_the_generated_app,
    prefetch_testing,
    selected_target,
)
from .code import push_stored_version
from .continuing import continue_if_stopped_here
from .deps import Actor, Components, Db, Owner, Supervisor, require_project
from .stale_reviews import close_stale_review

router = APIRouter(tags=["testing"])


class FindingIn(BaseModel):
    """A per finding decision, inside the stage."""

    decision: str = Field(pattern="^(accepted|dismissed)$")
    note: str | None = None


class ProposalIn(BaseModel):
    """A per proposal decision, inside the stage."""

    decision: str = Field(pattern="^(accepted|dismissed)$")
    note: str | None = None


class HealIn(BaseModel):
    """A reader overriding what the healing loop did with one test."""

    decision: str = Field(pattern="^(kept|reverted)$")
    note: str | None = None


class TestDecisionIn(BaseModel):
    """A reader's decision about one failing generated test no repair will fix."""

    decision: str = Field(pattern="^(quarantined|restored|rewrite)$")
    note: str | None = None


class ApplyIn(BaseModel):
    note: str | None = None


class TargetIn(BaseModel):
    """Which repository this project's testing runs work on."""

    target: str = Field(min_length=1)


class DecisionIn(BaseModel):
    kind: str = Field(pattern="^(approved|changes)$")
    note: str | None = None


async def _code_moved_past(conn: Any, project_id: str, gate: store.Row) -> tuple[int, int] | None:
    """The code version the waiting run tested and the current one, if the code moved on."""
    run = await store.get_run(conn, gate["run_id"])
    tested = int((run or {}).get("source_version") or 0)
    current = await store.current_code_version(conn, project_id)
    if tested and current > tested:
        return tested, current
    return None


def _failing_tests(snapshot: TestSnapshot) -> list[str]:
    """The generated app's tests that failed in this version's run, by name.

    Only the generated app's. A sample carries its failures on purpose, since
    they are what the healing loop is measured on, and nothing deploys a sample.
    A repair does not count as a pass here, kept or not: this run measured the
    test before it. A kept repair is in the stored test file (`decide_heal`), so
    the run that requesting changes starts measures it, and that run's report is
    the one an approval reads.
    """
    # What the run measured, as its report names it, not the newest choice.
    if not measured_the_generated_app(snapshot.tests):
        return []
    assert snapshot.tests is not None
    # A quarantined test is skipped from here on, with its reason on the
    # record: the review is not held up by it, and the staging build reads the
    # same skipped file.
    set_aside = {one.test_id for one in snapshot.heal_decisions if one.decision == "quarantined"}
    return [
        case.name
        for suite in snapshot.tests.suites
        for case in suite.cases
        if case.outcome in ("failed", "errored") and case.id not in set_aside
    ]


#: An app's own run, as the harness names it when a repository has several.
_APP_RUN = re.compile(r"^tests \((.+)\)$")

_STEP_WORDS = {"failed": "failed", "timed-out": "timed out", "not-run": "did not run"}


def _unproven(snapshot: TestSnapshot) -> list[str]:
    """What this run did not prove, which approving over needs a note for.

    Only a failed case held an approval up, so a workspace that would not
    install returned a report with no tests in it, and approving it read as
    every proof passing. Worded as the page words it (`unprovenIn`, the testing
    `model/view.ts`). A skipped generated test nobody quarantined is a
    criterion still a todo: nothing this platform writes skips a test of its
    own accord.
    """
    if not measured_the_generated_app(snapshot.tests):
        return []
    report = snapshot.tests
    assert report is not None
    cases = report.cases
    concerns: list[str] = []
    if not any(case.outcome in ("passed", "failed", "errored") for case in cases):
        stopped = next((step for step in report.steps if step.outcome != "passed"), None)
        concerns.append(
            f"no test ran: {stopped.name} {_STEP_WORDS.get(stopped.outcome, stopped.outcome)}"
            if stopped is not None
            else "no test ran"
        )
    else:
        for step in report.steps:
            app = _APP_RUN.match(step.name)
            if app and not any(
                suite.path.startswith(f"{app.group(1)}/") for suite in report.suites
            ):
                concerns.append(f"{app.group(1)} produced no test report")
    quarantined = {one.test_id for one in snapshot.heal_decisions if one.decision == "quarantined"}
    unwritten = sum(1 for case in cases if case.outcome == "skipped" and case.id not in quarantined)
    if unwritten:
        concerns.append(
            f"{unwritten} acceptance {'criterion' if unwritten == 1 else 'criteria'} declared "
            "and not written"
        )
    return concerns


async def _snapshot(conn: Any, project_id: str, owner: str) -> TestSnapshot:
    """The phase as the request leaves it, read in a few round trips (see design's)."""
    async with store.reads_only(conn):
        await prefetch_testing(conn, project_id, owner)
        project = await require_project(conn, project_id, owner)
        return await compose_testing(conn, project)


async def _proposals(conn: Any, project_id: str, version: int) -> RemediationProposals:
    found = await store.artefacts_at(
        conn, project_id, version=version, kinds=("remediation-proposal",)
    )
    if "remediation-proposal" not in found:
        raise Conflict("nothing has been proposed yet, so there is no fix to apply")
    return RemediationProposals.model_validate(found["remediation-proposal"]["body"])


async def _decision_for(conn: Any, project_id: str, version: int, target: str) -> str:
    """What a person decided about one proposal, from the overlays.

    Read rather than trusted from the artefact: the artefact is what the
    machine produced and the overlay is what a person decided, and keeping the
    two apart is what lets the study count how often a reader overruled the
    pipeline.
    """
    rows = await store.overlays(conn, project_id)
    for row in rows:
        if (
            row["kind"] == "remediation_decision"
            and row["target_id"] == target
            and row["version"] == version
        ):
            return str((row["value"] or {}).get("decision", ""))
    return ""


async def _applied(conn: Any, project_id: str, proposal_id: str) -> tuple[int, int] | None:
    """The test version a proposal was applied at, and the code version it made.

    Read from the overlay rather than passed in, because a re-verification is
    asked for after a second run has moved the current test version on, and the
    proposal being asked about belongs to the version it was proposed at.
    """
    rows = await store.overlays(conn, project_id)
    for row in rows:
        if row["kind"] == "remediation_decision" and row["target_id"] == proposal_id:
            applied = (row["value"] or {}).get("appliedCodeVersion")
            if applied:
                return int(row["version"]), int(applied)
    return None


async def _applied_as(conn: Any, project_id: str, version: int, target: str) -> int | None:
    """The code version one proposal of this test version was applied as, if it was."""
    for row in await store.overlays(conn, project_id):
        if (
            row["kind"] == "remediation_decision"
            and row["target_id"] == target
            and row["version"] == version
        ):
            made = (row["value"] or {}).get("appliedCodeVersion")
            return int(made) if made else None
    return None


async def _fix_awaiting_its_run(conn: Any, project_id: str) -> tuple[str, int] | None:
    """The applied fix that wrote the current code version, while no testing run
    has measured it, and that version.

    Only the current version. Testing runs on the newest code, so a fix's
    version that newer code has passed can never be measured, and waiting for
    it would refuse every fix after it for good.
    """
    current = await store.current_code_version(conn, project_id)
    if any(row["source_version"] == current for row in await _c3_runs(conn, project_id)):
        return None
    for row in await store.overlays(conn, project_id):
        if (
            row["kind"] == "remediation_decision"
            and int((row["value"] or {}).get("appliedCodeVersion") or 0) == current
        ):
            return str(row["target_id"]), current
    return None


async def _c3_runs(conn: Any, project_id: str) -> list[store.Row]:
    """This project's testing runs, newest first."""
    return [row for row in await store.project_runs(conn, project_id) if row["component"] == "c3"]


async def _reports(conn: Any, project_id: str, version: int) -> tuple[Any, Any] | None:
    """The two reports one testing run produced, or nothing if it produced neither."""
    found = await store.artefacts_at(
        conn, project_id, version=version, kinds=("validation-report", "test-report")
    )
    if "validation-report" not in found or "test-report" not in found:
        return None
    return (
        ValidationReport.model_validate(found["validation-report"]["body"]),
        TestReport.model_validate(found["test-report"]["body"]),
    )


async def _code_is_approved(conn: Any, project_id: str) -> bool:
    """Whether a person has agreed to the build that would be tested.

    An approval at the code gate is the ordinary answer. The other one is a
    version that exists only because a person accepted a security fix over a
    version they had already approved: the build was approved, the patch was
    approved, and there is no third thing to ask about. Without this the loop
    stops dead after an apply, because the new version has no code gate of its
    own and nothing can open one, so the fix could never be re-verified.

    The walk is over recorded patches rather than arithmetic on version
    numbers. A fix applied to a fix is two steps back, and a version that
    reached the store some other way stops the walk and has to be approved.
    """
    version = await store.current_code_version(conn, project_id)
    return await store.code_version_is_approved(conn, project_id, version)


@router.get("/projects/{project_id}/testing")
async def get_testing(project_id: str, conn: Db, owner: Owner) -> TestSnapshot:
    return await _snapshot(conn, project_id, owner)


@router.get("/projects/{project_id}/testing/targets")
async def list_targets(
    project_id: str, conn: Db, owner: Owner, components: Components
) -> list[dict[str, str]]:
    """What a reader may point this phase at.

    Asked of the component rather than listed here. Which samples exist is a
    fact about its fixtures directory, and a second copy of that list on this
    side would go stale the first time one was added, in the direction that
    offers a target no run can resolve.
    """
    await require_project(conn, project_id, owner)
    return components["c3"].targets()


@router.post("/projects/{project_id}/testing/target")
async def choose_target(
    project_id: str, body: TargetIn, conn: Db, owner: Owner, components: Components, actor: Actor
) -> TestSnapshot:
    """Point this project's testing runs at a repository.

    **Why this exists at all.** The generated application is a MERN
    repository and always will be, so the Java lane, the bytecode scanner and
    the seeded weaknesses the security stage is measured on are unreachable
    from it. The choice was in the overlay vocabulary and the graph read it
    from the first day; what was missing was any way for a person to make it,
    which meant the one target where three detection arms have something to say
    could only be selected by editing the database.

    Refused when the component does not offer it, rather than accepted and
    discovered three stages into a run. A target that does not resolve is a
    stage that fails after somebody chose it, and the choice is the moment to
    say so.

    Not per version. A choice that had to be made again after every
    regeneration is a setting nobody can keep, which is why the graph reads the
    newest across versions and why this writes at the current one.
    """
    await require_project(conn, project_id, owner)
    offered = {one["id"] for one in components["c3"].targets()}
    if body.target not in offered:
        raise Conflict(
            f"{body.target!r} is not a target this component offers. "
            f"It answers to: {', '.join(sorted(offered))}"
        )

    # A working run only. One paused at its gate has taken every measurement it
    # is going to take and is waiting on a person, so a setting that affects
    # only the next run may change under it; counting it blocked choosing a
    # target until the gate was decided, which can be as long as a reader likes.
    if await store.active_run(conn, project_id, component="c3", states=store.WORKING_RUN_STATES):
        raise Conflict(
            "a testing run is measuring this project right now, and changing the target "
            "under it would mean the report named one repository and measured another"
        )

    await store.put_overlay(
        conn,
        project_id=project_id,
        version=await store.current_test_version(conn, project_id) or 1,
        kind="target_selection",
        target_id="target",
        value=body.target,
        by=actor,
    )
    await store.record(
        conn,
        actor=actor,
        action="Chose what to test",
        target=body.target,
        detail="Testing runs from now on work on this repository.",
        project_id=project_id,
        category="testing",
    )
    return await _snapshot(conn, project_id, owner)


@router.post("/projects/{project_id}/testing/run")
async def start_run(
    project_id: str, conn: Db, owner: Owner, supervisor: Supervisor, actor: Actor
) -> TestSnapshot:
    """Generate, run, measure, heal, scan and propose, then stop at the gate."""
    await require_project(conn, project_id, owner)

    # Only the generated application. The reason for this gate is that testing
    # an unapproved build measures something nobody agreed to ship, and a
    # checked in sample is not this project's build: it is a fixture with
    # seeded weaknesses, and refusing to scan it because the project's own code
    # is unapproved would be this phase guarding a version it is not about.
    overlay_rows = await store.overlays(conn, project_id)
    if selected_target(overlay_rows) == DEFAULT_TARGET and not await _code_is_approved(
        conn, project_id
    ):
        raise Conflict(
            "this project's code has not been approved, so testing it would measure "
            "a build nobody agreed to ship"
        )

    await store.lock_run_axis(conn, project_id, "c3")
    gate = await store.pending_gate(conn, project_id=project_id, kind=GATE_KIND)
    if gate is not None:
        moved = await _code_moved_past(conn, project_id, gate)
        if moved is None:
            raise Conflict(
                "a testing review is waiting on this project; decide it before starting another run"
            )
        # The review is of code that is no longer current. The page did not
        # offer to decide it and this refused a new run while it waited, so a
        # fix applied before the review was decided left nothing to press.
        tested, current = moved
        await close_stale_review(
            conn,
            project_id,
            gate,
            by=actor,
            reason=(
                f"These tests ran on code version {tested}, and the code is at version "
                f"{current} now, so this review closes and the tests run on version {current}."
            ),
            stage_id="test-review",
            category="testing",
            what=f"test version {gate['requirements_version']}",
        )

    if await store.active_run(conn, project_id, component="c3") is not None:
        raise Conflict("a testing run is already in flight on this project")

    code_version = await store.current_code_version(conn, project_id)
    test_version = await store.next_test_version(conn, project_id)
    await store.seed_test_stages(conn, project_id)
    await store.set_stages(conn, project_id, list(TEST_GENERATING_STAGE_IDS), status="generating")
    run = await store.create_run(
        conn,
        project_id=project_id,
        requirements_version=test_version,
        component="c3",
        source_version=code_version,
    )
    await store.record(
        conn,
        actor=actor,
        action="Started a testing run",
        target=f"test version {test_version}",
        detail=f"Testing code version {code_version}.",
        project_id=project_id,
        run_id=run["id"],
        category="testing",
    )
    if supervisor is not None:
        from .projects import _after_commit

        _after_commit(supervisor, run["id"])
    return await _snapshot(conn, project_id, owner)


@router.post("/projects/{project_id}/testing/stages/{stage_id}/retry")
async def retry_stage(
    project_id: str,
    stage_id: str,
    conn: Db,
    owner: Owner,
    supervisor: Supervisor,
    actor: Actor,
) -> TestSnapshot:
    """Re-run one stage at the version already produced.

    A whole run would rewrite four artefacts the reader has read in order to
    fix the one they asked about, and in this phase one of those artefacts is a
    forty minute mutation pass.
    """
    if stage_id not in TEST_STAGE_IDS:
        raise NotFound("stage", stage_id)
    if stage_id not in spec_for("c3").stage_nodes():
        raise Conflict(f"{stage_id} is the gate; there is nothing to re-run. Decide it instead.")
    await require_project(conn, project_id, owner)
    version = await store.current_test_version(conn, project_id)
    if not version:
        raise Conflict("nothing has been tested yet, so there is no stage to retry")
    if await store.version_is_approved(conn, project_id, gate_kind=GATE_KIND, version=version):
        raise Conflict(
            f"test version {version} was approved, so its stages are settled. Run the "
            "tests again to measure a new version instead."
        )
    await store.lock_run_axis(conn, project_id, "c3")
    # Try again on the stage that stopped the phase's run goes on with that
    # run, to the review, rather than regenerating the one stage and stopping.
    continued = await continue_if_stopped_here(conn, project_id, spec_for("c3"), stage_id, by=actor)
    if continued is not None:
        if supervisor is not None:
            from .projects import _after_commit

            _after_commit(supervisor, continued["id"])
        return await _snapshot(conn, project_id, owner)
    if await store.active_run(conn, project_id, component="c3", states=store.WORKING_RUN_STATES):
        raise Conflict(
            "a testing run is already working on this project; wait for it to finish "
            "before retrying a stage"
        )

    latest = await store.latest_run(conn, project_id)
    code_version = (
        latest["source_version"]
        if latest is not None and latest["component"] == "c3" and latest["source_version"]
        else await store.current_code_version(conn, project_id)
    )
    await store.set_stage(conn, project_id, stage_id, status="generating")
    run = await store.create_run(
        conn,
        project_id=project_id,
        requirements_version=version,
        component="c3",
        only_stage=stage_id,
        source_version=code_version,
    )
    if supervisor is not None:
        from .projects import _after_commit

        _after_commit(supervisor, run["id"])
    return await _snapshot(conn, project_id, owner)


@router.post("/projects/{project_id}/testing/findings/{finding_id}/decision")
async def decide_finding(
    project_id: str, finding_id: str, body: FindingIn, conn: Db, owner: Owner, actor: Actor
) -> TestSnapshot:
    """Accept or dismiss one security finding, without touching the report.

    An overlay, so the validation report stays exactly as the arms produced it.
    That is what keeps the study's numbers honest: a dismissal is a human
    decision about a finding, not evidence that the finding was wrong, and a
    precision computed over a report somebody had edited would measure the
    editing.
    """
    if body.decision == "dismissed" and not (body.note or "").strip():
        raise Conflict(
            "dismissing a security finding needs a note saying why it does not apply here"
        )
    await require_project(conn, project_id, owner)
    version = await store.current_test_version(conn, project_id)
    if not version:
        raise Conflict("nothing has been scanned yet, so there is no finding to decide")

    await store.put_overlay(
        conn,
        project_id=project_id,
        version=version,
        kind="finding_decision",
        target_id=finding_id,
        value={"decision": body.decision, "note": (body.note or "").strip()},
        by=actor,
    )
    await store.record(
        conn,
        actor=actor,
        action=(
            "Accepted a security finding"
            if body.decision == "accepted"
            else "Dismissed a security finding"
        ),
        target=finding_id,
        detail=(body.note or "")[:500],
        project_id=project_id,
        category="approval",
    )
    return await _snapshot(conn, project_id, owner)


@router.post("/projects/{project_id}/testing/remediation/{proposal_id}/decision")
async def decide_proposal(
    project_id: str, proposal_id: str, body: ProposalIn, conn: Db, owner: Owner, actor: Actor
) -> TestSnapshot:
    """Accept or dismiss one proposed fix.

    Accepting records the decision and nothing more. C3 proposes and C2
    applies, so the patch reaches the repository as a new code version through
    the code phase, which is what keeps one writer for source code and makes
    the change reviewable by the same machinery as any other change.
    """
    if body.decision == "dismissed" and not (body.note or "").strip():
        raise Conflict("dismissing a proposed fix needs a note saying why")
    await require_project(conn, project_id, owner)
    version = await store.current_test_version(conn, project_id)
    if not version:
        raise Conflict("nothing has been proposed yet, so there is no fix to decide")

    await store.put_overlay(
        conn,
        project_id=project_id,
        version=version,
        kind="remediation_decision",
        target_id=proposal_id,
        value={"decision": body.decision, "note": (body.note or "").strip()},
        by=actor,
    )
    await store.record(
        conn,
        actor=actor,
        action=(
            "Accepted a proposed fix" if body.decision == "accepted" else "Dismissed a proposed fix"
        ),
        target=proposal_id,
        detail=(body.note or "")[:500],
        project_id=project_id,
        category="approval",
    )
    return await _snapshot(conn, project_id, owner)


# A test id is its file's path and its name (`apps/api/src/__tests__/x.ts::name`),
# so a route takes it as the rest of the path: as one path segment, a real id
# never reached the route, its slashes decoded before the match, and keeping a
# repair answered 404 on every generated test.
async def _refuse_once_approved(conn: Any, project_id: str, version: int) -> None:
    """Refuse an edit to a test file once its test version is approved.

    The approval covers the tests as they were, and Deployment's staging build
    reads the stored files: a decision after it changed what shipped without
    anyone approving that (review item X-2).
    """
    if await store.version_is_approved(conn, project_id, gate_kind=GATE_KIND, version=version):
        raise Conflict(
            f"test version {version} is approved with these tests, so they stay as they "
            "are: run the tests again to change them, and that run's review approves the "
            "change"
        )


@router.post("/projects/{project_id}/testing/heals/{test_id:path}/decision")
async def decide_heal(
    project_id: str, test_id: str, body: HealIn, conn: Db, owner: Owner, actor: Actor
) -> TestSnapshot:
    """Keep or revert what the healing loop did with one test.

    The guard decides mechanically whether a repair may be accepted. This is
    what a person decides afterwards, and it is separate for that reason: the
    machine's verdict and the human's are two different facts about the same
    repair, and the study reports both.

    Keeping writes the repair into the stored test file at the code version
    the run tested, which is the file the next run carries forward and
    Deployment's staging build runs; reverting a kept repair puts the test
    back as it was written. Both were only recorded until 2026-10-04, so a
    kept repair changed nothing, and the test it repaired went on failing
    wherever it ran.
    """
    await require_project(conn, project_id, owner)
    version = await store.current_test_version(conn, project_id)
    if not version:
        raise Conflict("nothing has been healed yet, so there is no repair to decide")
    await _refuse_once_approved(conn, project_id, version)
    attempt, case = await _heal_attempt(conn, project_id, test_version=version, test_id=test_id)
    if attempt is None:
        raise NotFound("a healing attempt on", f"{test_id} in test version {version}")

    # The same decision again is not a second decision: repeated clicks each
    # wrote another audit entry saying the same thing.
    note = (body.note or "").strip()
    already = next(
        (
            row
            for row in await store.overlays(conn, project_id)
            if row["kind"] == "heal_decision"
            and row["version"] == version
            and row["target_id"] == test_id
        ),
        None,
    )
    if already is not None and already["value"] == {"decision": body.decision, "note": note}:
        return await _snapshot(conn, project_id, owner)
    # A decision about the test itself comes first: its file no longer holds
    # the test as the repair was made to.
    if already is not None and already["value"].get("decision") == "quarantined":
        raise Conflict(
            f"{attempt.test_name} is quarantined, so its file skips the test this repair was "
            "made to. Restore the test first"
        )
    if already is not None and already["value"].get("decision") == "rewrite":
        raise Conflict(
            f"{attempt.test_name} was sent back to be written again, so its file holds a todo "
            "where this repair would go, and the next run writes the test afresh"
        )
    was_kept = already is not None and already["value"].get("decision") == "kept"

    written = ""
    if body.decision == "kept" and not was_kept:
        repair = _keepable(attempt, case)
        code_version = await _tests_of_the_current_code(conn, project_id, version)
        await _rewrite_test(conn, project_id, code_version, repair, undo=False)
        written = f"The test file at code version {code_version} now carries the repair."
    elif body.decision == "reverted" and was_kept and attempt.diff is not None:
        code_version = await _tests_of_the_current_code(conn, project_id, version)
        await _rewrite_test(conn, project_id, code_version, attempt.diff, undo=True)
        written = f"The test file at code version {code_version} is back as it was written."

    await store.put_overlay(
        conn,
        project_id=project_id,
        version=version,
        kind="heal_decision",
        target_id=test_id,
        value={"decision": body.decision, "note": note},
        by=actor,
    )
    await store.record(
        conn,
        actor=actor,
        action=("Kept a healed test" if body.decision == "kept" else "Reverted a healed test"),
        target=test_id,
        detail=" ".join(part for part in (note[:500], written) if part),
        project_id=project_id,
        category="testing",
    )
    return await _snapshot(conn, project_id, owner)


@router.post("/projects/{project_id}/testing/tests/{test_id:path}/decision")
async def decide_test(
    project_id: str,
    test_id: str,
    body: TestDecisionIn,
    conn: Db,
    owner: Owner,
    components: Components,
    actor: Actor,
) -> TestSnapshot:
    """Quarantine a failing generated test, restore one, or ask for one written again.

    A test review is not approved while a generated test fails, and a
    model-written test that asserts something the code does not do can fail for
    good: the healing loop leaves a regression alone, a first run has nothing to
    compare against, and the generator keeps every written body. One wrong test
    made a project unreleasable. Real teams then do one of two things, with a
    reason on the record:

    - **Quarantine**: the test is skipped, with who, when and why above it, in
      the stored file the next run carries and the staging build runs, until
      somebody restores it. The review no longer waits on it.
    - **Write it again**: a test that never passed, which nothing ever checked
      against the code, goes back to a todo the next run's fill writes afresh.
      Refused for a test that passed before: failing now, it is a regression,
      and the code is what has to change.

    The edit is C3's (it knows its own test files) and lands in the stored test
    file at the code version this run tested, so it is refused once the code
    has moved past that version. A quarantine lasts until somebody restores
    the test, across later runs, because each run carries the file, the
    contract tests' included. The decision is recorded beside the run's report
    and in Activity.
    """
    await require_project(conn, project_id, owner)
    version = await store.current_test_version(conn, project_id)
    if not version:
        raise Conflict("nothing has been tested yet, so there is no test to decide about")
    await _refuse_once_approved(conn, project_id, version)
    note = (body.note or "").strip()
    if body.decision != "restored" and not note:
        raise Conflict(
            "quarantining a test, or asking for it to be written again, needs a note saying why"
        )
    found = await store.artefacts_at(conn, project_id, version=version, kinds=("test-report",))
    if "test-report" not in found:
        raise Conflict(f"test version {version} has no report, so there is no test to decide about")
    report = TestReport.model_validate(found["test-report"]["body"])
    if not measured_the_generated_app(report):
        raise Conflict(
            "this run measured a sample, which is a checked in fixture rather than this "
            "project's tests, so its tests are not this platform's to change"
        )
    suite, case = next(
        ((suite, case) for suite in report.suites for case in suite.cases if case.id == test_id),
        (None, None),
    )
    if suite is None or case is None:
        raise NotFound("test", test_id)
    # The decision in force: this version's, or a quarantine from an earlier
    # one that nobody has restored, whose test every later run skips.
    current = next(
        (
            one.decision
            for one in heal_decisions(await store.overlays(conn, project_id), version)
            if one.test_id == test_id
        ),
        None,
    )
    if current == body.decision:
        return await _snapshot(conn, project_id, owner)
    if body.decision == "restored":
        if current != "quarantined":
            raise Conflict(f"{case.name} is not quarantined, so there is nothing to restore")
    else:
        if current == "kept":
            raise Conflict(
                f"a repair to {case.name} was kept, so its file already carries the repair "
                "for the next run to measure. Revert the repair first to set the test aside"
            )
        if case.outcome not in ("failed", "errored") and current != "quarantined":
            raise Conflict(
                f"{case.name} {case.outcome} in this run: only a failing test is quarantined "
                "or written again"
            )
    if body.decision == "rewrite":
        if case.kind == "api":
            raise Conflict(
                f"{case.name} is an API test, which every run writes again from the contract, "
                "so asking for it again changes nothing. Its failure means the code does not "
                "answer as the contract says: change the code, or quarantine it with a reason"
            )
        passed = await _passed_before(conn, project_id, test_id, before=version)
        if passed is not None:
            raise Conflict(
                f"{case.name} passed at test version {passed}, so it failing now is a "
                "regression rather than a wrong test: change the code, or quarantine it "
                "with a reason"
            )

    code_version = await _tests_of_the_current_code(conn, project_id, version)
    files = await store.code_files(
        conn, project_id, version=code_version, stage_id=store.TEST_FILE_STAGE
    )
    if suite.path not in files:
        raise Conflict(
            f"{suite.path} is not among the tests stored at code version {code_version}, so "
            "there is nothing to change"
        )
    edited = await components["c3"].decide_test(
        files[suite.path],
        case.name,
        decision=body.decision,
        by=actor,
        reason=note,
        on=datetime.now(UTC).date().isoformat(),
    )
    if edited is None:
        raise Conflict(
            f"{suite.path} does not hold {case.name} exactly once as this needs it, so nothing "
            "was changed rather than the wrong test"
        )
    files[suite.path] = edited
    await store.put_code_files(
        conn, project_id, version=code_version, stage_id=store.TEST_FILE_STAGE, files=files
    )
    await store.put_overlay(
        conn,
        project_id=project_id,
        version=version,
        kind="heal_decision",
        target_id=test_id,
        value={"decision": body.decision, "note": note},
        by=actor,
    )
    await store.record(
        conn,
        actor=actor,
        action={
            "quarantined": "Quarantined a test",
            "restored": "Restored a quarantined test",
            "rewrite": "Asked for a test to be written again",
        }[body.decision],
        target=test_id,
        detail=" ".join(
            part
            for part in (note[:500], f"The test file at code version {code_version} says so.")
            if part
        ),
        project_id=project_id,
        category="testing",
    )
    return await _snapshot(conn, project_id, owner)


async def _passed_before(conn: Any, project_id: str, test_id: str, *, before: int) -> int | None:
    """The newest earlier test version whose run passed this test, if any did."""
    for version in range(before - 1, 0, -1):
        found = await store.artefacts_at(conn, project_id, version=version, kinds=("test-report",))
        if "test-report" not in found:
            continue
        report = TestReport.model_validate(found["test-report"]["body"])
        if any(
            case.id == test_id and case.outcome == "passed"
            for suite in report.suites
            for case in suite.cases
        ):
            return version
    return None


async def _heal_attempt(
    conn: Any, project_id: str, *, test_version: int, test_id: str
) -> tuple[HealAttempt | None, TestCase | None]:
    """The loop's attempt on one test at this test version, and the test as the run measured it."""
    found = await store.artefacts_at(
        conn, project_id, version=test_version, kinds=("heal-report", "test-report")
    )
    healed = found.get("heal-report")
    if healed is None:
        return None, None
    attempt = next(
        (
            one
            for one in HealReport.model_validate(healed["body"]).attempts
            if one.test_id == test_id
        ),
        None,
    )
    measured = found.get("test-report")
    case = (
        next(
            (
                one
                for suite in TestReport.model_validate(measured["body"]).suites
                for one in suite.cases
                if one.id == test_id
            ),
            None,
        )
        if measured is not None
        else None
    )
    return attempt, case


def _keepable(attempt: HealAttempt, case: TestCase | None) -> DiffSpan:
    """The repair to write into the test, or why it may not be kept, raised.

    Only what the guard accepted: a refused repair is evidence about the model,
    and writing it into the suite would undo the refusal. And never one to an
    API test, which every run writes again from the contract: the repair would
    not outlast the next run, and that test failing means the code does not
    answer as the contract says, which no edit to the test can settle.
    """
    if attempt.diff is None:
        raise Conflict(
            f"the healing loop made no repair to {attempt.test_name} (it was "
            f"{attempt.classification}), so there is nothing to keep"
        )
    if not attempt.accepted:
        raise Conflict(
            f"the guard refused this repair ({attempt.refusal_reason or 'a check failed'}), so "
            "there is nothing to keep: the test stays as written and its failure stays open"
        )
    if case is not None and case.kind == "api":
        raise Conflict(
            f"{attempt.test_name} is an API test, which every run writes again from the "
            "contract, so a repair to it would not last. Its failure means the code does not "
            "answer as the contract says: change the code, or the contract"
        )
    return attempt.diff


async def _tested_code(conn: Any, project_id: str, test_version: int) -> int:
    """The code version the run behind this test version tested, whose test files it wrote."""
    run = await store.run_for_version(conn, project_id, component="c3", version=test_version)
    code_version = int((run or {}).get("source_version") or 0)
    if not code_version:
        raise Conflict(
            f"test version {test_version} names no code version it tested, so there is no "
            "test file to write the repair into"
        )
    return code_version


async def _tests_of_the_current_code(conn: Any, project_id: str, test_version: int) -> int:
    """The code version this test version tested, refused once the code has moved past it.

    A decision about a test is written into the tested version's test files,
    and a newer code version took its own copy of them when it was made. A
    decision written now would never reach it, and the next run would measure
    the test as it was.
    """
    code_version = await _tested_code(conn, project_id, test_version)
    # Claimed rather than written: a version takes its copy of the tests when
    # it is claimed, before its run has written anything.
    newest = await store.next_code_version(conn, project_id) - 1
    if newest > code_version:
        raise Conflict(
            f"these tests ran on code version {code_version}, and code version {newest} "
            "has been made since, with its own copy of them. Run the tests on version "
            f"{newest} first, then decide about what fails there"
        )
    return code_version


async def _rewrite_test(
    conn: Any, project_id: str, code_version: int, diff: DiffSpan, *, undo: bool
) -> None:
    """Apply a repair to the stored test file it was made to, or take it back out.

    Exactly or not at all, as an applied security fix is: a file that moved on
    since the repair was made is refused, never patched approximately. Only the
    test files are read and written, so a repair cannot reach production code.
    """
    files = await store.code_files(
        conn, project_id, version=code_version, stage_id=store.TEST_FILE_STAGE
    )
    if diff.path not in files:
        raise Conflict(
            f"{diff.path} is not among the tests stored at code version {code_version}, so "
            "the repair has nothing to apply to"
        )
    try:
        files[diff.path] = apply_to(
            files[diff.path], reverse(diff.diff) if undo else diff.diff, path=diff.path
        )
    except PatchRefused as refused:
        raise Conflict(f"the repair no longer applies to {refused}") from refused
    await store.put_code_files(
        conn, project_id, version=code_version, stage_id=store.TEST_FILE_STAGE, files=files
    )


@router.post("/projects/{project_id}/testing/remediation/{proposal_id}/apply")
async def apply_proposal(
    project_id: str,
    proposal_id: str,
    body: ApplyIn,
    conn: Db,
    owner: Owner,
    components: Components,
    actor: Actor,
) -> TestSnapshot:
    """Put an accepted fix into the code, as a new code version.

    **The one place a security fix crosses a component boundary.** C3 proposed
    it, a person accepted it, and the orchestrator applies it, because the
    orchestrator owns the artefact store and the version axis. C3 never writes
    source: a component that both finds a weakness and edits the code to close
    it is a component that can mark its own homework.

    The result is an ordinary code version. That is the point of routing it
    this way rather than patching the working tree: the fix is reviewable by
    the same machinery as any other change, it carries a version a re-scan can
    be compared against, and rolling it back means going back to the version
    before it rather than reversing an edit nobody recorded.

    A patch that no longer applies is refused with the line that did not match.
    Forcing it would be writing unreviewed code into the one place where being
    wrong is worst.

    The new version is pushed to a branch of its own, as every version is, and
    lands on the default branch: the version it patched was approved, and so
    was the patch. Until 2026-10-05 it inherited the patched version's
    repository pointer instead, so it was never pushed, Push refused it as
    already pushed, and a cloud release built on the commit without the fix
    while every fingerprint named the fixed candidate.
    """
    project = await require_project(conn, project_id, owner)
    version = await store.current_test_version(conn, project_id)
    if not version:
        raise Conflict("nothing has been proposed yet, so there is no fix to apply")

    proposals = await _proposals(conn, project_id, version)
    proposal = next((one for one in proposals.proposals if one.id == proposal_id), None)
    if proposal is None:
        raise NotFound("proposal", proposal_id)

    decision = await _decision_for(conn, project_id, version, proposal_id)
    if decision != "accepted":
        raise Conflict(
            "this fix has not been accepted. A patch reaches the code because a person "
            "decided it should, not because it was proposed"
        )

    # What the scan was pointed at, recorded on the artefact by the run that
    # produced it. Only the generated application is this platform's to patch:
    # a sample is a checked in fixture in the component's own repository, and a
    # remediation that edited one would be the platform writing into its own
    # source tree on a reader's say so.
    #
    # Refused here, by name. Without this the patch reached `apply_all`, which
    # correctly reported that the file it named is not in this code version,
    # and sent a reader to look for a file that moved when nothing had moved.
    if proposals.target != "generated":
        raise Conflict(
            f"this fix is for {proposals.target!r}, which this platform does not patch. "
            "Applying writes a new code version of the generated application, and a sample "
            "is a checked in fixture rather than code this project generated. Point the "
            "phase at the generated application and scan again to get a fix it can apply"
        )

    # Once. Applied again, its patch met the code it had already written, and
    # the refusal blamed the file for changing after the fix was proposed.
    made = await _applied_as(conn, project_id, version, proposal_id)
    if made is not None:
        raise Conflict(f"this fix is already applied, as code version {made}")

    # One fix at a time until a run has measured it. Testing runs only on the
    # newest code, and re-verification needs a run at exactly a fix's version,
    # so a second fix applied first left the first impossible to re-verify
    # (review item C3-9).
    waiting = await _fix_awaiting_its_run(conn, project_id)
    if waiting is not None:
        other, made = waiting
        raise Conflict(
            f"{other} is applied as code version {made}, which no testing run has measured "
            f"yet. Applying another fix now writes a newer version over it, and {other} could "
            f"never be re-verified: run the tests on code version {made} first, then apply "
            "this one"
        )

    code_version = await store.current_code_version(conn, project_id)
    files = await store.code_files(conn, project_id, version=code_version)
    if not files:
        raise Conflict(f"code version {code_version} has no files to patch")

    try:
        patched = apply_all(files, [(hunk.path, hunk.diff) for hunk in proposal.patch])
    except PatchRefused as refusal:
        raise Conflict(str(refusal)) from refusal

    next_version = await store.next_code_version(conn, project_id)
    # The tests stay filed as the tests: a push leaves them out, and testing
    # reads and decides about its own files by that stage.
    tests = await store.code_files(
        conn, project_id, version=code_version, stage_id=store.TEST_FILE_STAGE
    )
    await store.put_code_files(
        conn,
        project_id,
        version=next_version,
        stage_id="backend-code",
        files={path: content for path, content in patched.items() if path not in tests},
    )
    await store.put_code_files(
        conn,
        project_id,
        version=next_version,
        stage_id=store.TEST_FILE_STAGE,
        files={path: content for path, content in patched.items() if path in tests},
    )
    # Every artefact of the version being patched comes forward. The patch
    # changed file content, and nothing else about the build moved: the same
    # scope, the same stack, the same contract, the same manifest. A version
    # missing them is not a lighter version, it is a broken one, and it fails
    # in two places at once. The Build page would render a version with no
    # contract, and the next testing run would have no acceptance criteria to
    # derive tests from, which is where this loop used to stop.
    #
    # The manifest in particular has to be the one it had: a manifest naming a
    # different set from the file store is how the viewer shows a file nobody
    # can account for.
    #
    # Except where the patched version's code went and what built it, which are
    # facts about that version's files and not these. The pointer named a
    # commit without the fix, which Push then refused as already pushed and a
    # cloud release built on.
    not_pushed = (
        f"written by applying an accepted security fix over code version {code_version}, "
        "and not built or pushed on its own"
    )
    found = await store.artefacts_at(
        conn, project_id, version=code_version, kinds=CODE_ARTEFACT_KINDS
    )
    repository: dict[str, Any] | None = None
    for kind, row in found.items():
        carried = dict(row["body"])
        if "version" in carried:
            carried["version"] = next_version
        if kind == "code-repository":
            carried.update(repository=None, build=None, notPushedReason=not_pushed)
            repository = carried
        await store.put_artefact(
            conn,
            project_id=project_id,
            kind=kind,
            version=next_version,
            body=carried,
        )
    await store.put_overlay(
        conn,
        project_id=project_id,
        version=version,
        kind="remediation_decision",
        target_id=proposal_id,
        value={
            "decision": "accepted",
            "note": (body.note or "").strip(),
            "appliedCodeVersion": next_version,
            # The version this was applied over, so the approval the reader
            # gave that version can be followed forward to this one without
            # assuming the two numbers are adjacent.
            "patchedCodeVersion": code_version,
        },
        by=actor,
    )

    # Pushed once the overlay says what it patched, which is what counts its
    # approval and lands it.
    pushed, said = await push_stored_version(
        conn, project, version=next_version, owner=owner, c2=components["c2"]
    )
    if pushed is None and repository is not None:
        await store.put_artefact(
            conn,
            project_id=project_id,
            kind="code-repository",
            version=next_version,
            body={**repository, "notPushedReason": f"{not_pushed}: {said}"},
        )
    await store.record(
        conn,
        actor=actor,
        action="Applied a security fix",
        target=f"{proposal.cwe} in {proposal.patch[0].path}, code version {next_version}",
        detail=" ".join(
            (
                proposal.summary,
                f"Re-verification compares this against version {code_version}.",
                f"Pushed to {pushed.url}, branch {pushed.branch}.{said}"
                if pushed is not None
                else f"Not pushed: {said}.",
                *await _ships_with(conn, project_id, patched=code_version, written=next_version),
            )
        ),
        project_id=project_id,
        category="code",
    )
    return await _snapshot(conn, project_id, owner)


async def _ships_with(conn: Any, project_id: str, *, patched: int, written: int) -> list[str]:
    """What a fix applied over newer code than may ship reaches production with.

    A fix patches the newest code version, so code versions stay one line. Over
    code newer than the newest approved tests measured, it ships only with the
    rest of that code, once its tests are approved, and nothing said so (review
    item C4-13). Empty when the fix ships on its own.
    """
    releasable = await store.releasable_code_version(conn, project_id)
    if not releasable or patched <= releasable:
        return []
    sprint = await store.sprint_of_code(conn, project_id, patched)
    with_what = (
        f"sprint {sprint}"
        if sprint > await store.sprint_of_code(conn, project_id, releasable)
        else f"the rest of code version {patched}"
    )
    return [
        f"It ships with {with_what}, once code version {written}'s tests are approved; code "
        f"version {releasable}, the newest with approved tests, does not get it on its own."
    ]


@router.post("/projects/{project_id}/testing/remediation/{proposal_id}/reverify")
async def reverify_proposal(
    project_id: str,
    proposal_id: str,
    body: ApplyIn,
    conn: Db,
    owner: Owner,
    components: Components,
    actor: Actor,
) -> TestSnapshot:
    """Did the fix work? Answered by subtracting two runs, not by asking.

    **This is the only route that calls a component outside a run.** Everything
    else a component does is a stage, with a graph, a gate and a retry behind
    it. This is a question about two runs that already finished, so there is no
    stage to run and nothing to interrupt.

    It needs a second testing pass to exist. A re-verification against the same
    run that proposed the fix would be subtracting a number from itself, so if
    nothing has measured the patched code yet this says so and asks for a run
    rather than inventing an answer.

    C3 does the arithmetic, and C3 may refuse it: two passes measured with
    different arms, over a different file count, or with a suite that did not
    run, are not comparable, and subtracting them anyway is how a fix that did
    nothing comes to look like a fix that worked. A refusal is recorded in the
    thread and the audit log, nothing else is stored because there is no result
    to store, and the answer is a 409 carrying C3's sentence. It was a 200 with
    the refusal only in the thread, so a reader with the conversation closed
    pressed the button and saw nothing happen.
    """
    await require_project(conn, project_id, owner)

    applied = await _applied(conn, project_id, proposal_id)
    if applied is None:
        raise Conflict(
            "this fix has not been applied, so there is no second version to compare against"
        )
    before_version, code_version = applied

    proposals = await _proposals(conn, project_id, before_version)
    proposal = next((one for one in proposals.proposals if one.id == proposal_id), None)
    if proposal is None:
        raise NotFound("proposal", proposal_id)

    runs = await _c3_runs(conn, project_id)
    before_run = next((row for row in runs if row["requirements_version"] == before_version), None)
    after_run = next(
        (
            row
            for row in runs
            if row["source_version"] == code_version
            and row["requirements_version"] != before_version
        ),
        None,
    )
    if after_run is None:
        raise Conflict(
            f"nothing has tested code version {code_version} yet, which is the version "
            "carrying this fix. Start a testing run, then re-verify"
        )

    before = await _reports(conn, project_id, before_version)
    after = await _reports(conn, project_id, int(after_run["requirements_version"]))
    if before is None or after is None:
        raise Conflict("one of the two runs produced no report, so there is nothing to subtract")

    answer = await components["c3"].reverify(
        before[0],
        before[1],
        after[0],
        after[1],
        before_run_id=str(before_run["id"]) if before_run else "",
        after_run_id=str(after_run["id"]),
        # Did it close its own finding, looked for where its patch left it,
        # and not only did the totals hold (review item C3-7).
        finding_id=proposal.finding_id,
        patch=proposal.patch,
    )
    if answer.artefact is None:
        # The refusal is the result. It goes in the thread because that is
        # where this phase's reader looks, and it is the sentence that stops
        # somebody reading a flattering subtraction as a working fix.
        await store.post_thread_message(
            conn,
            project_id,
            kind="system",
            author="Testing and Security",
            content=answer.summary,
            stage_id="remediation",
        )
        await store.record(
            conn,
            actor=actor,
            action="Re-verification refused",
            target=f"{proposal_id}, code version {code_version}",
            detail=answer.summary,
            project_id=project_id,
            category="testing",
        )
        # Committed before refusing: the request's transaction rolls back on
        # the way out of an error, and the record of the refusal is the one
        # write this request means to keep.
        await conn.commit()
        raise Conflict(f"Not re-verified: {answer.summary}")

    await store.put_overlay(
        conn,
        project_id=project_id,
        version=before_version,
        kind="remediation_reverification",
        target_id=proposal_id,
        value=answer.artefact.model_dump(by_alias=True, mode="json"),
        by=actor,
    )
    await store.record(
        conn,
        actor=actor,
        action="Re-verified a security fix",
        target=f"{proposal_id}, code version {code_version}",
        detail=answer.summary,
        project_id=project_id,
        category="testing",
    )
    return await _snapshot(conn, project_id, owner)


@router.post("/projects/{project_id}/testing/decision")
async def submit_decision(
    project_id: str, body: DecisionIn, conn: Db, owner: Owner, supervisor: Supervisor, actor: Actor
) -> TestSnapshot:
    """The test review gate, reached from the browser.

    The note on an approval is not decoration here. This phase's whole output
    is a list of things that may still be wrong, so an approval that does not
    say what was left open is an approval nobody can defend later.
    """
    await require_project(conn, project_id, owner)
    gate = await store.pending_gate(conn, project_id=project_id, kind=GATE_KIND)
    if gate is None:
        raise Conflict("there is no testing decision waiting on this project")
    if body.kind == "changes" and not (body.note or "").strip():
        raise Conflict("requesting changes needs a note saying what to change")
    if body.kind == "changes":
        moved = await _code_moved_past(conn, project_id, gate)
        if moved is not None:
            tested, current = moved
            raise Conflict(
                f"these tests ran on code version {tested}, and the code is at version "
                f"{current} now, so requested changes would test the older code again. Run "
                f"the tests on version {current} instead: that closes this review"
            )
    if body.kind == "approved":
        current = await _snapshot(conn, project_id, owner)
        failing = _failing_tests(current)
        unproven = _unproven(current)
        if unproven and not failing and not (body.note or "").strip():
            raise Conflict(
                f"this run left {'; '.join(unproven)}, so approving it needs a note saying why "
                "that is enough to go on",
                detail={"concerns": unproven},
            )
        if failing:
            many = len(failing) != 1
            raise Conflict(
                f"{len(failing)} test{'s' if many else ''} fail{'' if many else 's'} in this "
                f'run, starting with "{failing[0]}". Deployment\'s staging build runs these '
                "same tests and refuses a candidate when any of them fails, so this review "
                "cannot be approved until they pass. Keep the repairs the healing guard "
                "accepted and request changes to run the tests with them, change the code "
                "they test, or quarantine a test you judge wrong, with a reason",
                detail=[{"test": name} for name in failing],
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

    snapshot = await _snapshot(conn, project_id, owner)
    open_findings = snapshot.open_findings
    on_the_app = measured_the_generated_app(snapshot.tests)
    if body.kind == "approved":
        # What the approval covers, kept beside it: the release holds if these
        # tests change before it ships (G4, review item X-2).
        await store.note_on_gate(
            conn,
            gate["id"],
            {
                "testFilesSha256": await store.test_files_digest(
                    conn, project_id, int(gate["requirements_version"])
                )
            },
        )
    approved_says = (
        "Deployment can start."
        if on_the_app
        else (
            f"This run measured {snapshot.tests.target if snapshot.tests else 'a sample'}, so "
            "it does not unlock Deployment: approve a run on the generated app for that."
        )
    )
    await store.post_thread_message(
        conn,
        project_id,
        kind="system",
        author=actor,
        content=(
            f"Approved testing and security with {open_findings} finding"
            f"{'s' if open_findings != 1 else ''} open. {approved_says}"
            if body.kind == "approved"
            else f"Requested changes: {body.note}"
        ),
        stage_id="test-review",
    )
    await store.record(
        conn,
        actor=actor,
        action=(
            "Approved testing and security"
            if body.kind == "approved"
            else "Requested testing changes"
        ),
        # What was open at approval, named rather than implied. An approval
        # that reads as "everything was fine" over three open criticals is the
        # audit entry this component exists to prevent.
        target=f"test version {gate['requirements_version']}, {open_findings} findings open",
        detail=(body.note or "")[:500],
        project_id=project_id,
        run_id=gate["run_id"],
        category="approval",
    )

    # A change is regenerated at a new test version, and only the store
    # allocates version numbers, so the number travels in the resume payload.
    # Without it the gate refuses to guess and the run fails (defect 27). The
    # code gate has always done it this way; this one now matches it.
    resume: dict[str, Any] = {"kind": body.kind, "note": body.note or ""}
    if body.kind == "changes":
        version = await store.next_test_version(conn, project_id)
        await store.set_run_version(conn, gate["run_id"], version)
        await store.set_stages(
            conn, project_id, list(TEST_GENERATING_STAGE_IDS), status="generating"
        )
        resume["version"] = version
    await store.set_run_state(conn, gate["run_id"], "queued", resume_payload=resume)

    if supervisor is not None:
        from .projects import _after_commit

        _after_commit(supervisor, gate["run_id"])
    return await _snapshot(conn, project_id, owner)
