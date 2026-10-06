"""The release guards, one row per reason a release may not go ahead.

The risk report is the canned component's, built by the real rules: express is
High (a major), zod Medium (a minor), vite Low (a patch). The candidate and the
rollback plan are built here per row. A release that meets every guard has
nothing blocking it; each row then breaks one thing, and exactly that guard
says so, naming the update when there is one.
"""

import asyncio
from datetime import UTC, datetime

import pytest
from orchestrator.clients.canned_c4 import CannedC4
from orchestrator.deploy.guards import (
    ReleaseFacts,
    cloud_connections,
    release_blockers,
    still_counts,
)
from sdlc_contracts import (
    ArchitecturalLayout,
    BuildStepReport,
    CvssFactors,
    DeploySnapshot,
    EvidenceSpan,
    FileValidation,
    PipelineConfig,
    PipelineFile,
    ReleaseCandidate,
    RestoreStep,
    RollbackPlan,
    SecurityFinding,
    SmokeCheck,
    StackSupport,
    UpdateRollback,
    VerificationCheck,
    VerifiedRelease,
)

from .conftest import needs_db
from .test_deployment_routes import (  # noqa: F401 - client is a fixture
    _approved_tests,
    _decide_every_update,
    _deploy_run,
    client,
)

NOW = datetime(2026, 9, 28, tzinfo=UTC)
CANDIDATE = "c" * 64


async def _canned_risk():
    canned = CannedC4()
    found = await canned.detect_updates(
        {}, target="generated", version=1, code_version=1, test_version=1
    )
    return (await canned.assess_risk(found.report, None, None, version=1)).artefact


RISK = asyncio.run(_canned_risk())
IDS = {item.package: item.update_id for item in RISK.assessments}
EXPRESS, ZOD, VITE = IDS["express"], IDS["zod"], IDS["vite"]
LEVELS = {item.package: item.arbitration.final for item in RISK.assessments}


def _candidate(*included: str, failing: str | None = None, serves: str = CANDIDATE):
    return ReleaseCandidate(
        version=1,
        generated_at=NOW,
        code_version=1,
        candidate_hash=CANDIDATE,
        included=list(included),
        image="sdlc-c4-p:v1",
        image_digest="sha256:" + "e" * 64,
        toolchain="scripted",
        isolation="scripted",
        steps=[
            BuildStepReport(
                name=name,
                command=name,
                outcome="failed" if name == failing else "passed",
                duration_seconds=1.0,
            )
            for name in ("candidate", "lockfile", "install", "test", "image", "boot")
        ],
        smoke=[SmokeCheck(path="/", status_code=200, ok=True)],
        fingerprint=serves,
    )


PREVIOUS = VerifiedRelease(
    deployment_id="d-1",
    deploy_version=1,
    candidate_hash="b" * 64,
    target="local",
    image_digest="sha256:" + "d" * 64,
    verified_at=NOW,
)


def _plan(*, restorable: bool, candidate: str = CANDIDATE) -> RollbackPlan:
    if not restorable:
        return RollbackPlan(
            version=1,
            generated_at=NOW,
            candidate_hash=candidate,
            restorable=False,
            unrestorable_reason="this project has no verified release yet",
            updates=[
                UpdateRollback(
                    update_id=EXPRESS,
                    level="high",
                    status="unavailable",
                    reason="this project has no verified release yet",
                )
            ],
        )
    return RollbackPlan(
        version=1,
        generated_at=NOW,
        candidate_hash=candidate,
        restore_target=PREVIOUS,
        restorable=True,
        steps=[RestoreStep(id="start", label="start", provider="local-docker", action="start it")],
        checks=[VerificationCheck(id="fp", kind="fingerprint", role="app", expect="b" * 64)],
        updates=[UpdateRollback(update_id=EXPRESS, level="high", status="prepared")],
    )


def _decision(decision: str, level: str, note: str = "reviewed") -> dict:
    return {"decision": decision, "levelAtDecision": level, "note": note}


def _facts(**changed) -> ReleaseFacts:
    base = {
        "deploy_version": 1,
        "target": "local",
        "risk": RISK,
        "candidate": _candidate(ZOD, VITE),
        "rollback": None,
        "decisions": {ZOD: _decision("approved", "medium")},
        "test_version": 1,
        "test_approved": True,
        "tested_code": 1,
        "releasable_code": 1,
    }
    return ReleaseFacts(**{**base, **changed})


def _codes(facts: ReleaseFacts) -> list[tuple[str, str | None]]:
    return [(blocker.code, blocker.update_id) for blocker in release_blockers(facts)]


