"""The assessment: three votes, the most cautious one, and a sentence when they disagree.

The reports it reads are produced by the real stages over small projects written
here, with the API diff answered from the recorded Roseau excerpt, so the shape
of the worked case (a patch by number that the code's own use of the changes
makes High) is checked end to end without a network. The report's validators
re-derive every level, so an assessment that reaches the wrong one is not
returned, it is refused.
"""

import json
from datetime import UTC, datetime
from itertools import count
from pathlib import Path

import httpx
import pytest
from c4.impact import stage
from c4.impact.api_diff import ApiDiff, roseau_symbols
from c4.intake.fetch import Fetcher
from c4.risk import assess as assessment
from c4.service import C4
from pydantic import ValidationError
from sdlc_contracts import (
    ChangedSymbol,
    ChangelogReport,
    DependencyUpdate,
    DependencyUpdates,
    ImpactReport,
    RiskReport,
    update_id_for,
    update_key,
)

ROSEAU = Path(__file__).parent / "fixtures" / "roseau" / "dubbo-2.7.3-2.7.21.excerpt.json"


def _update(package, ecosystem="npm", old="1.0.0", new="1.0.1", change="patch"):
    key = update_key(ecosystem, package, old, new)
    return DependencyUpdate(
        id=update_id_for(key),
        key=key,
        ecosystem=ecosystem,
        package=package,
        manifest_path="pom.xml" if ecosystem == "maven" else "package.json",
        scope="compile" if ecosystem == "maven" else "prod",
        declared=old,
        from_version=old,
        to_version=new,
        candidate="latest",
        change=change,
    )


DUBBO = _update("org.apache.dubbo:dubbo", "maven", "2.7.3", "2.7.21", "patch")

HANDLER = {
    "pom.xml": "<project><artifactId>agent</artifactId></project>",
    "src/main/java/com/x/Handler.java": (
        "package com.x;\n"
        "import com.alibaba.dubbo.rpc.RpcContext;\n"
        "class Handler {\n"
        "    Object serve() { return RpcContext.getContext().getServerContext(); }\n"
        "}\n"
    ),
}


def _updates(*updates) -> DependencyUpdates:
    return DependencyUpdates(
        version=1,
        generated_at=datetime(2026, 9, 27, tzinfo=UTC),
        code_version=1,
        test_version=1,
        target="generated",
        updates=list(updates),
    )


def _changelog(*pairs: tuple[DependencyUpdate, str, str]) -> ChangelogReport:
    """One verified claim per update: (update, claim kind, the vote the rule gives it)."""
    return ChangelogReport.model_validate(
        {
            "version": 1,
            "generatedAt": "2026-09-27T00:00:00Z",
            "modelId": "deepseek:deepseek-flash",
            "promptId": "changelog-extract/1",
            "promptSha256": "0" * 64,
            "perUpdate": [
                {
                    "updateId": update.id,
                    "notesFound": True,
                    "claims": [
                        {
                            "id": f"{update.id}-c1",
                            "kind": kind,
                            "symbols": [],
                            "quote": f"A {kind} in this release.",
                            "sourceUrl": "https://example/releases",
                            "version": update.to_version,
                        }
                    ],
                    "vote": {
                        "signal": "changelog",
                        "level": level,
                        "ruleId": "changelog-rule/1",
                        "rationale": "written by code",
                        "evidenceIds": [f"{update.id}-c1"],
                    },
                    "model": {
                        "modelId": "deepseek:deepseek-flash",
                        "promptId": "changelog-extract/1",
                        "promptSha256": "0" * 64,
                        "outcome": "answered",
                        "durationSeconds": 2.5,
                    },
                }
                for update, kind, level in pairs
            ],
        }
    )


async def _impact(files, updates, changelog=None, *, symbols=()) -> ImpactReport:
    async def answered(update, *, fetcher, launcher=None, cache_dir=None):
        return ApiDiff("ran", "recorded", tuple(s for s in symbols if s.update_id == update.id))

    original = stage.diff
    stage.diff = answered  # type: ignore[assignment]
    try:
        async with httpx.AsyncClient() as client:
            return await stage.analyse(
                files,
                updates,
                changelog,
                graph=None,
                contract=None,
                manifest=[],
                version=1,
                code_version=1,
                design_version=None,
                fetcher=Fetcher(client),
            )
    finally:
        stage.diff = original  # type: ignore[assignment]


