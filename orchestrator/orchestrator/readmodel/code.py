"""Compose a CodeSnapshot from the rows that hold it.

The design snapshot's shape, for the code phase: each artefact lives in its own
versioned row validated against its own schema, and this puts them together
with stage, gate and thread state into the one payload the browser reads.

Three things are derived here and never stored.

`generatedFromDesignVersion` comes from the run that produced the current code
version, so "the design moved on" is arithmetic over two numbers rather than a
flag somebody has to remember to set.

The contract diff is computed between the two newest contract versions, so the
receipt for a scope change is always current and nothing has to store it.

The stack selection is laid over the proposal, exactly as the design snapshot
lays the architecture selection over its candidates: nothing downstream reads
the stack, so choosing one is a decision about an artefact rather than an
input to a generation, and it costs no run.

File bodies are deliberately absent: the client polls this every 1.2 seconds
while anything is generating, and a run writes tens of source files. They are
served one at a time from their own route.
"""

from typing import Any

from psycopg import AsyncConnection
from sdlc_contracts import (
    CODE_STAGE_IDS,
    ApiContract,
    ApiContractArtefact,
    CodeRepository,
    CodeSnapshot,
    CodeStageId,
    CodeStageState,
    CodeThreadMessage,
    ContractAgreement,
    GateDecision,
    GateState,
    NextSprint,
    SprintPlan,
    SprintScope,
    TechStackArtefact,
    diff_contracts,
)

from ..db import store
from ..model_use import kept_model_use
from ..sprints import latest_choices, next_sprint
from .runs import run_status

CODE_ARTEFACT_KINDS = (
    "sprint-scope",
    "tech-stack",
    "api-contract",
    "contract-agreement",
    "code-repository",
)

GATE_KIND = "c2-code-review"

#: What the next sprint is divided from, read at the current design version.
SPRINT_PLAN = ("sprint-plan",)


