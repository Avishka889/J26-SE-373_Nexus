"""The release guards: what must be true before anything ships, checked where it matters.

The guards are one pure function over facts gathered once, so the gate decision
route, the snapshot's `blocking` list, the handover after the gate, and the saga
before its first step all ask the same question the same way. A refusal says,
in words, what is missing, and names the update it is about when there is one.

| Guard | What must hold |
|---|---|
| G1 | Every included Medium or High update is approved, at the level it has now; a High approval carries a review note (FR17, FR18) |
| G2 | Every included High update has a prepared, restorable rollback (FR17, FR19) |
| G3 | The candidate was verified in staging, and carries no update a person left out |
| G4 | The tests the run started from are approved, are still the tests approved, and no newer code has approved tests |
| G5 | A cloud release is turned on, has its connections, and carries a go ahead |
| G6 | The release goes where its plan was made for: a plan's steps name the adapters that carry it out |
| G7 | The pipeline that carries it validated: every generated file passed every validator that applies (NFR5) |
| G8 | No Critical or High finding in the tested code ships undecided: each is dismissed, or its risk accepted with a note |

A decision follows the update, not the version it was taken at (an update keeps
its id when the same move is assessed again), and the newest one is the one
that counts. It stops counting when the update's level has risen above the level
it was taken at: a Medium approval says nothing about a High risk. Low updates
ship without a decision, by the policy FR17 sets, unless a person left them out.
The snapshot reads decisions by these same two rules.

What may ship is the code the newest approved tests measured. Newer code waits
for its own tests and holds nothing back: G4 compared with the newest code
written, tested or not, so once the next sprint's code existed nothing could be
released until it was tested too.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sdlc_contracts import (
    Blocker,
    DeployPlan,
    PipelineConfig,
    ReleaseCandidate,
    RiskReport,
    RollbackPlan,
    SecurityFinding,
    ValidationReport,
)

from ..db import store

TEST_GATE_KIND = "c3-test-review"
CLOUD_PROVIDERS = ("github", "vercel", "render")
_ORDER = {"low": 0, "medium": 1, "high": 2}


def newest_decisions(overlay_rows: list[store.Row]) -> dict[str, store.Row]:
    """The newest decision row per update, across every deploy version."""
    newest: dict[str, store.Row] = {}
    for row in overlay_rows:
        if row["kind"] == "update_decision":
            newest[row["target_id"]] = row
    return newest


def still_counts(level_at_decision: object, level_now: str) -> bool:
    """A decision counts unless the update's level has risen above the one it was taken at."""
    return level_at_decision in _ORDER and _ORDER[str(level_at_decision)] >= _ORDER[level_now]


@dataclass(frozen=True)
class ReleaseFacts:
    """Everything the guards read, gathered once."""

    deploy_version: int
    target: str
    risk: RiskReport | None = None
    candidate: ReleaseCandidate | None = None
    rollback: RollbackPlan | None = None
    #: Update id to its newest decision, from any deploy version:
    #: {"decision", "note", "levelAtDecision"}.
    decisions: dict[str, dict[str, Any]] = field(default_factory=dict)
    test_version: int = 0
    test_approved: bool = False
    tested_code: int = 0
    #: The code version the newest approved tests measured: what may ship now.
    releasable_code: int = 0
    #: The tests at the tested code changed after their approval recorded them.
    tests_changed: bool = False
    cloud_enabled: bool = False
    #: The providers whose connection's last check says it works.
    connected: frozenset[str] = frozenset()
    #: The providers connected whose last check does not, each with why.
    failing: Mapping[str, str] = field(default_factory=dict)
    go_ahead: bool = False
    #: The target this deploy version's plan was made for, or None with no plan.
    plan_target: str | None = None
    #: The pipeline generated at this deploy version, or None before there is one.
    pipeline: PipelineConfig | None = None
    #: The security findings in the code the release ships: the validation
    #: report of the test version the run started from.
    findings: list[SecurityFinding] = field(default_factory=list)
    #: Finding id to the newest decision on it at that test version: {"decision", "note"}.
    finding_decisions: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: The verified deployments that still stand (`store.standing_release_ids`),
    #: or None where nobody asked.
    standing: frozenset[str] | None = None


def _key(risk: RiskReport | None, update_id: str) -> str:
    for assessment in risk.assessments if risk else []:
        if assessment.update_id == update_id:
            return assessment.key
    return update_id


