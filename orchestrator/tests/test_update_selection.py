"""Which updates a candidate carries: a High update only with somewhere to roll back to.

A High update's prepared rollback (FR17) restores a verified release on the target the
release goes to; a release on another target is nowhere a rollback can go, and the
rollback plan says so. The selection used to ask only whether any verified release
existed, so a project released on this machine had its first cloud candidate built
with its High updates in it, and G2 then refused the release it had just built.
"""

from datetime import UTC, datetime

from orchestrator.clients.canned_c4 import CannedC4
from orchestrator.graph.deployment_nodes import _selection
from sdlc_contracts import RiskReport, VerifiedRelease

NOW = datetime(2026, 9, 29, tzinfo=UTC)


async def _risk() -> RiskReport:
    """The canned assessment: vite Low, zod Medium, express High."""
    c4 = CannedC4()
    detected = await c4.detect_updates(
        {}, target="generated", version=1, code_version=1, test_version=1
    )
    return (await c4.assess_risk(detected.report, None, None, version=1)).artefact


def _verified(target: str) -> VerifiedRelease:
    return VerifiedRelease(
        deployment_id="d-1",
        deploy_version=1,
        candidate_hash="a" * 64,
        target=target,
        image_digest="sha256:" + "d" * 64 if target == "local" else None,
        commit_sha="3" * 40 if target == "cloud" else None,
        verified_at=NOW,
    )


def _high(risk: RiskReport) -> str:
    return next(a.update_id for a in risk.assessments if a.arbitration.final == "high")


class TestWhichUpdatesACandidateCarries:
    async def test_a_high_update_goes_in_with_a_verified_release_on_its_target(self) -> None:
        risk = await _risk()
        included, excluded = _selection(risk, _verified("cloud"), "cloud")
        assert excluded == [] and _high(risk) in included

    async def test_a_release_on_another_target_is_nowhere_to_roll_back_to(self) -> None:
        risk = await _risk()
        included, excluded = _selection(risk, _verified("local"), "cloud")
        [left_out] = excluded
        assert left_out["updateId"] == _high(risk) and left_out["reason"] == "no-restore-target"
        assert "cloud" in left_out["detail"] and "local" in left_out["detail"]
        assert len(included) == 2, "the Low and the Medium still go in"

    async def test_a_first_release_carries_no_high_update(self) -> None:
        risk = await _risk()
        included, excluded = _selection(risk, None, "local")
        assert [one["updateId"] for one in excluded] == [_high(risk)]
        assert "has none yet" in excluded[0]["detail"] and len(included) == 2


def _id(risk: RiskReport, package: str) -> str:
    return next(a.update_id for a in risk.assessments if a.package == package)


class TestWhatAPersonLeftOut:
    """A rebuild G3 asks for leaves out what a person left out, while that decision counts."""

    async def test_a_rejected_update_stays_out_with_its_note(self) -> None:
        risk = await _risk()
        zod = _id(risk, "zod")
        decisions = {zod: {"decision": "rejected", "note": "not yet", "levelAtDecision": "medium"}}
        included, excluded = _selection(risk, None, "local", decisions)
        assert zod not in included
        assert {"updateId": zod, "reason": "rejected", "detail": "not yet"} in excluded

    async def test_a_deferred_update_stays_out_too(self) -> None:
        risk = await _risk()
        zod = _id(risk, "zod")
        decisions = {zod: {"decision": "deferred", "note": "", "levelAtDecision": "medium"}}
        _, excluded = _selection(risk, None, "local", decisions)
        assert {"updateId": zod, "reason": "deferred", "detail": "deferred at a review"} in excluded

    async def test_a_decision_taken_at_a_lower_level_no_longer_counts(self) -> None:
        # Left out as Low, and Medium now: the person decides again, as G1 and G3 say.
        risk = await _risk()
        zod = _id(risk, "zod")
        decisions = {zod: {"decision": "rejected", "note": "later", "levelAtDecision": "low"}}
        included, _ = _selection(risk, None, "local", decisions)
        assert zod in included

    async def test_an_approved_update_goes_in(self) -> None:
        risk = await _risk()
        zod = _id(risk, "zod")
        decisions = {zod: {"decision": "approved", "note": "", "levelAtDecision": "medium"}}
        included, _ = _selection(risk, None, "local", decisions)
        assert zod in included