def _stage_row_to_model(row: store.Row) -> CodeStageState:
    return CodeStageState(
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


async def _generated_from(conn: AsyncConnection, project_id: str, code_version: int) -> int:
    """The design version the run that produced this code version read.

    A version written by applying an accepted security fix has no run of its
    own and inherits the provenance of the version it patched, which is the
    same question the testing phase asks and now the same answer.
    """
    return await store.design_version_for_code(conn, project_id, code_version) or 0


async def _diff(conn: AsyncConnection, project_id: str):
    """Between the two newest contract versions, or nothing before the second.

    A diff of one version against itself would be an empty receipt that reads
    as "nothing changed" rather than as "there is nothing to compare yet".
    """
    versions = await store.artefact_versions(conn, project_id, "api-contract")
    if len(versions) < 2:
        return None
    previous, current = versions[-2], versions[-1]
    rows = await store.artefacts_at(conn, project_id, version=previous, kinds=("api-contract",))
    newer = await store.artefacts_at(conn, project_id, version=current, kinds=("api-contract",))
    if "api-contract" not in rows or "api-contract" not in newer:
        return None
    before: ApiContract = ApiContractArtefact.model_validate(rows["api-contract"]["body"]).contract
    after: ApiContract = ApiContractArtefact.model_validate(newer["api-contract"]["body"]).contract
    return diff_contracts(before, after)


#: The design review, whose decision on the current design version code waits for.
DESIGN_GATE_KIND = "c1-design-review"


async def design_blocker(conn: AsyncConnection, project_id: str) -> str | None:
    """Why code cannot be generated from the design now, or None when it can.

    Code is generated from the current design version, so that version has to
    be the approved one. "Some version was approved once" let a design changed
    after its approval feed a code run nobody had reviewed: Cold Chain's design
    version 3 waited on its review while "Generate again" read it.
    """
    history = await store.gate_history(conn, project_id, kind=DESIGN_GATE_KIND)
    if not any(row["decision"] == "approved" for row in history):
        return (
            "this project's design has not been approved, so there is nothing settled to "
            "generate code from"
        )
    version = await store.current_version(conn, project_id)
    if await store.version_is_approved(
        conn, project_id, gate_kind=DESIGN_GATE_KIND, version=version
    ):
        # A design run still active here is settling the approval it was just
        # given, not regenerating: an approved version's artefacts are settled
        # and nothing it does can change them. Read as a regeneration, the page
        # said "the design is being regenerated" for up to a minute after every
        # approval.
        return None
    if await store.active_run(conn, project_id, component="c1") is not None:
        return (
            f"the design is being regenerated at version {version}; code is generated once "
            "its review approves it"
        )
    return (
        f"the design changed after it was approved: design version {version} waits on its "
        "review, and code is generated from an approved design"
    )


async def prefetch_code(conn: AsyncConnection, project_id: str, owner: str) -> None:
    """Ask, in two round trips, what composing this snapshot asks one by one.

    The second asks what the versions the first named settle. Only a read-only
    request is answered from them; a read the lists miss is asked on its own.
    """
    await store.prefetch(
        conn,
        store.get_project_query(project_id, owner),
        store.current_code_version_query(project_id),
        store.current_version_query(project_id),
        store.stage_states_query(project_id),
        store.thread_query(project_id),
        store.gate_history_query(project_id, GATE_KIND),
        store.overlays_query(project_id),
        store.gate_history_query(project_id, "c1-design-review"),
        store.active_run_query(project_id, "c1"),
        store.artefact_versions_query(project_id, "api-contract"),
        store.latest_full_run_query(project_id, "c2"),
    )
    if not store.remembering(conn):
        return
    code_version = await store.current_code_version(conn, project_id)
    design_version = await store.current_version(conn, project_id)
    contracts = await store.artefact_versions(conn, project_id, "api-contract")
    second = [store.version_is_approved_query(project_id, "c1-design-review", design_version)]
    if code_version:
        second.append(store.artefacts_at_query(project_id, code_version, CODE_ARTEFACT_KINDS))
        second.append(store.run_for_version_query(project_id, "c2", code_version))
        second.append(store.artefacts_at_query(project_id, design_version, SPRINT_PLAN))
    if len(contracts) >= 2:
        second.extend(
            store.artefacts_at_query(project_id, version, ("api-contract",))
            for version in contracts[-2:]
        )
    await store.prefetch(conn, *second)


async def _next_sprint(
    conn: AsyncConnection, project_id: str, design_version: int, overlay_rows: list[store.Row]
) -> NextSprint | None:
    """What planning the next sprint would add, from the plan generating would read.

    The current design version's, because generating again reads that one,
    and the same decisions the scope stage applies, so the page shows what the
    action will do.
    """
    found = await store.artefacts_at(conn, project_id, version=design_version, kinds=SPRINT_PLAN)
    if "sprint-plan" not in found:
        return None
    plan = SprintPlan.model_validate(found["sprint-plan"]["body"])
    return next_sprint(plan, latest_choices(overlay_rows))


async def compose_code(conn: AsyncConnection, project: store.Row) -> CodeSnapshot:
    """Read everything for one project's code phase and assemble the snapshot."""
    project_id = project["id"]

    code_version = await store.current_code_version(conn, project_id)
    design_version = await store.current_version(conn, project_id)
    artefacts = (
        await store.artefacts_at(conn, project_id, version=code_version, kinds=CODE_ARTEFACT_KINDS)
        if code_version
        else {}
    )
    stage_rows = await store.stage_states(conn, project_id)
    thread_rows = await store.thread(conn, project_id)
    history_rows = await store.gate_history(conn, project_id, kind=GATE_KIND)
    overlay_rows = await store.overlays(conn, project_id)

    def body(kind: str) -> dict[str, Any] | None:
        found = artefacts.get(kind)
        return found["body"] if found else None

    scope_body = body("sprint-scope")
    scope = SprintScope.model_validate(scope_body) if scope_body else None
    next_up = await _next_sprint(conn, project_id, design_version, overlay_rows) if scope else None

    stack_body = body("tech-stack")
    tech_stack = TechStackArtefact.model_validate(stack_body) if stack_body else None
    # The newest selection: overlays come oldest first, and the first one found
    # made Select after a regeneration appear to do nothing.
    selection = next(
        (row for row in reversed(overlay_rows) if row["kind"] == "stack_selection"), None
    )
    if tech_stack is not None and selection is not None:
        chosen = str(selection["value"])
        if chosen in {candidate.id for candidate in tech_stack.candidates}:
            tech_stack = tech_stack.model_copy(
                update={
                    "selected_id": chosen,
                    "selected_at": selection["at"],
                    "selected_by": selection["by"],
                }
            )

    contract_body = body("api-contract")
    contract = ApiContractArtefact.model_validate(contract_body) if contract_body else None

    agreement_body = body("contract-agreement")
    agreement = ContractAgreement.model_validate(agreement_body) if agreement_body else None

    repository_body = body("code-repository")
    repository = CodeRepository.model_validate(repository_body) if repository_body else None

    # Only the code vocabulary. stage_states and thread_messages hold the
    # design phase's rows too, and CodeStageId is a Literal over eight ids, so
    # an unfiltered build is a ValidationError on the first design row.
    stages: dict[CodeStageId, CodeStageState] = {
        row["stage_id"]: _stage_row_to_model(row)
        for row in stage_rows
        if row["stage_id"] in CODE_STAGE_IDS
    }
    # A project that has never reached the code phase has no rows at all, and
    # the contract says all eight are present. Pending is the truthful answer.
    for stage_id in CODE_STAGE_IDS:
        stages.setdefault(stage_id, CodeStageState(id=stage_id))

    # A version an accepted fix wrote has no review of its own: the page read
    # it as undecided, with no decision anywhere to make.
    covering = store.approval_covering(
        code_version,
        {int(row["requirements_version"]) for row in history_rows if row["decision"] == "approved"},
        store.patches_in(overlay_rows),
    )

    return CodeSnapshot(
        project_id=project_id,
        code_version=code_version,
        design_version=design_version,
        design_blocker=await design_blocker(conn, project_id),
        generated_from_design_version=(
            await _generated_from(conn, project_id, code_version) if code_version else 0
        ),
        stages=stages,
        scope=scope,
        next_sprint=next_up,
        tech_stack=tech_stack,
        contract=contract,
        agreement=agreement,
        repository=repository,
        diff=await _diff(conn, project_id),
        gate=_gate_state(history_rows, code_version),
        approved_through=covering if covering and covering != code_version else None,
        run=await run_status(conn, project_id, component="c2"),
        thread=[
            CodeThreadMessage(
                id=str(row["id"]),
                kind=row["kind"],
                stage_id=row["stage_id"],
                author=row["author"],
                content=row["content"],
                at=row["at"],
            )
            for row in thread_rows
            if row["stage_id"] in CODE_STAGE_IDS
        ],
    )
