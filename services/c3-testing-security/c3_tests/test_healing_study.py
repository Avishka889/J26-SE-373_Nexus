"""The self healing study: the numbers contribution B is judged on.

The headline contribution had no evaluation harness. Every heal report computed
its own rates and nothing pooled them, so the figure a dissertation quotes did
not exist.

What is held here is not the arithmetic, which is trivial, but the four
decisions the arithmetic encodes: pool rather than average, report the gap
rather than either rate, separate a caught cheat from a non answer, and score
classification in the dangerous direction.
"""

import json
import subprocess
import sys
from datetime import UTC, datetime
from typing import get_args

import pytest
from c3.eval.healing import (
    CAUGHT_CHEATS,
    INEFFECTIVE,
    NON_ANSWERS,
    UNCHECKED,
    as_epoch_row,
    combine,
    rejudged,
    study,
)
from sdlc_contracts import (
    ClassificationEvidence,
    DiffSpan,
    GuardCheck,
    HealAttempt,
    HealReport,
)
from sdlc_contracts.heal_report import RefusalReason


def _attempt(
    test_id: str = "t1",
    *,
    classification: str = "brittle",
    classified_by: str = "trace-changed",
    accepted: bool = False,
    has_diff: bool = True,
    refusal: str | None = None,
) -> HealAttempt:
    checks = (
        [
            GuardCheck(name="test-code-only", passed=True, detail="one test file"),
            GuardCheck(name="passes-unchanged-code", passed=True, detail="green"),
            GuardCheck(
                name="kills-a-mutant",
                passed=accepted,
                detail="killed 2 of 3" if accepted else "killed 0 of 3",
            ),
        ]
        if has_diff
        else []
    )
    # The contract refuses two shapes that a careless fixture produces, and
    # both refusals are worth keeping live rather than working around: a
    # referee that decided without citing what it relied on, and a repair
    # refused without a reason. Satisfying them here is a line of setup; a
    # fixture that evaded them would be testing a report the store would never
    # accept.
    evidence = ClassificationEvidence(
        traced_to=["R-4"],
        changed_artefacts=["R-4"] if classification == "brittle" else [],
        cited_diff_span=(
            "[R1] requirement R-4 changed its rounding" if classified_by == "model-referee" else ""
        ),
        referee_reasoning=(
            "the behaviour moved on purpose" if classified_by == "model-referee" else ""
        ),
    )
    if has_diff and not accepted and refusal is None:
        refusal = "kills-no-mutant"
    return HealAttempt(
        test_id=test_id,
        test_name=test_id,
        suite_path="apps/web/src/__tests__/basket.test.ts",
        failure_message="expected 3.01 to be 3.005",
        classification=classification,  # type: ignore[arg-type]
        classified_by=classified_by,  # type: ignore[arg-type]
        evidence=evidence,
        accepted=accepted,
        attempts=1 if has_diff else 0,
        diff=DiffSpan(path="apps/web/src/__tests__/basket.test.ts", diff="@@\n-a\n+b")
        if has_diff
        else None,
        checks=checks,
        refusal_reason=refusal,  # type: ignore[arg-type]
        passed_on_unchanged_run_id="run-1" if accepted else "",
    )


def _report(attempts: list[HealAttempt], version: int = 1) -> HealReport:
    return HealReport(
        version=version,
        generated_at=datetime.now(UTC),
        target="apps/web",
        from_code_version=version,
        to_code_version=version + 1,
        attempts=attempts,
    )


class TestTheGapIsTheResult:
    def test_a_weakened_repair_counts_as_produced_and_not_as_accepted(self) -> None:
        """The whole study in one case. A loop without a guard reports this as
        a success; this one reports it as a repair that was produced and
        refused, and the difference between those two numbers is the point."""
        found = study([_report([_attempt(accepted=False, refusal="kills-no-mutant")])])

        assert found.convergence.naive == 100.0
        assert found.convergence.strict == 0.0
        assert found.convergence.gap == 100.0

    def test_an_honest_repair_closes_the_gap(self) -> None:
        found = study([_report([_attempt(accepted=True)])])

        assert (found.convergence.naive, found.convergence.strict) == (100.0, 100.0)
        assert found.convergence.gap == 0.0

    def test_a_model_that_answers_nothing_shows_no_gap_either(self) -> None:
        """A gap of zero means either a model that never cheated or one that
        never answered, and only the refusal breakdown says which. That is why
        the gap is never reported alone."""
        found = study([_report([_attempt(has_diff=False, refusal="malformed-output")])])

        assert found.convergence.gap == 0.0
        assert found.non_answers == 1
        assert found.caught_cheats == 0

    def test_a_regression_is_not_a_failed_repair(self) -> None:
        """Refusing to heal a real bug is the point, not a miss. Counting it in
        the denominator would make a run full of real bugs look like a loop
        that could not fix them."""
        found = study(
            [
                _report(
                    [
                        _attempt("t1", accepted=True),
                        _attempt(
                            "t2",
                            classification="regression",
                            classified_by="trace-unchanged",
                            has_diff=False,
                        ),
                    ]
                )
            ]
        )

        assert found.convergence.brittle == 1
        assert found.convergence.strict == 100.0
        assert found.regressions_flagged == 1


