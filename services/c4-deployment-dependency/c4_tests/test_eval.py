"""The study's machinery, before any real case exists: rubric, split, scoring, tables.

Each piece is small enough to check against numbers worked out by hand, and
each is where a study goes quietly wrong: a rubric that labels a broken control
as a result, a split that moves as the corpus grows, a macro average that
rewards never predicting a class, a table that pools two epochs.
"""

import json
from datetime import date
from pathlib import Path

import pytest
from c4.eval.__main__ import main
from c4.eval.cases import CaseClient, CaseUpdate, LabelledCase, Observed, ObservedStep
from c4.eval.loaders.bump import case_from_record
from c4.eval.rubric import Excluded, level
from c4.eval.scoring import score
from c4.eval.split import held_out
from c4.eval.study import HeldOutRefused, VotesMissing, run, votes_header
from c4.eval.tables import render


def _observed(
    *candidate: str, baseline: str = "passed", warnings: tuple[str, ...] = ()
) -> Observed:
    return Observed(
        method="container-reproduction",
        captured_at="2026-09-27",
        baseline=[ObservedStep(name="test", outcome=baseline)],
        candidate=[ObservedStep(name="test", outcome=outcome) for outcome in candidate],
        warnings=list(warnings),
    )


def _case(case_id: str, old: str, new: str, observed: Observed) -> LabelledCase:
    return LabelledCase(
        case_id=case_id,
        source="hand",
        client=CaseClient(kind="seeded"),
        update=CaseUpdate(
            ecosystem="npm", package=f"pkg-{case_id}", from_version=old, to_version=new
        ),
        observed=observed,
        provenance="written by hand for the test",
    )


class TestTheRubric:
    def test_a_break_is_high(self) -> None:
        assert level(_observed("failed")) == "high"

    def test_a_timeout_is_a_break(self) -> None:
        assert level(_observed("timed-out")) == "high"

    def test_new_warnings_without_a_break_are_medium(self) -> None:
        assert level(_observed("passed", warnings=("DeprecationWarning: app.del",))) == "medium"

    def test_nothing_new_is_low(self) -> None:
        assert level(_observed("passed")) == "low"

    def test_a_broken_control_is_excluded_not_labelled(self) -> None:
        """If the installed version already fails, the update is not what failed."""
        found = level(_observed("failed", baseline="failed"))
        assert isinstance(found, Excluded) and "already broken" in found.reason

    def test_nothing_observed_is_excluded(self) -> None:
        assert isinstance(level(_observed("not-run")), Excluded)

    def test_a_lost_download_is_excluded_not_called_a_break(self) -> None:
        """The candidate's install failing because the registry dropped the
        connection is the network's doing, not the update's."""
        found = level(_observed("unavailable", "not-run"))
        assert isinstance(found, Excluded) and "download" in found.reason

    def test_a_lost_download_in_the_control_is_excluded_for_that_reason(self) -> None:
        found = level(_observed("passed", baseline="unavailable"))
        assert isinstance(found, Excluded) and "download" in found.reason

    @pytest.mark.parametrize(
        "category",
        [
            "COMPILATION_FAILURE",
            "TEST_FAILURE",
            "DEPENDENCY_RESOLUTION_FAILURE",
            "ENFORCER_FAILURE",
            "DEPENDENCY_LOCK_FAILURE",
            "WERROR_FAILURE",
        ],
    )
    def test_every_bump_category_is_a_break(self, category) -> None:
        observed = _observed("failed").model_copy(update={"failure_category": category})
        assert level(observed) == "high"


class TestTheSplit:
    def test_about_one_in_five_is_held_out(self) -> None:
        keys = [f"npm:pkg{i}@1.0.0->2.0.0" for i in range(2000)]
        share = sum(held_out(key) for key in keys) / len(keys)
        assert 0.17 < share < 0.23

    def test_the_same_update_is_always_on_the_same_side(self) -> None:
        key = "npm:express@4.21.2->5.1.0"
        assert len({held_out(key) for _ in range(5)}) == 1

    def test_growing_the_corpus_never_moves_a_case(self) -> None:
        """The split is a function of the key alone, so a case's side cannot
        depend on what else is in the corpus."""
        first = {f"k{i}": held_out(f"k{i}") for i in range(50)}
        again = {f"k{i}": held_out(f"k{i}") for i in range(200)}
        assert all(again[key] == side for key, side in first.items())


