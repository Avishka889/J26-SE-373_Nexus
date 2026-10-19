"""The C4 analysis contracts, held to what they claim to enforce.

Each class is one promise the module docstrings make, and each test is a report
that breaks it being refused at the boundary. The load bearing one is the first:
a risk report cannot author its own final level, which is FR6 and FR7 as a
property of the type.
"""

from datetime import datetime

import pytest
from pydantic import ValidationError
from sdlc_contracts import (
    ChangelogAnalysis,
    ChangelogClaim,
    DependencyUpdate,
    ImpactReport,
    ModelCall,
    RiskReport,
    SignalVote,
    UpdateAssessment,
    UpdateImpact,
    update_id_for,
    update_key,
)

WHEN = datetime(2026, 9, 27, 12, 0)
SHA = "a" * 64
KEY = update_key("npm", "express", "4.21.2", "5.1.0")
UID = update_id_for(KEY)


def _vote(signal: str, level: str | None, *, evidence: list[str] | None = None) -> dict:
    rule = {"semver": "semver-rule/1", "changelog": "changelog-rule/1", "usage": "usage-rule/1"}
    body: dict = {
        "signal": signal,
        "level": level,
        "ruleId": rule[signal],
        "rationale": f"{signal} said {level}",
        "evidenceIds": evidence or [],
    }
    if level is None:
        body["abstainedReason"] = "nothing to go on"
    return body


def _assessment(
    *,
    change: str = "patch",
    votes: tuple[str | None, str | None, str | None] = ("low", "low", "high"),
    final: str = "high",
    decided_by: list[str] | None = None,
    advisory: str = "The signals disagree; the most cautious level was taken. Confirm it.",
    deploy: str = "approval-with-rollback",
    review: bool = True,
) -> dict:
    semver, changelog, usage = votes
    return {
        "updateId": UID,
        "key": KEY,
        "package": "express",
        "ecosystem": "npm",
        "fromVersion": "4.21.2",
        "toVersion": "5.1.0",
        "change": change,
        "votes": [
            _vote("semver", semver, evidence=["version"]),
            _vote("changelog", changelog, evidence=["version"]),
            _vote("usage", usage, evidence=["version"]),
        ],
        "arbitration": {
            "final": final,
            "decidedBy": decided_by if decided_by is not None else ["usage"],
            "advisory": advisory,
        },
        "strategy": {"deploy": deploy, "manualReviewRequired": review, "rollbackRequired": review},
        "evidence": [{"id": "version", "kind": "version", "summary": "4.21.2 to 5.1.0"}],
        "latency": {"changelogSeconds": 2.0, "usageSeconds": 1.0, "arbitrationSeconds": 0.0},
    }


class TestTheFinalLevelIsTheRules:
    def test_a_report_the_rule_agrees_with_is_accepted(self) -> None:
        assessment = UpdateAssessment.model_validate(_assessment())
        assert assessment.arbitration.final == "high"
        assert assessment.disagreement

    def test_a_report_cannot_author_its_own_final_level(self) -> None:
        """Two calm votes and one cautious one, and a producer that would like
        the answer to be medium. The rule says high, so the report is refused."""
        with pytest.raises(ValidationError, match="the rule over these votes says high"):
            UpdateAssessment.model_validate(
                _assessment(final="medium", deploy="approval", review=False)
            )

    def test_the_deciding_signals_are_the_rules_too(self) -> None:
        with pytest.raises(ValidationError, match="decided by"):
            UpdateAssessment.model_validate(_assessment(decided_by=["semver"]))

    def test_the_semver_vote_is_re_derived_from_the_change(self) -> None:
        """A patch the SemVer vote calls high is a vote the rule never cast."""
        with pytest.raises(ValidationError, match="the SemVer vote says high for a patch"):
            UpdateAssessment.model_validate(
                _assessment(votes=("high", "low", "high"), decided_by=["semver", "usage"])
            )

    def test_nothing_voted_is_high_decided_by_nobody(self) -> None:
        assessment = UpdateAssessment.model_validate(
            _assessment(change="non-semver", votes=(None, None, None), decided_by=[])
        )
        assert assessment.arbitration.final == "high"
        assert assessment.evidence_complete, "nothing was cast, so nothing lacks evidence"