def test_the_canned_levels_are_the_ones_these_rows_assume() -> None:
    assert LEVELS == {"express": "high", "zod": "medium", "vite": "low"}


def test_a_release_that_meets_every_guard_has_nothing_blocking_it() -> None:
    assert release_blockers(_facts()) == []


class TestG1:
    def test_a_medium_update_nobody_decided(self) -> None:
        assert _codes(_facts(decisions={})) == [("G1", ZOD)]

    def test_an_approval_taken_at_a_lower_level_does_not_count(self) -> None:
        facts = _facts(
            candidate=_candidate(EXPRESS),
            rollback=_plan(restorable=True),
            decisions={EXPRESS: _decision("approved", "medium")},
        )
        [blocker] = release_blockers(facts)
        assert (blocker.code, blocker.update_id) == ("G1", EXPRESS)
        assert "decided at Medium and is now High" in blocker.message

    def test_a_high_approval_without_a_review_note(self) -> None:
        facts = _facts(
            candidate=_candidate(EXPRESS),
            rollback=_plan(restorable=True),
            decisions={EXPRESS: _decision("approved", "high", note="")},
        )
        assert _codes(facts) == [("G1", EXPRESS)]

    def test_a_decision_taken_at_a_higher_level_still_counts(self) -> None:
        assert _codes(_facts(decisions={ZOD: _decision("approved", "high")})) == []
        assert still_counts("high", "medium") and not still_counts("low", "medium")
        assert not still_counts(None, "low")


class TestG2:
    def test_a_high_update_with_no_rollback_plan(self) -> None:
        facts = _facts(
            candidate=_candidate(EXPRESS), decisions={EXPRESS: _decision("approved", "high")}
        )
        assert _codes(facts) == [("G2", None)]

    def test_a_high_update_whose_rollback_is_unavailable(self) -> None:
        facts = _facts(
            candidate=_candidate(EXPRESS),
            rollback=_plan(restorable=False),
            decisions={EXPRESS: _decision("approved", "high")},
        )
        [blocker] = release_blockers(facts)
        assert (blocker.code, blocker.update_id) == ("G2", EXPRESS)
        assert blocker.message.endswith("no verified release yet")

    def test_a_plan_restoring_a_release_that_no_longer_stands(self) -> None:
        # The plan is fixed at analysis. The release it restores can be rolled
        # back after that, and it stayed verified, so the plan still passed
        # (review item C4-9).
        high = {
            "candidate": _candidate(EXPRESS),
            "rollback": _plan(restorable=True),
            "decisions": {EXPRESS: _decision("approved", "high")},
        }
        gone = _facts(**high, standing=frozenset())
        there = _facts(**high, standing=frozenset({PREVIOUS.deployment_id}))

        [blocker] = release_blockers(gone)
        assert blocker.code == "G2"
        assert "is no longer a verified release that succeeded" in blocker.message
        assert "Analyse again" in blocker.message
        assert release_blockers(there) == []

    def test_a_rollback_plan_written_for_another_candidate(self) -> None:
        facts = _facts(rollback=_plan(restorable=True, candidate="f" * 64))
        assert _codes(facts) == [("G2", None)]


class TestG3:
    def test_no_candidate_was_built(self) -> None:
        assert _codes(_facts(candidate=None)) == [("G3", None)]

    @pytest.mark.parametrize(
        ("candidate", "why"),
        [
            (_candidate(ZOD, VITE, failing="test"), "its test step failed"),
            (_candidate(ZOD, VITE, serves="9" * 64), "did not serve its own fingerprint"),
        ],
    )
    def test_a_candidate_staging_did_not_verify(self, candidate, why) -> None:
        [blocker] = release_blockers(_facts(candidate=candidate))
        assert blocker.code == "G3" and why in blocker.message

    def test_an_update_left_out_at_review_that_the_candidate_still_carries(self) -> None:
        facts = _facts(
            decisions={
                ZOD: _decision("approved", "medium"),
                VITE: _decision("rejected", "low", "breaks the build"),
            }
        )
        [blocker] = release_blockers(facts)
        assert (blocker.code, blocker.update_id) == ("G3", VITE)
        assert "request changes to rebuild without it" in blocker.message


class TestG4:
    def test_tests_that_are_not_approved(self) -> None:
        assert _codes(_facts(test_approved=False)) == [("G4", None)]

    def test_an_analysis_of_code_older_than_the_newest_tested_code(self) -> None:
        [blocker] = release_blockers(_facts(releasable_code=2))
        assert blocker.code == "G4"
        assert "code version 2 has approved tests now" in blocker.message
        assert "analyse the updates again" in blocker.message