class TestTheWorkedCaseShape:
    async def test_a_patch_the_code_uses_is_high_with_an_advisory_and_a_rollback(self) -> None:
        symbols = roseau_symbols(json.loads(ROSEAU.read_text()), update_id=DUBBO.id)
        impact = await _impact(HANDLER, _updates(DUBBO), symbols=symbols)
        [assessed] = assessment.report(_updates(DUBBO), None, impact, version=1).assessments
        levels = [(vote.signal, vote.level) for vote in assessed.votes]
        assert levels == [("semver", "low"), ("changelog", None), ("usage", "high")]
        assert (assessed.arbitration.final, assessed.arbitration.decided_by) == ("high", ["usage"])
        assert assessed.arbitration.advisory.startswith(
            "The signals disagree: SemVer says Low, the changelog says no vote, usage says High."
        )
        assert (assessed.strategy.deploy, assessed.strategy.rollback_required) == (
            "approval-with-rollback",
            True,
        )
        assert assessed.affected_files == ["src/main/java/com/x/Handler.java"]
        assert assessed.affected_components == ["module:."]
        kinds = {item.kind for item in assessed.evidence}
        assert kinds == {"version", "reference", "api-diff", "component"}
        cited = assessed.votes[2].evidence_ids[0]
        [reference] = [item for item in assessed.evidence if item.id == cited]
        assert "RpcContext#getServerContext" in reference.summary and ":4:" in reference.summary


class TestTheRule:
    async def test_votes_that_agree_need_no_advisory_and_ship_automatically(self) -> None:
        update = _update("acme")
        changelog = _changelog((update, "fix", "low"))
        files = {"src/a.ts": 'import { thing } from "acme";\nthing();\n'}
        impact = await _impact(files, _updates(update), changelog)
        [assessed] = assessment.report(_updates(update), changelog, impact, version=1).assessments
        assert [vote.level for vote in assessed.votes] == ["low", "low", None]
        assert assessed.arbitration.final == "low" and assessed.strategy.deploy == "automatic"

    def test_with_no_vote_at_all_the_update_is_high_and_says_why(self) -> None:
        update = _update("acme", old="r2024", new="r2025", change="non-semver")
        [assessed] = assessment.report(_updates(update), None, None, version=1).assessments
        assert (assessed.arbitration.final, assessed.arbitration.decided_by) == ("high", [])
        assert assessed.arbitration.advisory.startswith("No signal could vote")
        assert assessed.strategy.manual_review_required

    def test_the_same_votes_give_the_same_outcome_in_either_ecosystem(self) -> None:
        """NFR12: nothing in the arbitration reads the ecosystem."""
        npm = _update("acme", "npm", "1.0.0", "1.0.1")
        maven = _update("org.acme:acme", "maven", "1.0.0", "1.0.1")
        changelog = _changelog((npm, "removal", "high"), (maven, "removal", "high"))
        first, second = assessment.report(
            _updates(npm, maven), changelog, None, version=1
        ).assessments
        for part in ("arbitration", "strategy"):
            assert getattr(first, part) == getattr(second, part)

    async def test_low_low_high_is_high_and_a_majority_would_be_refused(self, monkeypatch) -> None:
        """SemVer and the changelog say Low, and the code uses a removed export.
        The most cautious vote is High; a majority would say Low, and because the
        report re-derives the level, a majority cannot even be recorded."""
        update = _update("acme")
        changelog = _changelog((update, "fix", "low"))
        removed = ChangedSymbol(
            update_id=update.id, symbol="thing", kind="removed", source="api-diff", tool="test"
        )
        files = {"src/a.ts": 'import { thing } from "acme";\nthing();\n'}
        impact = await _impact(files, _updates(update), changelog, symbols=[removed])
        [assessed] = assessment.report(_updates(update), changelog, impact, version=1).assessments
        assert [vote.level for vote in assessed.votes] == ["low", "low", "high"]
        assert assessed.arbitration.final == "high"

        def majority(votes):
            cast = [level for level in votes.values() if level]
            winner = max(set(cast), key=cast.count)
            return winner, tuple(signal for signal, level in votes.items() if level == winner)

        monkeypatch.setattr(assessment, "safety_first", majority)
        with pytest.raises(ValidationError, match="the rule over these votes says high"):
            assessment.report(_updates(update), changelog, impact, version=1)


class TestTheRecord:
    def test_each_step_is_timed_on_its_own_clock(self) -> None:
        update = _update("acme")
        ticks = count(start=10.0, step=0.25)
        [assessed] = assessment.report(
            _updates(update),
            _changelog((update, "fix", "low")),
            None,
            version=1,
            clock=lambda: next(ticks),
        ).assessments
        assert assessed.latency.changelog_seconds == 2.5
        assert assessed.latency.arbitration_seconds == 0.25
        assert assessed.latency.assessment_seconds == 2.75

    async def test_the_component_answers_through_its_stage(self) -> None:
        update = _update("acme")
        answer = await C4("deepseek:deepseek-flash").assess_risk(
            _updates(update), _changelog((update, "removal", "high")), None, version=4
        )
        risk = answer.artefact
        assert isinstance(risk, RiskReport) and risk.version == 4
        assert answer.summary == (
            "1 update assessed: 1 High, 0 Medium, 0 Low; 1 where the signals disagree"
        )