class TestDisagreementIsSaidOutLoud:
    def test_disagreement_without_an_advisory_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="NFR10"):
            UpdateAssessment.model_validate(_assessment(advisory=""))

    def test_no_votes_without_an_advisory_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="NFR10"):
            UpdateAssessment.model_validate(
                _assessment(
                    change="non-semver", votes=(None, None, None), decided_by=[], advisory=""
                )
            )

    def test_agreement_needs_no_advisory(self) -> None:
        assessment = UpdateAssessment.model_validate(
            _assessment(
                votes=("low", "low", "low"),
                final="low",
                decided_by=["semver", "changelog", "usage"],
                advisory="",
                deploy="automatic",
                review=False,
            )
        )
        assert not assessment.disagreement


class TestTheStrategyFollowsTheLevel:
    def test_high_is_reviewed_with_a_prepared_rollback(self) -> None:
        with pytest.raises(ValidationError, match="manual review"):
            UpdateAssessment.model_validate(_assessment(review=False))

    def test_low_is_never_held_for_review(self) -> None:
        with pytest.raises(ValidationError, match="manual review"):
            UpdateAssessment.model_validate(
                _assessment(
                    votes=("low", "low", "low"),
                    final="low",
                    decided_by=["semver", "changelog", "usage"],
                    advisory="",
                    deploy="automatic",
                    review=True,
                )
            )


class TestEvidenceTravelsWithTheLevel:
    def test_a_vote_citing_evidence_the_assessment_lacks_is_refused(self) -> None:
        body = _assessment()
        body["votes"][2]["evidenceIds"] = ["ref:missing"]
        with pytest.raises(ValidationError, match="ref:missing"):
            UpdateAssessment.model_validate(body)

    def test_a_vote_needs_a_level_or_a_reason(self) -> None:
        with pytest.raises(ValidationError, match="abstained without saying why"):
            SignalVote.model_validate(
                {"signal": "usage", "level": None, "ruleId": "usage-rule/1", "rationale": "x"}
            )

    def test_a_vote_names_its_own_rule(self) -> None:
        with pytest.raises(ValidationError, match="names rule"):
            SignalVote.model_validate(
                {"signal": "usage", "level": "low", "ruleId": "semver-rule/1", "rationale": "x"}
            )


class TestTheReportRoundTrips:
    def test_a_stored_report_reads_back_with_its_counts_recomputed(self) -> None:
        report = RiskReport.model_validate(
            {"version": 1, "generatedAt": WHEN, "assessments": [_assessment()]}
        )
        stored = report.model_dump(by_alias=True, mode="json")
        assert stored["byLevel"] == {"low": 0, "medium": 0, "high": 1}
        stored["byLevel"] = {"low": 1, "medium": 0, "high": 0}  # an authored count is discarded
        again = RiskReport.model_validate(stored)
        assert again.by_level == {"low": 0, "medium": 0, "high": 1}
        assert again.disagreements == 1

    def test_an_update_is_assessed_once(self) -> None:
        with pytest.raises(ValidationError, match="more than once"):
            RiskReport.model_validate(
                {"version": 1, "generatedAt": WHEN, "assessments": [_assessment(), _assessment()]}
            )


def _model_call(outcome: str = "answered", stated: str | None = None) -> dict:
    return {
        "modelId": "deepseek:deepseek-flash",
        "promptId": "changelog-extract/1",
        "promptSha256": SHA,
        "outcome": outcome,
        "statedLevel": stated,
    }


def _analysis(*, claims: list[dict], refused: int = 0, level: str | None, model: dict | None):
    vote = _vote("changelog", level)
    return {
        "updateId": UID,
        "windows": ["5.0.0", "5.1.0"],
        "notesFound": True,
        "claims": claims,
        "refused": [{"reason": "quote-not-found", "quote": "invented"}] * refused,
        "vote": vote,
        "model": model,
    }