class TestG5:
    def test_the_cloud_needs_its_switch_its_connections_and_a_go_ahead(self) -> None:
        messages = [b.message for b in release_blockers(_facts(target="cloud"))]
        assert messages == [
            "cloud releases are turned off on this orchestrator",
            "there is no working github connection",
            "there is no working vercel connection",
            "there is no working render connection",
            "a cloud release spends provider minutes, so the decision must carry the go ahead",
        ]

    def test_a_connection_whose_check_failed_is_not_a_working_one(self) -> None:
        """A connection counted when it merely existed: its check's verdict was
        stored and never read, so a revoked token passed G5 and the release
        failed at its first provider call (review item X-12)."""
        facts = _facts(
            target="cloud",
            cloud_enabled=True,
            connected=frozenset({"github", "vercel"}),
            failing={"render": "Render refused the key (401)."},
            go_ahead=True,
        )
        [blocker] = release_blockers(facts)
        assert blocker.code == "G5"
        assert blocker.message == (
            "the render connection is not working: Render refused the key (401). "
            "Check it again in Settings"
        )

    def test_with_all_of_them_the_cloud_is_not_blocked(self) -> None:
        facts = _facts(
            target="cloud",
            cloud_enabled=True,
            connected=frozenset({"github", "vercel", "render"}),
            go_ahead=True,
        )
        assert release_blockers(facts) == []


class TestWhichConnectionsWork:
    def test_a_check_that_passed_counts_with_or_without_limits(self) -> None:
        working, failing = cloud_connections(
            {
                "github": {"probe": {"verdict": "SUITABLE", "reason": "Authenticates as dev."}},
                "vercel": {"probe": {"verdict": "WORKABLE", "reason": "Limited token."}},
            }
        )
        assert working == frozenset({"github", "vercel"})
        assert failing == {}

    def test_a_check_that_failed_does_not_and_says_why(self) -> None:
        working, failing = cloud_connections(
            {"render": {"probe": {"verdict": "UNUSABLE", "reason": "Render refused the key."}}}
        )
        assert working == frozenset()
        assert failing == {"render": "Render refused the key."}

    def test_a_connection_nothing_checked_is_not_known_to_work(self) -> None:
        working, failing = cloud_connections({"github": {"provider": "github", "probe": None}})
        assert working == frozenset()
        assert failing == {"github": "it has not been checked"}

    def test_a_provider_a_release_does_not_use_is_not_counted(self) -> None:
        working, failing = cloud_connections(
            {"atlas": {"probe": {"verdict": "UNUSABLE", "reason": "No cluster."}}}
        )
        assert (working, failing) == (frozenset(), {})


class TestG6:
    """The plan is made for the target chosen when the analysis runs, and its steps
    name the adapters that carry the release out, so a target switched at the review
    recorded a cloud release that the local plan's containers carried out."""

    def test_a_target_chosen_after_the_plan_is_refused_and_says_what_to_do(self) -> None:
        facts = _facts(
            target="cloud",
            plan_target="local",
            cloud_enabled=True,
            connected=frozenset({"github", "vercel", "render"}),
            go_ahead=True,
        )
        [blocker] = release_blockers(facts)
        assert blocker.code == "G6"
        assert blocker.message == (
            "this version was planned for the local target, not the cloud target chosen now: "
            "request changes, and the next version is planned for cloud"
        )

    def test_the_planned_target_is_not_blocked(self) -> None:
        assert release_blockers(_facts(plan_target="local")) == []


def _pipeline(*checks: FileValidation, supported: bool = True) -> PipelineConfig:
    """The deploy layer, each file checked by the validators given (all passing by default)."""
    passed = FileValidation(validator="json-schema", tool="schema", outcome="passed")
    return PipelineConfig(
        version=1,
        generated_at=NOW,
        code_version=1,
        candidate_hash=CANDIDATE,
        stack=StackSupport(
            stack_id="mern",
            supported=True,
            layout=ArchitecturalLayout(
                kind="one-process", serves_frontend_from_backend=True, evidence=["test"]
            ),
        )
        if supported
        else StackSupport(stack_id="react-spring-postgres", supported=False, reason="no template"),
        files=[
            PipelineFile(
                path=path,
                purpose="workflow" if path.startswith(".github") else "container",
                sha256="a" * 64,
                bytes=1,
                template_id=f"mern/{path}@1",
                validations=[checks[0] if checks and path == "Dockerfile" else passed],
            )
            for path in (".github/workflows/deploy.yml", "Dockerfile")
        ]
        if supported
        else [],
        kubernetes="skipped",
        kubernetes_reason="not asked",
    )