class TestPooledRatherThanAveraged:
    def test_a_big_run_outweighs_a_small_one(self) -> None:
        """Averaging two reports' percentages would call this 50 percent. Nine
        of ten repairs were accepted, and the number is 90."""
        small = _report([_attempt("a", accepted=False, refusal="kills-no-mutant")])
        big = _report([_attempt(f"b{n}", accepted=True) for n in range(9)], version=2)

        found = study([small, big])

        assert found.convergence.brittle == 10
        assert found.convergence.strict == 90.0

    def test_combining_studies_adds_counts_not_rates(self) -> None:
        first = study([_report([_attempt("a", accepted=True)])])
        second = study([_report([_attempt(f"b{n}") for n in range(3)], version=2)])

        together = combine([first, second])

        assert together.convergence.brittle == 4
        assert together.convergence.repairs_accepted == 1
        assert together.convergence.strict == 25.0

    def test_nothing_measured_is_zero_rather_than_an_error(self) -> None:
        found = study([])

        assert found.convergence.strict == 0.0
        assert found.attempts == 0


class TestARefusalIsNotJustARefusal:
    @pytest.mark.parametrize("reason", sorted(CAUGHT_CHEATS))
    def test_a_dishonest_repair_is_counted_as_one(self, reason) -> None:
        """A caught cheat is evidence the guard works. A non answer is evidence
        the model is unusable. One refusal rate would put them in the same
        column."""
        found = study([_report([_attempt(refusal=reason)])])

        assert found.caught_cheats == 1
        assert found.non_answers == 0

    def test_every_reason_is_reported_separately(self) -> None:
        found = study(
            [
                _report(
                    [
                        _attempt("a", refusal="kills-no-mutant"),
                        _attempt("b", refusal="assertion-weakened"),
                        _attempt("c", refusal="malformed-output", has_diff=False),
                    ]
                )
            ]
        )

        assert found.refusals == {
            "kills-no-mutant": 1,
            "assertion-weakened": 1,
            "malformed-output": 1,
        }

    def test_an_accepted_repair_contributes_no_refusal(self) -> None:
        assert study([_report([_attempt(accepted=True)])]).refusals == {}

    @pytest.mark.parametrize("reason", ["still-failing", "touched-production-code"])
    def test_a_repair_that_did_not_work_is_neither_of_the_other_two(self, reason) -> None:
        """A model that answered and was wrong is a third thing.

        The first live healing run on generated code produced six of these and
        nothing else. Counted as cheats they would have said the guard caught six
        dishonest repairs; counted as non answers they would have said the model
        returned nothing. Both would have been wrong about the same six rows, and
        the first would have flattered the number this component is judged on.
        """
        found = study([_report([_attempt(refusal=reason)])])

        assert found.ineffective == 1
        assert found.caught_cheats == 0
        assert found.non_answers == 0

    def test_a_repair_the_guard_could_not_check_is_not_a_caught_cheat(self) -> None:
        """No code the test reaches was found to break, so nobody was caught.

        Every generated acceptance test landed here as `kills-no-mutant`, a
        caught cheat, while the guard read static imports only: the guard's
        blind spot, booked as the model's dishonesty.
        """
        found = study([_report([_attempt(refusal="no-code-to-check")])])

        assert found.unchecked == 1
        assert found.caught_cheats == 0
        assert found.as_dict()["unchecked"] == 1
        assert "1 the guard found no code to check against" in found.table()

    def test_the_four_columns_account_for_every_reason(self) -> None:
        """A reason in none of them is a refusal that vanishes from the study."""
        every = set(get_args(RefusalReason))
        columns = (CAUGHT_CHEATS, NON_ANSWERS, INEFFECTIVE, UNCHECKED)

        assert every == CAUGHT_CHEATS | NON_ANSWERS | INEFFECTIVE | UNCHECKED
        for index, one in enumerate(columns):
            for other in columns[index + 1 :]:
                assert not one & other
        assert "no-code-to-check" in UNCHECKED
        # Named rather than derived from the sets, or emptying one and folding
        # its reasons into another leaves every assertion above still true.
        assert "kills-no-mutant" in CAUGHT_CHEATS
        assert "still-failing" in INEFFECTIVE
        assert "still-failing" not in CAUGHT_CHEATS


