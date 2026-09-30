"""The rollback plan: somewhere verified to return to, on the same target, or a reason why not.

A plan is written before every release and executed only on a person's
approval. What is checked here is what the release guards and the rollback
guard rely on: a first release cannot be restored and its High updates are
refused; a restorable plan names the verified release and checks its
fingerprint; and a plan never offers to restore the candidate it rolls back
from, or a release from the other target.
"""

from datetime import UTC, datetime

import pytest
from c4.risk import assess
from c4.rollback.plan import DATA_NOTE, DATABASE_NOTE, plan
from c4.service import C4
from pydantic import ValidationError
from sdlc_contracts import (
    BuildStepReport,
    ReleaseCandidate,
    RiskReport,
    RollbackPlan,
    UpdateRollback,
    VerifiedRelease,
)

from .test_assessment import _changelog, _update, _updates

NOW = datetime(2026, 9, 28, tzinfo=UTC)
HIGH = _update("acme", old="1.0.0", new="2.0.0", change="major")
LOW = _update("beta")


def _candidate(*included: str, digest: str = "a" * 64) -> ReleaseCandidate:
    return ReleaseCandidate(
        version=3,
        generated_at=NOW,
        code_version=2,
        candidate_hash=digest,
        included=list(included),
        toolchain="scripted",
        isolation="scripted",
        steps=[BuildStepReport(name="image", command="docker build .", outcome="passed")],
    )


def _previous(target: str = "local", digest: str = "b" * 64, **kw) -> VerifiedRelease:
    return VerifiedRelease(
        deployment_id="d-1",
        deploy_version=2,
        candidate_hash=digest,
        target=target,
        image_digest=kw.get("image", "sha256:" + "c" * 64),
        commit_sha=kw.get("commit"),
        verified_at=NOW,
    )


RISK: RiskReport = assess.report(
    _updates(HIGH, LOW), _changelog((HIGH, "removal", "high"), (LOW, "fix", "low")), None, version=3
)


class TestAFirstRelease:
    def test_there_is_nothing_to_return_to_and_a_high_update_is_refused(self) -> None:
        prepared = plan(_candidate(HIGH.id, LOW.id), RISK, None, release_target="local", version=3)
        assert not prepared.restorable and prepared.restore_target is None
        assert "no verified release yet" in prepared.unrestorable_reason
        statuses = {item.update_id: item.status for item in prepared.updates}
        assert statuses == {HIGH.id: "unavailable", LOW.id: "not-required"}
        assert prepared.blocks == [HIGH.id]


class TestARestorablePlan:
    def test_locally_the_verified_image_is_started_and_its_fingerprint_checked(self) -> None:
        previous = _previous()
        prepared = plan(_candidate(HIGH.id), RISK, previous, release_target="local", version=3)
        assert prepared.restorable and prepared.restore_target == previous
        assert [step.id for step in prepared.steps] == ["start-verified", "switch-back"]
        assert [step.id for step in prepared.steps if step.moves_traffic] == ["switch-back"]
        [fingerprint] = [check for check in prepared.checks if check.kind == "fingerprint"]
        assert fingerprint.expect.endswith("b" * 64)
        assert prepared.updates[0].status == "prepared" and prepared.blocks == []
        assert prepared.approval == "required"

    def test_in_the_cloud_the_verified_commit_is_redeployed_not_the_providers_button(
        self,
    ) -> None:
        previous = _previous("cloud", commit="f" * 40)
        prepared = plan(_candidate(HIGH.id), RISK, previous, release_target="cloud", version=3)
        backend, frontend = prepared.steps
        assert backend.provider == "render" and "f" * 40 in backend.action and backend.moves_traffic
        assert frontend.provider == "github" and "f" * 40 in frontend.action
        assert frontend.moves_traffic
        assert {check.role for check in prepared.checks} == {"backend", "frontend"}
        assert any("Vercel Hobby" in note for note in prepared.provider_constraints)


class TestNowhereToGo:
    @pytest.mark.parametrize(
        ("previous", "target", "reason"),
        [
            (_previous("local"), "cloud", "ran on the local target"),
            (_previous(digest="a" * 64), "local", "the candidate is the verified release itself"),
            (_previous("cloud"), "cloud", "recorded no commit to redeploy"),
            (_previous(image=None), "local", "recorded no image digest"),
        ],
    )
    def test_each_reason_is_said_and_a_high_update_is_refused(self, previous, target, reason):
        prepared = plan(_candidate(HIGH.id), RISK, previous, release_target=target, version=3)
        assert not prepared.restorable and reason in prepared.unrestorable_reason
        assert prepared.blocks == [HIGH.id]

    def test_the_contract_refuses_a_prepared_rollback_with_nowhere_to_go(self) -> None:
        with pytest.raises(ValidationError, match="no update can have a prepared rollback"):
            RollbackPlan(
                version=1,
                generated_at=NOW,
                candidate_hash="a" * 64,
                restorable=False,
                unrestorable_reason="nothing to return to",
                updates=[UpdateRollback(update_id=HIGH.id, level="high", status="prepared")],
            )


class TestWhatARestoreDoesToTheRecords:
    """A restore leaves a database alone and empties memory, and the plan says which."""

    def _with_database(self, candidate: ReleaseCandidate) -> ReleaseCandidate:
        steps = [
            *candidate.steps,
            BuildStepReport(name="database", command="docker run mongo", outcome="passed"),
        ]
        return candidate.model_copy(update={"steps": steps})

    def test_a_release_that_keeps_a_database_says_a_restore_leaves_it(self) -> None:
        prepared = plan(
            self._with_database(_candidate()),
            RISK,
            _previous("cloud", commit="1" * 40),
            release_target="cloud",
            version=3,
            database=True,
            now=NOW,
        )
        assert prepared.data_note == DATABASE_NOTE

    def test_it_does_not_promise_the_restored_release_can_read_them(self) -> None:
        """The note said a restored release finds the records "as this one left
        them", and nothing checks that: it is older code reading what newer code
        wrote (review item C4-12)."""
        assert "as this one left them" not in DATABASE_NOTE
        assert "Nothing checks that the restored release can read them" in DATABASE_NOTE
        assert "which a restore does not touch" in DATABASE_NOTE

    def test_code_that_keeps_memory_is_told_so_even_where_a_database_waits(self) -> None:
        prepared = plan(
            _candidate(),
            RISK,
            _previous("cloud", commit="1" * 40),
            release_target="cloud",
            version=3,
            database=True,
            now=NOW,
        )
        assert prepared.data_note == DATA_NOTE

    def test_without_a_database_where_it_releases_a_restore_starts_empty(self) -> None:
        prepared = plan(
            self._with_database(_candidate()), RISK, _previous(), release_target="local", version=3
        )
        assert prepared.data_note == DATA_NOTE


class TestTheStage:
    async def test_the_component_answers_with_the_plan_and_what_it_blocks(self) -> None:
        answer = await C4("deepseek:deepseek-flash").plan_rollback(
            _candidate(HIGH.id), RISK, None, release_target="local", version=3
        )
        assert isinstance(answer.artefact, RollbackPlan)
        assert answer.notes == {"restorable": False, "blocks": [HIGH.id]}
        assert answer.summary.startswith("not restorable: this project has no verified release")