class TestScoring:
    def test_a_confusion_matrix_worked_out_by_hand(self) -> None:
        """Truth high high medium low; predicted high low medium low.
        Accuracy 3/4. High: precision 1, recall 1/2. Medium: 1 and 1.
        Low: precision 1/2, recall 1."""
        scores = score([("high", "high"), ("high", "low"), ("medium", "medium"), ("low", "low")])
        assert scores.accuracy == pytest.approx(0.75)
        assert scores.high_recall == pytest.approx(0.5)
        assert scores.missed_high == 1
        assert scores.macro_precision == pytest.approx((1 + 1 + 0.5) / 3)
        assert scores.macro_recall == pytest.approx((0.5 + 1 + 1) / 3)

    def test_an_abstention_scores_as_high_and_is_counted(self) -> None:
        scores = score([("high", None), ("low", None)])
        assert scores.abstained == 2
        assert scores.high_recall == 1.0
        assert scores.confusion["low"]["high"] == 1

    def test_never_predicting_a_class_does_not_help_the_average(self) -> None:
        """Truth has a Medium the arm never predicts: Medium still counts, at zero."""
        scores = score([("medium", "high"), ("high", "high")])
        assert scores.macro_recall == pytest.approx((0 + 1) / 2)

    def test_no_true_high_means_no_high_recall_rather_than_zero(self) -> None:
        assert score([("low", "low")]).high_recall is None


CASES = [
    _case("a", "1.2.3", "1.2.4", _observed("failed")),
    _case("b", "1.2.3", "2.0.0", _observed("passed")),
    _case("c", "1.2.3", "1.3.0", _observed("passed", warnings=("deprecated",))),
    _case("d", "1.2.3", "1.2.4", _observed("failed", baseline="failed")),
]