def release_blockers(facts: ReleaseFacts) -> list[Blocker]:
    """Every reason this release may not go ahead, or none."""
    blockers: list[Blocker] = []
    risk, candidate, rollback = facts.risk, facts.candidate, facts.rollback
    levels = {a.update_id: a.arbitration.final for a in (risk.assessments if risk else [])}
    included = list(candidate.included) if candidate else []

    # G1: Medium and High need a person, at the level they have now.
    for update_id in included:
        level = levels.get(update_id, "high")
        if level == "low":
            continue
        decision = facts.decisions.get(update_id)
        name = _key(risk, update_id)
        if decision is None:
            blockers.append(
                Blocker(
                    code="G1",
                    message=f"{name} is {level.capitalize()} and needs a person's approval",
                    update_id=update_id,
                )
            )
            continue
        at = decision.get("levelAtDecision")
        if not still_counts(at, level):
            blockers.append(
                Blocker(
                    code="G1",
                    message=(
                        f"{name} was decided at {str(at).capitalize()} and is now "
                        f"{level.capitalize()}, so that decision does not count"
                    ),
                    update_id=update_id,
                )
            )
        elif (
            decision.get("decision") == "approved" and level == "high" and not decision.get("note")
        ):
            blockers.append(
                Blocker(
                    code="G1",
                    message=f"{name} is High, and its approval carries no review note",
                    update_id=update_id,
                )
            )

    # G2: a High update ships only with a rollback prepared for it.
    high = [u for u in included if levels.get(u, "high") == "high"]
    if high and rollback is None:
        blockers.append(Blocker(code="G2", message="there is no rollback plan for this candidate"))
    elif rollback is not None:
        if candidate is not None and rollback.candidate_hash != candidate.candidate_hash:
            blockers.append(
                Blocker(code="G2", message="the rollback plan was written for another candidate")
            )
        # The plan is fixed at analysis, and the release it restores can be rolled
        # back after that (review item C4-9).
        target = rollback.restore_target
        if (
            high
            and target is not None
            and facts.standing is not None
            and target.deployment_id not in facts.standing
        ):
            blockers.append(
                Blocker(
                    code="G2",
                    message=(
                        f"the rollback plan restores deploy version {target.deploy_version}, "
                        "which is no longer a verified release that succeeded. Analyse again, "
                        "so the plan restores one that is"
                    ),
                )
            )
        reasons = {item.update_id: item.reason for item in rollback.updates}
        for update_id in rollback.blocks:
            if update_id in included:
                blockers.append(
                    Blocker(
                        code="G2",
                        message=(
                            f"{_key(risk, update_id)} is High and its rollback is unavailable: "
                            f"{reasons.get(update_id) or rollback.unrestorable_reason}"
                        ),
                        update_id=update_id,
                    )
                )

    # G3: what staging verified is what was approved.
    if candidate is None:
        blockers.append(Blocker(code="G3", message="no release candidate was built"))
    else:
        if not candidate.verified:
            failed = next(
                (s.name for s in candidate.steps if s.outcome in ("failed", "timed-out")), None
            )
            why = (
                f"its {failed} step failed"
                if failed
                else "it did not serve its own fingerprint"
                if candidate.fingerprint != candidate.candidate_hash
                else "a smoke request did not answer"
            )
            blockers.append(
                Blocker(code="G3", message=f"the candidate was not verified in staging: {why}")
            )
        for update_id in included:
            decision = facts.decisions.get(update_id) or {}
            counted = still_counts(decision.get("levelAtDecision"), levels.get(update_id, "high"))
            if counted and decision.get("decision") in ("rejected", "deferred"):
                blockers.append(
                    Blocker(
                        code="G3",
                        message=(
                            f"{_key(risk, update_id)} was {decision['decision']} at review and the "
                            "candidate still carries it: request changes to rebuild without it"
                        ),
                        update_id=update_id,
                    )
                )

    # G4: the tests that justify this release still hold.
    if not facts.test_approved:
        blockers.append(
            Blocker(
                code="G4",
                message=f"test version {facts.test_version} is not approved, so nothing may ship",
            )
        )
    elif facts.tests_changed:
        blockers.append(
            Blocker(
                code="G4",
                message=(
                    f"the tests at code version {facts.tested_code} changed after test version "
                    f"{facts.test_version} was approved: run the tests again and approve them, "
                    "so the release runs the tests a person approved"
                ),
            )
        )
    elif facts.tested_code != facts.releasable_code:
        blockers.append(
            Blocker(
                code="G4",
                message=(
                    f"this analysis is of code version {facts.tested_code}, and code version "
                    f"{facts.releasable_code} has approved tests now: analyse the updates again "
                    "to release it"
                ),
            )
        )

    # G5: the cloud is opt in, connected, and asked for each time.
    if facts.target == "cloud":
        if not facts.cloud_enabled:
            blockers.append(
                Blocker(code="G5", message="cloud releases are turned off on this orchestrator")
            )
        for provider in CLOUD_PROVIDERS:
            if provider in facts.failing:
                blockers.append(
                    Blocker(
                        code="G5",
                        message=(
                            f"the {provider} connection is not working: "
                            f"{facts.failing[provider]} Check it again in Settings"
                        ),
                    )
                )
            elif provider not in facts.connected:
                blockers.append(
                    Blocker(code="G5", message=f"there is no working {provider} connection")
                )
        if not facts.go_ahead:
            blockers.append(
                Blocker(
                    code="G5",
                    message=(
                        "a cloud release spends provider minutes, so the decision must carry "
                        "the go ahead"
                    ),
                )
            )

    # G6: the plan is made for the target chosen when the analysis runs, and its
    # steps name the adapters that carry the release out. A target changed at the
    # review would record a release to one target and carry out the other's plan.
    if facts.plan_target is not None and facts.plan_target != facts.target:
        blockers.append(
            Blocker(
                code="G6",
                message=(
                    f"this version was planned for the {facts.plan_target} target, not the "
                    f"{facts.target} target chosen now: request changes, and the next version "
                    f"is planned for {facts.target}"
                ),
            )
        )

    # G7: the pipeline that carries the release validated. Its validity was
    # computed and read by no guard (review item C4-8).
    pipeline = facts.pipeline
    if pipeline is not None and not pipeline.valid:
        blockers.append(Blocker(code="G7", message=_pipeline_problem(pipeline)))

    # G8: no Critical or High weakness ships undecided. The test approval only
    # counted the open findings, and no guard read them (review item C3-8).
    for finding in facts.findings:
        if finding.severity not in ("critical", "high"):
            continue
        decision = facts.finding_decisions.get(finding.id) or {}
        kind, note = decision.get("decision"), str(decision.get("note") or "").strip()
        if kind == "dismissed" or (kind == "accepted" and note):
            continue
        named = (
            f"{finding.cwe} {finding.title}, {finding.severity.capitalize()} "
            f"({finding.base_score}), at {finding.evidence.path}:{finding.evidence.start_line}"
        )
        blockers.append(
            Blocker(
                code="G8",
                message=(
                    f"{named} was accepted with no note saying why it can ship: say why, "
                    "or fix it and test again"
                    if kind == "accepted"
                    else f"{named} is open in the code this release ships: fix it and test "
                    "again, dismiss it with a note saying why it does not apply, or accept "
                    "the risk with a note saying why it can ship"
                ),
            )
        )
    return blockers


