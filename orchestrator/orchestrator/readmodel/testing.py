"""Compose a TestSnapshot from the rows that hold it.

The code snapshot's shape for the testing phase, and the same three rules.
Every artefact lives in its own versioned row validated against its own schema;
this puts them together with stage, gate and thread state into the one payload
the browser reads; and nothing here is stored that can be derived.

Two things are derived and worth naming.

`testedCodeVersion` comes from the run that produced the current test version,
so "the code moved on" is arithmetic over two numbers rather than a flag
somebody has to remember to set. A green report about a code version two behind
is the most misleading thing this phase can display, and the contract computes
`codeMovedOn` from exactly these two numbers.

Decisions are laid over the artefacts rather than written into them, exactly as
the design phase does it. A finding dismissed by a reader, a fix accepted,
applied and re-verified: none of that is something C3 knew when it produced the
report, and editing the report to say so would make every number in the study a
number about the reader. So the artefact stays as the arms produced it and the
overlays say what happened next.

The stage vocabulary is filtered, and that filter is not optional. `stage_states`
holds the design and code phases' rows too, and `TestStageId` is a Literal over
seven ids, so an unfiltered build is a ValidationError on the first design row.
The same hazard C2 hit and fixed, in the same place, for the same reason.
"""

from typing import Any

from psycopg import AsyncConnection
from sdlc_contracts import (
    TEST_STAGE_IDS,
    GateDecision,
    GateState,
    HealDecision,
    HealReport,
    RemediationProposals,
    Reverification,
    TestAuditEntry,
    TestReport,
    TestSnapshot,
    TestStageId,
    TestStageState,
    TestThreadMessage,
    ValidationReport,
)

from ..db import store
from ..model_use import kept_model_use
from .runs import run_status

#: The four artefacts this phase owns. `test-review` produces none: it is the
#: gate, and a gate is a decision rather than a document.
TEST_ARTEFACT_KINDS = (
    "test-report",
    "heal-report",
    "validation-report",
    "remediation-proposal",
)

GATE_KIND = "c3-test-review"