class TestG7:
    """`PipelineConfig.valid` was read by no guard, so a release could ship a pipeline
    a validator failed, or one nothing validated (review item C4-8)."""

    def test_a_valid_pipeline_says_nothing(self) -> None:
        assert release_blockers(_facts(pipeline=_pipeline())) == []

    def test_a_file_a_validator_failed_is_refused_and_named(self) -> None:
        failed = FileValidation(
            validator="hadolint",
            tool="hadolint 2.12",
            outcome="failed",
            findings=["DL3008 pin versions in apt-get install"],
        )
        [blocker] = release_blockers(_facts(pipeline=_pipeline(failed)))
        assert blocker.code == "G7"
        assert blocker.message == (
            "the generated pipeline did not validate: Dockerfile, hadolint failed "
            "(DL3008 pin versions in apt-get install)"
        )

    def test_a_validator_that_did_not_run_says_why(self) -> None:
        missing = FileValidation(
            validator="hadolint", outcome="not-run", reason="Docker is not running"
        )
        [blocker] = release_blockers(_facts(pipeline=_pipeline(missing)))
        assert blocker.code == "G7"
        assert "Dockerfile, hadolint did not run (Docker is not running)" in blocker.message

    def test_an_unsupported_stack_has_nothing_to_release(self) -> None:
        [blocker] = release_blockers(_facts(pipeline=_pipeline(supported=False)))
        assert blocker.code == "G7"
        assert "no pipeline was generated: no template" in blocker.message


def _finding(finding_id: str, *, privileges: str = "L", impact: str = "H") -> SecurityFinding:
    """A finding in the code the release ships: 8.1, High, as given; Critical with no
    privileges needed; Medium with low impact."""
    return SecurityFinding(
        id=finding_id,
        cwe="CWE-89",
        title="SQL injection in the orders search",
        origin="scanner",
        raised_by=["scanner"],
        evidence=EvidenceSpan(path="apps/api/src/routes/orders.ts", start_line=36, end_line=38),
        factors=CvssFactors(
            attack_vector="N",
            attack_complexity="L",
            privileges_required=privileges,
            user_interaction="N",
            scope="U",
            confidentiality=impact,
            integrity=impact,
            availability="N",
        ),
        confidence=0.8,
        confidence_source="scanner-rule",
    )


class TestG8:
    """An open Critical or High finding in the code a release ships never reached
    the release gate: no guard read the findings, and the test approval only
    counted them (review item C3-8)."""

    def test_an_open_high_finding_is_refused_and_named(self) -> None:
        high = _finding("f-high")
        assert high.severity == "high"
        [blocker] = release_blockers(_facts(findings=[high]))
        assert blocker.code == "G8"
        assert blocker.message == (
            "CWE-89 SQL injection in the orders search, High (8.1), at "
            "apps/api/src/routes/orders.ts:36 is open in the code this release ships: fix it "
            "and test again, dismiss it with a note saying why it does not apply, or accept "
            "the risk with a note saying why it can ship"
        )

    def test_a_critical_one_too_and_a_medium_one_is_not_this_guards(self) -> None:
        critical, medium = _finding("f-c", privileges="N"), _finding("f-m", impact="L")
        assert (critical.severity, medium.severity) == ("critical", "medium")
        assert [b.code for b in release_blockers(_facts(findings=[critical, medium]))] == ["G8"]

    def test_a_dismissal_or_a_risk_accepted_with_a_note_lets_it_ship(self) -> None:
        high = _finding("f-high")
        for decision in (
            {"decision": "dismissed", "note": "the search is not exposed"},
            {"decision": "accepted", "note": "behind the admin login until sprint 2"},
        ):
            assert (
                release_blockers(_facts(findings=[high], finding_decisions={"f-high": decision}))
                == []
            )

    def test_accepting_it_with_no_note_says_why_it_can_ship_is_missing(self) -> None:
        facts = _facts(
            findings=[_finding("f-high")],
            finding_decisions={"f-high": {"decision": "accepted", "note": ""}},
        )
        [blocker] = release_blockers(facts)
        assert blocker.code == "G8"
        assert "was accepted with no note saying why it can ship" in blocker.message