def _pipeline_problem(pipeline: PipelineConfig) -> str:
    """What kept a pipeline from validating, file by file and validator by validator."""
    if not pipeline.stack.supported:
        return f"no pipeline was generated: {pipeline.stack.reason}"
    problems = []
    for file in pipeline.files:
        if not file.validations:
            problems.append(f"{file.path}, which no validator checked")
        for check in file.validations:
            if check.outcome == "failed":
                problems.append(
                    f"{file.path}, {check.validator} failed ({'; '.join(check.findings)})"
                )
            elif check.outcome == "not-run":
                problems.append(f"{file.path}, {check.validator} did not run ({check.reason})")
    return "the generated pipeline did not validate: " + (
        "; ".join(problems) or "no file was generated"
    )


#: The verdicts of a connection's check that say it can be used: as it is, or
#: with limits the check names.
WORKING_VERDICTS = frozenset({"SUITABLE", "WORKABLE"})


def cloud_connections(connections: Mapping[str, Any]) -> tuple[frozenset[str], dict[str, str]]:
    """Which of a cloud release's connections work, and which are there but do not, with why.

    A connection counted when it merely existed. Its check's verdict is stored
    beside it and was never read, so a token the provider refused passed G5 and
    the release failed at its first call to that provider (review item X-12).
    One whose check was never recorded is not known to work either.
    """
    working: set[str] = set()
    failing: dict[str, str] = {}
    for provider in CLOUD_PROVIDERS:
        meta = connections.get(provider)
        if not meta:
            continue
        probe = meta.get("probe") or {}
        if probe.get("verdict") in WORKING_VERDICTS:
            working.add(provider)
        else:
            failing[provider] = probe.get("reason") or "it has not been checked"
    return frozenset(working), failing


#: The artefacts the release guards read at a deploy version.
FACT_KINDS = ("risk-report", "release-candidate", "rollback-plan", "deploy-plan", "pipeline-config")