def _judged(*, passes: bool, kills: bool, stored: str, test_id: str = "t1") -> HealAttempt:
    """A repair the guard ran all three checks on, with the name the run stored."""
    return _attempt(test_id, refusal=stored).model_copy(
        update={
            "checks": [
                GuardCheck(name="test-code-only", passed=True, detail="one test file"),
                GuardCheck(name="passes-unchanged-code", passed=passes, detail="as measured"),
                GuardCheck(name="kills-a-mutant", passed=kills, detail="as measured"),
            ]
        }
    )


class TestARefusalDecidedAgainFromItsChecks:
    """Reports from before defect 22 named a repair that did not work as a cheat.

    The guard asked whether a repair kills a mutant before asking whether it
    passes, and a test that already fails cannot kill one, so every repair that
    did not work was stored as `kills-no-mutant`, the caught cheat. The checks
    are the guard's measurements and were right; only the name was decided in
    the wrong order. Epoch 12's six are stored that way.
    """

    def test_a_repair_that_did_not_work_is_named_so(self) -> None:
        stored = _report([_judged(passes=False, kills=False, stored="kills-no-mutant")])

        [report], changed = rejudged([stored])

        assert changed == 1
        assert report.attempts[0].refusal_reason == "still-failing"
        found = study([report])
        assert found.caught_cheats == 0
        assert found.ineffective == 1

    def test_a_name_the_run_got_right_is_kept(self) -> None:
        stored = _report([_judged(passes=True, kills=False, stored="kills-no-mutant")])

        [report], changed = rejudged([stored])

        assert changed == 0
        assert report.attempts[0].refusal_reason == "kills-no-mutant"

    def test_a_check_the_guard_could_not_run_keeps_what_the_run_knew(self) -> None:
        """Whether any code the test reaches was found is not in the report."""
        stored = _report([_judged(passes=True, kills=False, stored="no-code-to-check")])

        [report], changed = rejudged([stored])

        assert changed == 0
        assert report.attempts[0].refusal_reason == "no-code-to-check"

    def test_an_attempt_the_guard_never_judged_is_left_alone(self) -> None:
        """No repair, so no checks of the guard's to decide from."""
        silent = _attempt(has_diff=False, refusal="no-repair-produced").model_copy(
            update={
                "checks": [GuardCheck(name="test-code-only", passed=False, detail="no repairer")]
            }
        )

        [report], changed = rejudged([_report([silent])])

        assert changed == 0
        assert report.attempts[0].refusal_reason == "no-repair-produced"

    def test_the_row_says_how_many_were_decided_again(self) -> None:
        stored = _report([_judged(passes=False, kills=False, stored="kills-no-mutant")])
        reports, changed = rejudged([stored])

        row = as_epoch_row(study(reports), label="epoch-12", rejudged=changed)

        assert row["refusalsRejudged"] == 1
        assert "refusalsRejudged" not in as_epoch_row(study(reports), label="epoch-12")

    def test_the_command_decides_again_only_when_asked(self, tmp_path) -> None:
        """A stored number is scored as stored unless the command is told otherwise."""
        stored = _report([_judged(passes=False, kills=False, stored="kills-no-mutant")])
        directory = tmp_path / "reports"
        directory.mkdir()
        (directory / "run.json").write_text(stored.model_dump_json(by_alias=True))

        rows = {}
        for flags in ([], ["--rejudge"]):
            out = tmp_path / f"row-{len(flags)}.json"
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "c3.eval",
                    "--healing",
                    str(directory),
                    "--out",
                    str(out),
                    "--epoch",
                    "epoch-12",
                    *flags,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            rows[bool(flags)] = json.loads(out.read_text())

        assert rows[False]["caughtCheats"] == 1
        assert "refusalsRejudged" not in rows[False]
        assert rows[True]["caughtCheats"] == 0
        assert rows[True]["ineffective"] == 1
        assert rows[True]["refusalsRejudged"] == 1