REMOVAL = {
    "id": "c1",
    "kind": "removal",
    "symbols": ["app.del"],
    "quote": "Removed app.del, use app.delete instead",
    "sourceUrl": "https://github.com/expressjs/express/releases/tag/v5.0.0",
    "version": "5.0.0",
}


class TestTheChangelogVoteIsTheRules:
    def test_a_verified_removal_is_high(self) -> None:
        analysis = ChangelogAnalysis.model_validate(
            _analysis(claims=[REMOVAL], level="high", model=_model_call())
        )
        assert analysis.vote.level == "high"

    def test_a_stated_level_cannot_move_the_vote(self) -> None:
        """The model says high; its only verified claim is a fix. The vote is
        the rule's, low, and a report claiming otherwise is refused."""
        fix = {**REMOVAL, "id": "c2", "kind": "fix", "symbols": [], "quote": "Fixed a crash"}
        with pytest.raises(ValidationError, match="the rule says low"):
            ChangelogAnalysis.model_validate(
                _analysis(claims=[fix], level="high", model=_model_call(stated="high"))
            )
        accepted = ChangelogAnalysis.model_validate(
            _analysis(claims=[fix], level="low", model=_model_call(stated="high"))
        )
        assert accepted.model is not None and accepted.model.stated_level == "high"

    def test_every_claim_refused_is_an_abstention_not_a_quiet_release(self) -> None:
        with pytest.raises(ValidationError, match="the rule says None"):
            ChangelogAnalysis.model_validate(
                _analysis(claims=[], refused=2, level="low", model=_model_call())
            )

    def test_a_model_that_did_not_answer_did_not_vote(self) -> None:
        with pytest.raises(ValidationError, match="the rule says None"):
            ChangelogAnalysis.model_validate(
                _analysis(claims=[], level="low", model=_model_call("rate-limited"))
            )

    def test_claims_cannot_come_from_a_model_that_did_not_answer(self) -> None:
        with pytest.raises(ValidationError, match="did not answer"):
            ChangelogAnalysis.model_validate(
                _analysis(claims=[REMOVAL], level=None, model=_model_call("provider-error"))
            )

    def test_a_claim_cannot_name_a_symbol_its_quote_lacks(self) -> None:
        with pytest.raises(ValidationError, match="does not contain"):
            ChangelogClaim.model_validate({**REMOVAL, "symbols": ["res.sendfile"]})

    def test_the_model_call_records_what_answered(self) -> None:
        call = ModelCall.model_validate(_model_call())
        assert call.model_id == "deepseek:deepseek-flash"


def _reference(path: str, kind: str = "removed") -> dict:
    return {
        "symbol": "app.del",
        "symbolKind": kind,
        "match": "member",
        "span": {"path": path, "startLine": 4, "endLine": 4, "snippet": "app.del('/x', h)"},
    }


def _impact(references: list[dict], unreferenced: list[str], level: str | None) -> dict:
    return {
        "updateId": UID,
        "importsPackage": True,
        "references": references,
        "unreferenced": unreferenced,
        "apiDiff": "ran",
        "vote": _vote("usage", level),
    }


class TestTheUsageVoteIsTheRules:
    def test_a_broken_symbol_in_use_is_high(self) -> None:
        impact = UpdateImpact.model_validate(_impact([_reference("a.ts")], [], "high"))
        assert impact.vote.level == "high"

    def test_nothing_changed_in_use_is_low(self) -> None:
        impact = UpdateImpact.model_validate(_impact([], ["app.del"], "low"))
        assert impact.vote.level == "low"

    def test_no_changed_symbols_known_is_an_abstention(self) -> None:
        with pytest.raises(ValidationError, match="the rule says None"):
            UpdateImpact.model_validate(_impact([], [], "low"))