async def gather(
    conn: Any,
    project_id: str,
    *,
    owner: str,
    deploy_version: int,
    target: str,
    test_version: int,
    go_ahead: bool = False,
) -> ReleaseFacts:
    """The facts at one deploy version, read from the store."""
    from ..config import get_settings

    found = await store.artefacts_at(conn, project_id, version=deploy_version, kinds=FACT_KINDS)

    def parsed(kind: str, model: Any) -> Any:
        return model.model_validate(found[kind]["body"]) if kind in found else None

    overlay_rows = await store.overlays(conn, project_id)
    decisions = {
        update_id: dict(row["value"])
        for update_id, row in newest_decisions(overlay_rows).items()
        if isinstance(row["value"], dict)
    }
    # The findings in the code this release ships, and what a person decided
    # about each at that test version, as the testing page shows them.
    scanned = (
        await store.artefacts_at(
            conn, project_id, version=test_version, kinds=("validation-report",)
        )
        if test_version
        else {}
    )
    findings = (
        ValidationReport.model_validate(scanned["validation-report"]["body"]).findings
        if "validation-report" in scanned
        else []
    )
    finding_decisions = {
        row["target_id"]: dict(row["value"])
        for row in overlay_rows
        if row["kind"] == "finding_decision"
        and row["version"] == test_version
        and isinstance(row["value"], dict)
    }
    tested = await store.run_for_version(conn, project_id, component="c3", version=test_version)
    # What the approval recorded of its tests, against what is stored now: a later
    # run on the same code rewrites them, and the staging build reads them (X-2).
    approval = next(
        (
            row
            for row in reversed(await store.gate_history(conn, project_id, kind=TEST_GATE_KIND))
            if row["decision"] == "approved" and row["requirements_version"] == test_version
        ),
        None,
    )
    recorded = ((approval or {}).get("payload") or {}).get("testFilesSha256")
    tests_changed = bool(recorded) and recorded != await store.test_files_digest(
        conn, project_id, test_version
    )
    body = await store.settings_body(conn, owner)
    connected, failing = cloud_connections(body.get("connections") or {})
    return ReleaseFacts(
        deploy_version=deploy_version,
        target=target,
        risk=parsed("risk-report", RiskReport),
        candidate=parsed("release-candidate", ReleaseCandidate),
        rollback=parsed("rollback-plan", RollbackPlan),
        decisions=decisions,
        test_version=test_version,
        test_approved=bool(test_version)
        and await store.version_is_approved(
            conn, project_id, gate_kind=TEST_GATE_KIND, version=test_version
        ),
        tested_code=int((tested or {}).get("source_version") or 0),
        releasable_code=await store.releasable_code_version(conn, project_id),
        tests_changed=tests_changed,
        cloud_enabled=get_settings().c4_cloud_enabled,
        connected=connected,
        failing=failing,
        go_ahead=go_ahead,
        plan_target=plan.target if (plan := parsed("deploy-plan", DeployPlan)) else None,
        pipeline=parsed("pipeline-config", PipelineConfig),
        findings=list(findings),
        finding_decisions=finding_decisions,
        standing=await store.standing_release_ids(conn, project_id),
    )


def rollback_blockers(
    release: store.Row, plan: RollbackPlan | None, restores: store.Row | None
) -> list[Blocker]:
    """Why a rollback of this release cannot start, or nothing (FR20, NFR6).

    The decision itself is the person's; these are the facts that must hold for
    that decision to have somewhere safe to go.
    """
    if release["kind"] != "release":
        return [Blocker(code="R1", message="only a release can be rolled back")]
    # One kept unverified after a declined rollback still serves, so a person who
    # declined can still decide to roll it back.
    if release["state"] not in ("awaiting-rollback-approval", "succeeded", "kept-unverified"):
        return [
            Blocker(
                code="R1",
                message=f"a release that is {release['state']} has nothing to roll back",
            )
        ]
    if plan is None:
        return [Blocker(code="R2", message="no rollback plan was prepared for this release")]
    if not plan.restorable or plan.restore_target is None:
        return [
            Blocker(
                code="R2",
                message=f"there is nothing to roll back to: {plan.unrestorable_reason}",
            )
        ]
    if restores is None or not restores["verified"]:
        return [
            Blocker(
                code="R3",
                message="the release the plan restores is no longer on record as verified",
            )
        ]
    if restores["state"] != "succeeded":
        return [
            Blocker(
                code="R3",
                message=(
                    f"the release the plan restores, deploy version {restores['deploy_version']}, "
                    f"is {restores['state']} now, and no other verified release stands to "
                    "restore"
                ),
            )
        ]
    return []