class TestClassificationInTheDangerousDirection:
    def test_a_regression_called_brittle_is_named_as_the_expensive_error(self) -> None:
        """It sends a real bug to be papered over, and only the guard stands
        between that and a green suite over broken code."""
        found = study(
            [_report([_attempt("t1", classification="brittle")])],
            labels={"t1": "regression"},
        )

        assert found.classification.regressions_called_brittle == 1
        assert found.classification.brittle_called_regression == 0
        assert found.classification.accuracy == 0.0

    def test_brittleness_called_a_regression_is_the_cheap_one(self) -> None:
        found = study(
            [_report([_attempt("t1", classification="regression", has_diff=False)])],
            labels={"t1": "brittle"},
        )

        assert found.classification.brittle_called_regression == 1
        assert found.classification.regressions_called_brittle == 0

    def test_a_regression_whose_repair_was_accepted_is_a_bug_hidden(self) -> None:
        """The outcome the guard exists to prevent, and it was counted only as
        strict convergence: on E-2's second run the one accepted repair turned a
        correct test into one that asserts the bug (E-29)."""
        found = study(
            [_report([_attempt("t1", classification="brittle", accepted=True)])],
            labels={"t1": "regression"},
        )

        assert found.classification.regressions_healed == 1
        assert found.as_dict()["classification"]["regressionsHealed"] == 1
        assert "a bug hidden behind a green test" in found.table()

    def test_a_refused_repair_of_a_regression_hid_nothing(self) -> None:
        found = study(
            [_report([_attempt("t1", classification="brittle", refusal="still-failing")])],
            labels={"t1": "regression"},
        )

        assert found.classification.regressions_called_brittle == 1
        assert found.classification.regressions_healed == 0

    def test_hidden_bugs_are_added_when_studies_are_combined(self) -> None:
        one = study(
            [_report([_attempt("t1", classification="brittle", accepted=True)])],
            labels={"t1": "regression"},
        )

        assert combine([one, one]).classification.regressions_healed == 2

    def test_undecided_is_not_counted_as_wrong(self) -> None:
        """An undecided failure reaching a person is the designed outcome when
        the evidence does not settle it."""
        found = study(
            [
                _report(
                    [
                        _attempt(
                            "t1",
                            classification="undecided",
                            classified_by="unclassified",
                            has_diff=False,
                        ),
                        _attempt("t2", classification="brittle", accepted=True),
                    ]
                )
            ],
            labels={"t1": "brittle", "t2": "brittle"},
        )

        assert found.classification.undecided == 1
        assert found.classification.accuracy == 50.0
        assert found.classification.accuracy_when_decided == 100.0

    def test_an_unlabelled_failure_is_not_scored(self) -> None:
        """Scoring the loop against its own verdicts would measure its
        consistency rather than its correctness."""
        found = study([_report([_attempt("t1")])], labels={})

        assert found.classification.labelled == 0
        assert found.classification.accuracy == 0.0

    def test_convergence_is_produced_without_any_labels(self) -> None:
        found = study([_report([_attempt(accepted=True)])])

        assert found.convergence.strict == 100.0
        assert found.classification.labelled == 0


class TestHowMuchTheRulesDecidedAlone:
    def test_the_trace_signal_is_counted_apart_from_the_model(self) -> None:
        """The platform's own contribution. A model refereed only the
        ambiguous middle, and how small that middle is says how much the
        contract and requirement diffs are doing."""
        found = study(
            [
                _report(
                    [
                        _attempt("a", classified_by="trace-changed", accepted=True),
                        _attempt(
                            "b",
                            classified_by="trace-unchanged",
                            classification="regression",
                            has_diff=False,
                        ),
                        _attempt("c", classified_by="trace-changed", accepted=True),
                        _attempt("d", classified_by="model-referee", accepted=True),
                    ]
                )
            ]
        )

        assert found.rule_decided == 75.0
        assert found.classified_by["model-referee"] == 1

    def test_a_test_written_after_the_change_is_decided_by_a_rule_too(self) -> None:
        """E-25's rule reads the case's first version, not a model."""
        found = study(
            [
                _report(
                    [
                        _attempt(
                            "a",
                            classified_by="written-after-change",
                            classification="regression",
                            has_diff=False,
                        ),
                        _attempt("b", classified_by="model-referee", accepted=True),
                    ]
                )
            ]
        )

        assert found.rule_decided == 50.0


class TestTheTableAReaderSees:
    def test_it_names_the_gap_rather_than_only_the_rates(self) -> None:
        found = study(
            [
                _report(
                    [
                        _attempt("a", accepted=True),
                        _attempt("b", refusal="kills-no-mutant"),
                    ]
                )
            ]
        )

        table = found.table()

        assert "the guard caught" in table
        assert "50.00 points" in table

    def test_it_separates_dishonesty_from_silence(self) -> None:
        found = study(
            [
                _report(
                    [
                        _attempt("a", refusal="assertion-weakened"),
                        _attempt("b", refusal="malformed-output", has_diff=False),
                    ]
                )
            ]
        )

        assert "1 for dishonesty and 1 for silence" in found.table()