class TestTheStudy:
    def test_the_baseline_and_the_degenerate_arm_on_identical_cases(self) -> None:
        study = run(
            CASES, epoch="Test epoch", commit="abc1234", split="all", today=date(2026, 9, 27)
        )
        assert study["epoch"]["labelled"] == 3 and study["epoch"]["excluded"] == 1
        semver = study["arms"]["semver"]
        # a: patch called low, truly high. b: major called high, truly low. c: minor, medium.
        assert semver["accuracy"] == pytest.approx(1 / 3)
        assert semver["missed_high"] == 1
        assert study["arms"]["always-high"]["degenerate"] is True
        assert study["arms"]["always-high"]["high_recall"] == 1.0

    def test_recorded_votes_give_the_usage_arm_and_the_combined_arm(self) -> None:
        """a: a patch SemVer calls Low, usage High: combined High, truly High.
        b: a major SemVer calls High, usage abstains: combined High, truly Low.
        c: a minor SemVer calls Medium, usage Low: combined Medium, truly Medium.
        The combined arm scores 2 of 3; usage alone 1 of 3, its abstention on b
        scored as High."""
        usage = {"a": "high", "b": None, "c": "low", "d": "low"}
        semver = {"a": "low", "b": "high", "c": "medium", "d": "low"}
        votes = {
            case.case_id: {
                "semver": semver[case.case_id],
                "changelog": None,
                "changelogRun": False,
                "usage": {"level": usage[case.case_id]},
            }
            for case in CASES
        }
        study = run(CASES, epoch="Votes", commit="abc1234", split="all", votes=votes)
        assert list(study["arms"]) == [
            "semver",
            "usage",
            "semver+usage",
            "usage-gated",
            "always-high",
        ]
        assert study["arms"]["usage-gated"]["exploratory"] is True
        assert study["arms"]["semver+usage"]["accuracy"] == pytest.approx(2 / 3)
        assert study["arms"]["usage"]["accuracy"] == pytest.approx(1 / 3)
        assert study["arms"]["usage"]["abstained"] == 1
        assert study["cases"][0]["votes"]["usage"]["level"] == "high"

    def test_a_run_changelog_adds_its_pairs_the_hybrid_and_the_stated_level(self) -> None:
        """a is truly High, b Low, c Medium. Worked by hand, most cautious of what was cast:
        changelog     medium, low, (none: High)  -> 1 of 3
        semver+chl    medium, high, medium       -> 1 of 3
        chl+usage     high, low, low             -> 2 of 3
        hybrid        high, high, medium         -> 2 of 3
        stated        low, high, (none: High)    -> 0 of 3, and used by no rule."""
        semver = {"a": "low", "b": "high", "c": "medium", "d": "low"}
        changelog = {"a": "medium", "b": "low", "c": None, "d": "low"}
        stated = {"a": "low", "b": "high", "c": None, "d": "low"}
        usage = {"a": "high", "b": None, "c": "low", "d": "low"}
        votes = {
            case.case_id: {
                "semver": semver[case.case_id],
                "changelog": {
                    "level": changelog[case.case_id],
                    "model": (
                        {"statedLevel": stated[case.case_id]} if stated[case.case_id] else None
                    ),
                },
                "changelogRun": True,
                "usage": {"level": usage[case.case_id]},
            }
            for case in CASES
        }
        made = votes_header(
            {
                "recordedOn": "2026-09-27",
                "votes": votes,
                "changelog": {
                    "model": "deepseek:deepseek-flash",
                    "promptId": "changelog-extract/1",
                    "promptSha256": "c8558e129ab0" + "0" * 52,
                    "settings": {"maxTokens": 8192, "thinking": "disabled", "temperature": 0.0},
                    "commit": "5ddb67f",
                    "recordedOn": "2026-09-27",
                },
            }
        )
        study = run(
            CASES, epoch="Hybrid", commit="abc1234", split="all", votes=votes, votes_made=made
        )
        arms = study["arms"]
        assert list(arms) == [
            "semver",
            "changelog",
            "usage",
            "semver+changelog",
            "semver+usage",
            "changelog+usage",
            "hybrid",
            "changelog-stated",
            "usage-gated",
            "always-high",
        ]
        accuracy = {name: arm["accuracy"] for name, arm in arms.items()}
        assert accuracy["changelog"] == pytest.approx(1 / 3)
        assert accuracy["semver+changelog"] == pytest.approx(1 / 3)
        assert accuracy["changelog+usage"] == pytest.approx(2 / 3)
        assert accuracy["hybrid"] == pytest.approx(2 / 3)
        assert accuracy["changelog-stated"] == 0.0
        assert arms["changelog-stated"]["informational"] and not arms["hybrid"]["informational"]
        table = render(study)
        assert "| changelog-stated (informational) |" in table
        assert "rules semver-rule/1, changelog-rule/1, usage-rule/1, safety-first-max/1" in table
        assert (
            "model `deepseek:deepseek-flash`, prompt `changelog-extract/1` (`c8558e129ab0`)"
            in table
        )
        assert "max tokens 8192" in table and "run at `5ddb67f`" in table

    def test_a_votes_record_that_misses_a_case_is_refused(self) -> None:
        with pytest.raises(VotesMissing, match="nothing for"):
            run(CASES, epoch="Votes", commit="abc1234", split="all", votes={})

    def test_the_held_out_set_is_not_read_by_accident(self) -> None:
        with pytest.raises(HeldOutRefused):
            run(CASES, epoch="Peek", commit="abc1234", split="held-out")

    def test_each_ecosystem_is_scored_on_its_own_cases(self) -> None:
        maven = _case("m", "1.2.3", "1.2.4", _observed("failed")).model_copy(
            update={
                "update": CaseUpdate(
                    ecosystem="maven",
                    package="org.example:m",
                    from_version="1.2.3",
                    to_version="1.2.4",
                )
            }
        )
        study = run(
            [*CASES, maven], epoch="Split", commit="abc1234", split="all", today=date(2026, 9, 27)
        )
        assert study["byEcosystem"]["maven"]["semver"]["cases"] == 1
        assert study["byEcosystem"]["maven"]["semver"]["missed_high"] == 1
        assert study["byEcosystem"]["npm"]["semver"]["cases"] == 3
        table = render(study)
        assert "| semver | maven | 1 |" in table
        assert "Confusion, semver" in table and "Confusion, always-high" not in table

    def test_the_table_names_everything_it_was_computed_under(self) -> None:
        study = run(
            CASES, epoch="Test epoch", commit="abc1234", split="all", today=date(2026, 9, 27)
        )
        table = render(study)
        assert "Commit `abc1234`" in table and "outcome-rubric/1" in table
        assert "always-high (degenerate)" in table