def _impact_report(*, components: list[dict], unmapped: list[dict]) -> dict:
    return {
        "version": 1,
        "generatedAt": WHEN,
        "codeVersion": 1,
        "extraction": {
            "extractionId": "x1",
            "parser": "tree-sitter",
            "filesIndexed": 3,
            "seconds": 0.1,
        },
        "perUpdate": [_impact([_reference("a.ts"), _reference("b.ts")], [], "high")],
        "affectedFiles": [
            {"path": "a.ts", "updateIds": [UID], "referenceCount": 1},
            {"path": "b.ts", "updateIds": [UID], "referenceCount": 1},
        ],
        "affectedComponents": components,
        "unmappedFiles": unmapped,
    }


COMPONENT = {
    "nodeId": "e-order",
    "label": "Order",
    "kind": "entity",
    "updateIds": [UID],
    "files": ["a.ts"],
    "links": [{"via": "manifest-entity", "path": "a.ts", "detail": "implements Order"}],
    "traces": ["R-1"],
}


class TestNoAffectedFileIsLost:
    def test_every_file_is_mapped_or_listed(self) -> None:
        report = ImpactReport.model_validate(
            _impact_report(
                components=[COMPONENT],
                unmapped=[{"path": "b.ts", "reason": "not-in-manifest"}],
            )
        )
        assert report.refused_count == 0

    def test_a_file_neither_mapped_nor_listed_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="neither mapped nor listed"):
            ImpactReport.model_validate(_impact_report(components=[COMPONENT], unmapped=[]))

    def test_affected_files_are_exactly_the_referenced_ones(self) -> None:
        body = _impact_report(
            components=[COMPONENT], unmapped=[{"path": "b.ts", "reason": "not-in-manifest"}]
        )
        body["affectedFiles"].append({"path": "c.ts", "updateIds": [UID], "referenceCount": 1})
        with pytest.raises(ValidationError, match="extra"):
            ImpactReport.model_validate(body)


class TestAnUpdateIsWhatItsNameSays:
    def _update(self, **overrides) -> dict:
        body = {
            "id": UID,
            "key": KEY,
            "ecosystem": "npm",
            "package": "express",
            "manifestPath": "apps/api/package.json",
            "scope": "prod",
            "declared": "^4.21.2",
            "fromVersion": "4.21.2",
            "toVersion": "5.1.0",
            "candidate": "latest",
            "change": "major",
        }
        body.update(overrides)
        return body

    def test_a_consistent_update_is_accepted(self) -> None:
        assert DependencyUpdate.model_validate(self._update()).id == UID

    def test_an_id_that_is_not_the_hash_of_its_key_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="not the hash"):
            DependencyUpdate.model_validate(self._update(id="u-000000000000"))

    def test_a_key_naming_another_update_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="does not name this update"):
            DependencyUpdate.model_validate(self._update(toVersion="5.0.0"))

    def test_a_downgrade_is_not_an_update(self) -> None:
        with pytest.raises(ValidationError, match="not-an-upgrade"):
            DependencyUpdate.model_validate(self._update(change="downgrade"))


class TestTheExplanationIsOnTheRecord:
    def _explained(self, outcome: str, source: str) -> dict:
        return {
            **_assessment(),
            "explanation": "High, decided by usage.",
            "explanationSource": source,
            "explanationCall": {
                **_model_call(outcome),
                "promptId": "explain-assessment/2",
                "requests": 1,
                "promptTokens": 900,
                "completionTokens": 80,
            },
        }

    def test_a_models_prose_must_come_from_a_call_that_answered(self) -> None:
        with pytest.raises(ValidationError, match="the call it came from was rate-limited"):
            UpdateAssessment.model_validate(self._explained("rate-limited", "model"))

    def test_a_failed_call_still_records_its_cost_beside_the_rule_summary(self) -> None:
        assessment = UpdateAssessment.model_validate(self._explained("malformed", "rule"))
        assert assessment.explanation_call is not None
        assert assessment.explanation_call.completion_tokens == 80