@needs_db
class TestAtTheGate:
    async def test_the_snapshot_says_what_blocks_and_the_approval_is_refused_for_it(
        self,
        client,  # noqa: F811 - the fixture
    ) -> None:
        project_id = await _approved_tests(client)
        await _deploy_run(client, project_id)
        snapshot = DeploySnapshot.model_validate(
            (await client.get(f"/projects/{project_id}/deployment")).json()
        )
        assert [(b.code, b.update_id) for b in snapshot.blocking] == [("G1", ZOD)]

        refused = await client.post(
            f"/projects/{project_id}/deployment/decision", json={"kind": "approved", "by": "you"}
        )
        assert refused.status_code == 409
        assert refused.json()["detail"] == [
            {"code": "G1", "message": snapshot.blocking[0].message, "updateId": ZOD}
        ]

        await _decide_every_update(client, project_id)
        cleared = DeploySnapshot.model_validate(
            (await client.get(f"/projects/{project_id}/deployment")).json()
        )
        assert cleared.blocking == []
        approved = await client.post(
            f"/projects/{project_id}/deployment/decision", json={"kind": "approved", "by": "you"}
        )
        assert approved.status_code == 200, approved.text

    async def test_a_pipeline_that_did_not_validate_is_refused_at_the_gate(
        self,
        client,  # noqa: F811 - the fixture
    ) -> None:
        client.app.state.c4.invalid_pipeline = True
        try:
            project_id = await _approved_tests(client)
            await _deploy_run(client, project_id)
            await _decide_every_update(client, project_id)
        finally:
            client.app.state.c4.invalid_pipeline = False

        snapshot = DeploySnapshot.model_validate(
            (await client.get(f"/projects/{project_id}/deployment")).json()
        )
        assert {b.code for b in snapshot.blocking} == {"G7"}
        refused = await client.post(
            f"/projects/{project_id}/deployment/decision", json={"kind": "approved", "by": "you"}
        )
        assert refused.status_code == 409
        assert "the generated pipeline did not validate" in refused.text

    async def test_an_open_high_finding_is_refused_until_a_person_decides_it(
        self,
        client,  # noqa: F811 - the fixture
    ) -> None:
        client.app.state.c3.findings = [_finding("f-high")]
        try:
            project_id = await _approved_tests(client)
        finally:
            client.app.state.c3.findings = []
        await _deploy_run(client, project_id)
        await _decide_every_update(client, project_id)

        snapshot = DeploySnapshot.model_validate(
            (await client.get(f"/projects/{project_id}/deployment")).json()
        )
        assert [b.code for b in snapshot.blocking] == ["G8"]
        refused = await client.post(
            f"/projects/{project_id}/deployment/decision", json={"kind": "approved", "by": "you"}
        )
        assert refused.status_code == 409
        assert "SQL injection in the orders search" in refused.text

        accepted = await client.post(
            f"/projects/{project_id}/testing/findings/f-high/decision",
            json={"decision": "accepted", "note": "behind the admin login until sprint 2"},
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["findingDecisions"][0]["note"] == (
            "behind the admin login until sprint 2"
        )
        cleared = DeploySnapshot.model_validate(
            (await client.get(f"/projects/{project_id}/deployment")).json()
        )
        assert cleared.blocking == []
        approved = await client.post(
            f"/projects/{project_id}/deployment/decision", json={"kind": "approved", "by": "you"}
        )
        assert approved.status_code == 200, approved.text

    async def test_a_cloud_release_shows_it_needs_the_go_ahead(self, client) -> None:  # noqa: F811 - the fixture
        project_id = await _approved_tests(client)
        await client.post(
            f"/projects/{project_id}/deployment/target", json={"target": "cloud", "by": "you"}
        )
        await _deploy_run(client, project_id)
        await _decide_every_update(client, project_id)
        snapshot = DeploySnapshot.model_validate(
            (await client.get(f"/projects/{project_id}/deployment")).json()
        )
        assert {b.code for b in snapshot.blocking} == {"G5"}
        assert any("go ahead" in b.message for b in snapshot.blocking)

    async def test_a_target_switched_at_the_review_is_refused_until_it_is_planned(
        self,
        client,  # noqa: F811 - the fixture
    ) -> None:
        project_id = await _approved_tests(client)
        await _deploy_run(client, project_id)
        await _decide_every_update(client, project_id)
        await client.post(
            f"/projects/{project_id}/deployment/target", json={"target": "cloud", "by": "you"}
        )

        snapshot = DeploySnapshot.model_validate(
            (await client.get(f"/projects/{project_id}/deployment")).json()
        )
        assert "G6" in {b.code for b in snapshot.blocking}
        refused = await client.post(
            f"/projects/{project_id}/deployment/decision",
            json={"kind": "approved", "by": "you", "goAhead": True},
        )
        assert refused.status_code == 409
        assert "G6" in {item["code"] for item in refused.json()["detail"]}

        await client.post(
            f"/projects/{project_id}/deployment/target", json={"target": "local", "by": "you"}
        )
        back = DeploySnapshot.model_validate(
            (await client.get(f"/projects/{project_id}/deployment")).json()
        )
        assert back.blocking == []