BUMP_RECORD = {
    "url": "https://github.com/arextest/arex-agent-java/pull/194",
    "project": "arex-agent-java",
    "projectOrganisation": "arextest",
    "breakingCommit": "dc9a40fde9a9fee5aaec3f60695385ba539406d4",
    "updatedDependency": {
        "dependencyGroupID": "org.apache.dubbo",
        "dependencyArtifactID": "dubbo",
        "previousVersion": "2.7.3",
        "newVersion": "2.7.21",
        "dependencyScope": "provided",
        "versionUpdateType": "patch",
    },
    "preCommitReproductionCommand": "docker run ghcr.io/chains-project/breaking-updates:dc9a40fde9a9fee5aaec3f60695385ba539406d4-pre",
    "breakingUpdateReproductionCommand": "docker run ghcr.io/chains-project/breaking-updates:dc9a40fde9a9fee5aaec3f60695385ba539406d4-breaking",
    "javaVersionUsedForReproduction": "11",
    "failureCategory": "COMPILATION_FAILURE",
}


class TestTheBumpLoader:
    def test_a_record_becomes_a_high_case_the_version_number_calls_low(self) -> None:
        """The worked case's shape: a patch by number, a compile failure observed."""
        case = case_from_record(BUMP_RECORD, dataset_commit="main", captured_at="2026-09-27")
        assert (case.update.package, case.update.from_version, case.update.to_version) == (
            "org.apache.dubbo:dubbo",
            "2.7.3",
            "2.7.21",
        )
        assert case.source_change == "patch"
        assert level(case.observed) == "high"
        study = run([case], epoch="One", commit="abc", split="all")
        assert study["cases"][0]["predictions"]["semver"] == "low"


def test_the_command_line_writes_the_record_and_prints_the_table(tmp_path: Path, capsys) -> None:
    cases = tmp_path / "cases"
    cases.mkdir()
    for case in CASES:
        (cases / f"{case.case_id}.json").write_text(
            json.dumps(case.model_dump(by_alias=True, mode="json"))
        )
    out = tmp_path / "studies"

    code = main(
        [
            "--cases",
            str(cases),
            "--epoch",
            "Epoch Test",
            "--commit",
            "abc1234",
            "--split",
            "all",
            "--out",
            str(out),
        ]
    )

    assert code == 0
    assert (out / "epoch-test.json").exists()
    assert "Epoch Test" in capsys.readouterr().out
    assert main(["--tables", str(out)]) == 0


def test_a_breaking_images_compiler_errors_become_the_cases_failure_locations() -> None:
    from c4.eval.loaders.bump import failure_locations

    log = (
        "[INFO] Compiling 5 source files\n"
        "[ERROR] /arex-agent-java/mod/src/main/java/p/A.java:[43,47] incompatible types\n"
        "[ERROR] /arex-agent-java/mod/src/main/java/p/A.java:[45,60] incompatible types\n"
        "[ERROR] /arex-agent-java/mod/src/main/java/p/A.java:[43,47] incompatible types\n"
        "[ERROR] For more information about the errors\n"
    )
    found = failure_locations(log, workdir="/arex-agent-java")
    assert [(f.path, f.line) for f in found] == [
        ("mod/src/main/java/p/A.java", 43),
        ("mod/src/main/java/p/A.java", 45),
    ]