def _stage_row_to_model(row: store.Row) -> TestStageState:
    return TestStageState(
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


#: This phase's actions filed under another category: approvals, whatever their
#: phase, are "approval", and an applied fix is a code version, "code".
_TESTING_ACTIONS = (
    "Accepted a security finding",
    "Dismissed a security finding",
    "Accepted a proposed fix",
    "Dismissed a proposed fix",
    "Approved testing and security",
    "Requested testing changes",
    "Applied a security fix",
)


def _audit_query(project_id: str) -> store.Query:
    return store.phase_audit_query(project_id, ("testing", "security"), _TESTING_ACTIONS)


#: Decisions about a failing test itself rather than about a repair to it.
_ABOUT_THE_TEST = ("quarantined", "restored", "rewrite")


def heal_decisions(rows: list[store.Row], version: int) -> list[HealDecision]:
    """The reader's decision on each test at this test version, newest per test.

    Recorded by `POST .../heals/{test}/decision` and read by nothing until now,
    so deciding about a repair changed nothing on the page.

    A quarantine lasts until somebody restores the test, so one made at an
    earlier version is still in force here unless a later decision about the
    test ended it: every later run carries the skipped test in its file, and a
    reader has to find it to restore it.
    """
    here: dict[str, store.Row] = {}
    about_the_test: dict[str, store.Row] = {}
    for row in rows:
        if (
            row["kind"] != "heal_decision"
            or row["version"] > version
            or not isinstance(row["value"], dict)
        ):
            continue
        if row["value"].get("decision") in _ABOUT_THE_TEST:
            about_the_test[row["target_id"]] = row
        if row["version"] == version:
            here[row["target_id"]] = row
    for test_id, row in about_the_test.items():
        if test_id not in here and row["value"].get("decision") == "quarantined":
            here[test_id] = row
    return [
        HealDecision(
            test_id=row["target_id"],
            decision=row["value"].get("decision", "kept"),
            by=row["by"],
            at=row["at"],
            note=row["value"].get("note", ""),
        )
        for row in here.values()
    ]


def _gate_state(history_rows: list[store.Row], version: int) -> GateState:
    """The decision that covers this version, with every other one behind it.

    C2's rule, and it is not a detail: a decision is recorded against the
    version it was made about. Reporting the newest decision whatever its
    version means the phase never asks again, the page reads as decided, and
    the run waiting at its gate waits for good.
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


#: What a run works on when nobody has chosen. The generated application, which
#: is what the pipeline exists to produce.
DEFAULT_TARGET = "generated"


def measured_the_generated_app(report: Any) -> bool:
    """Whether a test report measured the generated application.

    The report names what it measured, so a number is never attributed to the
    wrong target (C3's `_target_name`: "the generated app at code version N",
    "the java sample"). The newest target choice is not that: it may change
    while a review waits, and reading it let a switch to a sample hide the
    generated app's failing tests from the review.
    """
    return report is not None and str(report.target).startswith("the generated app")


def selected_target(rows: list[store.Row]) -> str:
    """Which repository this project's runs work on.

    Newest across versions, not per version, because a choice that had to be
    made again after every regeneration would be a setting nobody could keep.
    That is the same rule the graph reads it by, and the two must agree or the
    page names one target while the run uses another.
    """
    chosen = [
        row for row in rows if row["kind"] == "target_selection" and row["target_id"] == "target"
    ]
    return str(chosen[-1]["value"]) if chosen else DEFAULT_TARGET


def _decided_findings(
    validation: ValidationReport, rows: list[store.Row], version: int
) -> ValidationReport:
    """Lay the reader's dismissals over what the arms found.

    Only dismissals move a status. Accepting a finding is agreeing with the
    machine that the weakness is real, and a weakness agreed to is still open;
    closing it on agreement would let the open count fall by being read.

    The artefact itself is untouched, which is what keeps the study's numbers
    about the arms rather than about the reader: precision computed over a
    report somebody edited measures the editing.
    """
    dismissed = {
        row["target_id"]
        for row in rows
        if row["kind"] == "finding_decision"
        and row["version"] == version
        and (row["value"] or {}).get("decision") == "dismissed"
    }
    if not dismissed:
        return validation
    findings = [
        finding.model_copy(update={"status": "dismissed"}) if finding.id in dismissed else finding
        for finding in validation.findings
    ]
    return validation.model_copy(update={"findings": findings})


def _decided_proposals(
    remediation: RemediationProposals, rows: list[store.Row], version: int
) -> RemediationProposals:
    """What happened to each proposed fix after it was proposed.

    Without this the page would keep saying "awaiting decision" about a fix
    that was accepted, applied and re-verified, because the artefact is what
    C3 produced at the moment it proposed and nothing after that belongs in
    it.

    **`verified` is set from the numbers, never from the act of measuring.**
    A re-verification whose totals got worse leaves the proposal `applied` and
    carries its own arithmetic, so the rollback offer follows from the figures
    a reader can see rather than from a word somebody wrote.
    """
    decisions = {
        row["target_id"]: row
        for row in rows
        if row["kind"] == "remediation_decision" and row["version"] == version
    }
    checks = {
        row["target_id"]: row
        for row in rows
        if row["kind"] == "remediation_reverification" and row["version"] == version
    }
    if not decisions and not checks:
        return remediation

    proposals = []
    for proposal in remediation.proposals:
        update: dict[str, Any] = {}
        decision = decisions.get(proposal.id)
        if decision is not None:
            value = decision["value"] or {}
            applied = value.get("appliedCodeVersion")
            update.update(
                {
                    "state": "applied" if applied else value.get("decision", proposal.state),
                    "decided_by": decision["by"],
                    "decided_at": decision["at"],
                    "decision_note": str(value.get("note", "")),
                    "applied_code_version": applied,
                }
            )
        check = checks.get(proposal.id)
        if check is not None:
            result = Reverification.model_validate(check["value"])
            update["reverification"] = result
            if update.get("state") == "applied" and not result.worsened:
                update["state"] = "verified"
        proposals.append(proposal.model_copy(update=update) if update else proposal)
    return remediation.model_copy(update={"proposals": proposals})


#: A fix that has left the proposal stage. These rows outlive the run that
#: proposed them, because what happened to them is the phase's own result.
SETTLED = ("applied", "verified", "rolled-back")


async def _carried_proposals(
    conn: AsyncConnection, project_id: str, current_version: int, rows: list[store.Row]
) -> list[Any]:
    """Fixes applied at an earlier test version, with what became of them.

    A testing run writes the proposals its own scan produced, so the run that
    proves a fix worked is also the run whose artefact has never heard of that
    fix. Reading only the current version would empty the applied fixes panel
    at exactly the moment it has something to show, and the re-verification,
    which is the last quarter of this component's loop, would be stored and
    never seen.

    Only settled proposals come forward. One still awaiting a decision belongs
    to the scan that raised it and would otherwise ask a reader to decide,
    twice, about a code version that has moved on.
    """
    versions = sorted(
        {
            int(row["version"])
            for row in rows
            if row["kind"] == "remediation_decision"
            and (row["value"] or {}).get("appliedCodeVersion")
            and int(row["version"]) != current_version
        },
        reverse=True,
    )
    carried: list[Any] = []
    for version in versions:
        found = await store.artefacts_at(
            conn, project_id, version=version, kinds=("remediation-proposal",)
        )
        if "remediation-proposal" not in found:
            continue
        older = _decided_proposals(
            RemediationProposals.model_validate(found["remediation-proposal"]["body"]),
            rows,
            version,
        )
        carried.extend(one for one in older.proposals if one.state in SETTLED)
    return carried


async def _tested_code_version(conn: AsyncConnection, project_id: str, test_version: int) -> int:
    """The code version the run that produced this test version read."""
    runs = await store.project_runs(conn, project_id)
    for run in runs:  # newest first
        if run["component"] == "c3" and run["requirements_version"] == test_version:
            return int(run["source_version"] or 0)
    return 0


async def prefetch_testing(conn: AsyncConnection, project_id: str, owner: str) -> None:
    """Ask, in two round trips, what composing this snapshot asks one by one.

    Only a read-only request is answered from them; a read the lists miss is
    asked on its own.
    """
    await store.prefetch(
        conn,
        store.get_project_query(project_id, owner),
        store.current_test_version_query(project_id),
        store.current_code_version_query(project_id),
        store.stage_states_query(project_id),
        store.thread_query(project_id),
        store.gate_history_query(project_id, GATE_KIND),
        store.overlays_query(project_id),
        store.project_runs_query(project_id),
        store.latest_full_run_query(project_id, "c3"),
        _audit_query(project_id),
    )
    if not store.remembering(conn):
        return
    test_version = await store.current_test_version(conn, project_id)
    if test_version:
        await store.prefetch(
            conn, store.artefacts_at_query(project_id, test_version, TEST_ARTEFACT_KINDS)
        )


async def compose_testing(conn: AsyncConnection, project: store.Row) -> TestSnapshot:
    """Read everything for one project's testing phase and assemble the snapshot."""
    project_id = project["id"]

    test_version = await store.current_test_version(conn, project_id)
    code_version = await store.current_code_version(conn, project_id)
    artefacts = (
        await store.artefacts_at(conn, project_id, version=test_version, kinds=TEST_ARTEFACT_KINDS)
        if test_version
        else {}
    )
    stage_rows = await store.stage_states(conn, project_id)
    thread_rows = await store.thread(conn, project_id)
    history_rows = await store.gate_history(conn, project_id, kind=GATE_KIND)
    overlay_rows = await store.overlays(conn, project_id)

    def body(kind: str) -> dict[str, Any] | None:
        found = artefacts.get(kind)
        return found["body"] if found else None

    tests_body = body("test-report")
    tests = TestReport.model_validate(tests_body) if tests_body else None

    heal_body = body("heal-report")
    heal = HealReport.model_validate(heal_body) if heal_body else None

    validation_body = body("validation-report")
    validation = ValidationReport.model_validate(validation_body) if validation_body else None
    if validation is not None:
        validation = _decided_findings(validation, overlay_rows, test_version)

    remediation_body = body("remediation-proposal")
    remediation = (
        RemediationProposals.model_validate(remediation_body) if remediation_body else None
    )
    if remediation is not None:
        remediation = _decided_proposals(remediation, overlay_rows, test_version)
    # Only once this phase has a version of its own. A project that has never
    # been tested cannot have applied a fix, and the snapshot it would build
    # would carry proposals at version zero, which the contract refuses.
    carried = (
        await _carried_proposals(conn, project_id, test_version, overlay_rows)
        if test_version
        else []
    )
    if carried:
        # The artefact's own version stays what it is. These rows name the code
        # version they were applied at, which is the number that matters about
        # a fix and the one a reader can check against the file store.
        remediation = (
            remediation.model_copy(update={"proposals": [*remediation.proposals, *carried]})
            if remediation is not None
            else RemediationProposals(
                version=test_version,
                generated_at=carried[0].generated_at,
                target="an earlier testing run",
                proposals=carried,
            )
        )

    stages: dict[TestStageId, TestStageState] = {
        row["stage_id"]: _stage_row_to_model(row)
        for row in stage_rows
        if row["stage_id"] in TEST_STAGE_IDS
    }
    # A project that has never reached this phase has no rows at all, and the
    # contract says all seven are present. Pending is the truthful answer.
    for stage_id in TEST_STAGE_IDS:
        stages.setdefault(stage_id, TestStageState(id=stage_id))

    return TestSnapshot(
        project_id=project_id,
        target=selected_target(overlay_rows),
        test_version=test_version,
        code_version=code_version,
        tested_code_version=(
            await _tested_code_version(conn, project_id, test_version) if test_version else 0
        ),
        stages=stages,
        tests=tests,
        heal=heal,
        validation=validation,
        remediation=remediation,
        gate=_gate_state(history_rows, test_version),
        run=await run_status(conn, project_id, component="c3"),
        heal_decisions=heal_decisions(overlay_rows, test_version),
        audit=[
            TestAuditEntry(
                actor=row["actor"],
                action=row["action"],
                target=row["target"] or "",
                detail=row["detail"] or "",
                at=row["at"],
            )
            for row in await store.run(conn, _audit_query(project_id))
        ],
        thread=[
            TestThreadMessage(
                id=str(row["id"]),
                kind=row["kind"],
                stage_id=row["stage_id"],
                author=row["author"],
                content=row["content"],
                at=row["at"],
            )
            for row in thread_rows
            if row["stage_id"] in TEST_STAGE_IDS
        ],
    )
