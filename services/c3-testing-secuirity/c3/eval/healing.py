"""The self healing study: what the guard caught, and what it cost.

Contribution A had an evaluation harness from the start and contribution B,
which is the headline, had none. Every heal report computes its own rates, and
nothing aggregated them across runs, which means the number the dissertation
actually quotes did not exist.

**Pooled, never averaged.** A run with one brittle test and a run with forty
are not two data points of equal weight, and averaging their percentages says
they are. Every rate here is computed from the pooled attempts, the same rule
the per class detection scoring follows and for the same reason.

**The gap is the result, not the rates.** Naive convergence counts every
brittle test a repair was produced for; strict counts the repairs that cleared
the guard. A loop without a guard would report the first and call it success.
The difference between them is what the guard is worth, and reporting either
alone hides it: the naive number flatters, and the strict number on its own
looks like a weak model rather than a working fence.

**Refusals are separated by reason because they say different things.** A model
that weakened an assertion cheated and was caught. A model that returned
nothing failed to answer. Pooling those into one refusal rate would put a
caught cheat and a non answer in the same column, and the first is evidence the
guard works while the second is evidence the model is unusable.

**Classification is scored in the dangerous direction.** Calling a regression
brittle sends a real bug to be papered over; calling brittleness a regression
costs a person a look. The two errors are not symmetric, so they are reported
separately rather than as one accuracy figure that would let a model trade the
cheap mistake for the expensive one and look unchanged.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from sdlc_contracts import HealAttempt, HealReport

#: The refusal this component exists to produce. A repair that would have
#: passed every other check and cannot fail is the documented cheat, and how
#: often the guard catches it is the headline number of contribution B.
CAUGHT_CHEATS = frozenset({"assertion-weakened", "kills-no-mutant", "test-deleted"})

#: A model that did not answer, rather than one that answered dishonestly.
NON_ANSWERS = frozenset({"no-repair-produced", "malformed-output"})

#: A model that answered and was wrong: the repair changed only test code and
#: still does not pass, or it reached past the application under test.
#:
#: Its own column because it is neither of the others, and because the first
#: live healing run on generated code produced six of these and nothing else.
#: Counted as cheats they would have said the guard caught six dishonest
#: repairs; counted as non answers they would have said the model returned
#: nothing. Both would have been wrong about the same six rows.
INEFFECTIVE = frozenset({"still-failing", "touched-production-code"})

#: The guard unable to ask its third question: no production code the test
#: reaches was found to break. Its own column, because it is neither a model
#: that cheated nor one that did not answer. Every generated acceptance test
#: landed here, counted as a caught cheat, while the guard read static imports
#: only and the tests load their app with a dynamic one.
UNCHECKED = frozenset({"no-code-to-check"})


@dataclass
class Convergence:
    """What the loop achieved on the tests it was allowed to repair."""

    brittle: int = 0
    repairs_produced: int = 0
    repairs_accepted: int = 0

    @property
    def naive(self) -> float:
        """What a loop without a guard would have reported."""
        return round(self.repairs_produced / self.brittle * 100, 2) if self.brittle else 0.0

    @property
    def strict(self) -> float:
        """What this loop reports: repairs that cleared the guard."""
        return round(self.repairs_accepted / self.brittle * 100, 2) if self.brittle else 0.0

    @property
    def gap(self) -> float:
        """The guard's effect, in percentage points.

        The single number this study exists to produce. A gap of zero means
        either a model that never cheated or a guard that never caught one, and
        the refusal breakdown says which.
        """
        return round(self.naive - self.strict, 2)

    def as_dict(self) -> dict:
        return {
            "brittle": self.brittle,
            "repairsProduced": self.repairs_produced,
            "repairsAccepted": self.repairs_accepted,
            "naiveConvergence": self.naive,
            "strictConvergence": self.strict,
            "guardEffect": self.gap,
        }


@dataclass
class ClassificationScore:
    """How well the classifier told a stale test from a real bug.

    Counted against hand labels rather than against the loop's own verdict,
    which would make it a measure of its own consistency.
    """

    labelled: int = 0
    correct: int = 0
    #: A regression the classifier called brittle. The expensive error: it
    #: sends a real bug to be papered over, and only the guard stands between
    #: that and a green suite over broken code.
    regressions_called_brittle: int = 0
    #: Brittleness the classifier called a regression. The cheap error: a
    #: person looks at a test that was stale.
    brittle_called_regression: int = 0
    #: Neither, left for a person. Not an error: an undecided failure reaching
    #: a human is the designed outcome when the evidence does not settle it.
    undecided: int = 0

    @property
    def accuracy(self) -> float:
        return round(self.correct / self.labelled * 100, 2) if self.labelled else 0.0

    @property
    def decided(self) -> int:
        return self.labelled - self.undecided

    @property
    def accuracy_when_decided(self) -> float:
        """Accuracy over the failures it was willing to decide.

        Reported beside the overall figure because a classifier that answers
        undecided to everything scores zero on one and is not wrong, only
        useless, and the two failures deserve different words.
        """
        return round(self.correct / self.decided * 100, 2) if self.decided else 0.0

    def as_dict(self) -> dict:
        return {
            "labelled": self.labelled,
            "correct": self.correct,
            "accuracy": self.accuracy,
            "decided": self.decided,
            "accuracyWhenDecided": self.accuracy_when_decided,
            "undecided": self.undecided,
            "regressionsCalledBrittle": self.regressions_called_brittle,
            "brittleCalledRegression": self.brittle_called_regression,
        }


@dataclass
class HealingStudy:
    """One run of the self healing evaluation, ready to be written down."""

    reports: int = 0
    attempts: int = 0
    convergence: Convergence = field(default_factory=Convergence)
    classification: ClassificationScore = field(default_factory=ClassificationScore)
    #: Every refusal, by its reason. Ordered by count when rendered.
    refusals: dict[str, int] = field(default_factory=dict)
    #: How the classifier reached its verdicts. The trace based signal is the
    #: novel one, so how often it decided alone is a result about the platform
    #: rather than about the model.
    classified_by: dict[str, int] = field(default_factory=dict)
    regressions_flagged: int = 0

    @property
    def caught_cheats(self) -> int:
        """Repairs refused for being dishonest rather than absent."""
        return sum(count for reason, count in self.refusals.items() if reason in CAUGHT_CHEATS)

    @property
    def non_answers(self) -> int:
        return sum(count for reason, count in self.refusals.items() if reason in NON_ANSWERS)

    @property
    def ineffective(self) -> int:
        """Repairs refused for not working, which is neither of the other two."""
        return sum(count for reason, count in self.refusals.items() if reason in INEFFECTIVE)

    @property
    def unchecked(self) -> int:
        """Repairs refused because the guard found no code to check them against."""
        return sum(count for reason, count in self.refusals.items() if reason in UNCHECKED)

    @property
    def rule_decided(self) -> float:
        """Share of classifications the traceability rules settled alone.

        The platform's own contribution to the loop. A model refereed only the
        ambiguous middle, and how small that middle is says how much of the
        work the contract and requirement diffs are doing.
        """
        total = sum(self.classified_by.values())
        rules = self.classified_by.get("trace-changed", 0) + self.classified_by.get(
            "trace-unchanged", 0
        )
        return round(rules / total * 100, 2) if total else 0.0

    def as_dict(self) -> dict:
        return {
            "reports": self.reports,
            "attempts": self.attempts,
            "regressionsFlagged": self.regressions_flagged,
            "convergence": self.convergence.as_dict(),
            "classification": self.classification.as_dict(),
            "refusals": dict(sorted(self.refusals.items(), key=lambda item: -item[1])),
            "caughtCheats": self.caught_cheats,
            "nonAnswers": self.non_answers,
            "ineffective": self.ineffective,
            "unchecked": self.unchecked,
            "classifiedBy": dict(sorted(self.classified_by.items(), key=lambda item: -item[1])),
            "ruleDecidedPercent": self.rule_decided,
        }

    def table(self) -> str:
        """The study as text, for a terminal and for a first draft."""
        convergence = self.convergence
        lines = [
            f"{self.reports} reports, {self.attempts} attempts, "
            f"{self.regressions_flagged} regressions flagged and never healed",
            "",
            f"{'brittle tests':22} {convergence.brittle}",
            f"{'repairs produced':22} {convergence.repairs_produced}",
            f"{'repairs accepted':22} {convergence.repairs_accepted}",
            f"{'naive convergence':22} {convergence.naive:.2f}%",
            f"{'strict convergence':22} {convergence.strict:.2f}%",
            f"{'the guard caught':22} {convergence.gap:.2f} points",
            "",
            f"refused, {self.caught_cheats} for dishonesty and {self.non_answers} for silence"
            + (
                f", and {self.unchecked} the guard found no code to check against"
                if self.unchecked
                else ""
            )
            + ":",
        ]
        for reason, count in sorted(self.refusals.items(), key=lambda item: -item[1]):
            lines.append(f"  {reason:24} {count}")
        if self.classification.labelled:
            score = self.classification
            lines.extend(
                [
                    "",
                    f"classification over {score.labelled} labelled failures:",
                    f"  {'accuracy':24} {score.accuracy:.2f}%",
                    f"  {'when it decided':24} {score.accuracy_when_decided:.2f}% "
                    f"of {score.decided}",
                    f"  {'regression called brittle':24} {score.regressions_called_brittle} "
                    "(the expensive error)",
                    f"  {'brittle called regression':24} {score.brittle_called_regression} "
                    "(the cheap one)",
                ]
            )
        lines.extend(["", f"the rules decided {self.rule_decided:.2f}% without a model"])
        return "\n".join(lines)


def study(
    reports: Iterable[HealReport],
    *,
    labels: dict[str, str] | None = None,
) -> HealingStudy:
    """Every heal report as one set of numbers.

    `labels` maps a test id to what a person decided it really was, `brittle`
    or `regression`. Without it the convergence and refusal figures are still
    produced; only the classification score needs ground truth, and inventing
    that ground truth from the loop's own verdicts would measure the loop
    against itself.
    """
    found = HealingStudy()
    truth = labels or {}

    for report in reports:
        found.reports += 1
        for attempt in report.attempts:
            found.attempts += 1
            _count_classification(found, attempt)
            _count_repair(found, attempt)
            _score_against_labels(found, attempt, truth)
    return found


def _count_classification(found: HealingStudy, attempt: HealAttempt) -> None:
    found.classified_by[attempt.classified_by] = (
        found.classified_by.get(attempt.classified_by, 0) + 1
    )
    if attempt.classification == "regression":
        found.regressions_flagged += 1


def _count_repair(found: HealingStudy, attempt: HealAttempt) -> None:
    """Only brittle tests are repaired, so only they count towards convergence.

    A regression is flagged and never healed. Counting it in the denominator
    would make a run with many real bugs look like a loop that failed to fix
    them, when refusing to fix them is the whole point.
    """
    if attempt.classification != "brittle":
        return
    found.convergence.brittle += 1
    if attempt.diff is not None:
        found.convergence.repairs_produced += 1
    if attempt.accepted:
        found.convergence.repairs_accepted += 1
    if attempt.refusal_reason:
        found.refusals[attempt.refusal_reason] = found.refusals.get(attempt.refusal_reason, 0) + 1


def _score_against_labels(found: HealingStudy, attempt: HealAttempt, truth: dict[str, str]) -> None:
    actual = truth.get(attempt.test_id)
    if actual is None:
        return
    score = found.classification
    score.labelled += 1
    if attempt.classification == "undecided":
        score.undecided += 1
        return
    if attempt.classification == actual:
        score.correct += 1
    elif actual == "regression":
        score.regressions_called_brittle += 1
    else:
        score.brittle_called_regression += 1


def combine(studies: Sequence[HealingStudy]) -> HealingStudy:
    """Several studies as one, by adding the counts.

    Counts rather than rates, so the pooled result is what it would have been
    had everything run at once. Adding rates would be the averaging this module
    exists to avoid.
    """
    total = HealingStudy()
    for one in studies:
        total.reports += one.reports
        total.attempts += one.attempts
        total.regressions_flagged += one.regressions_flagged
        total.convergence.brittle += one.convergence.brittle
        total.convergence.repairs_produced += one.convergence.repairs_produced
        total.convergence.repairs_accepted += one.convergence.repairs_accepted
        for reason, count in one.refusals.items():
            total.refusals[reason] = total.refusals.get(reason, 0) + count
        for how, count in one.classified_by.items():
            total.classified_by[how] = total.classified_by.get(how, 0) + count
        score, other = total.classification, one.classification
        score.labelled += other.labelled
        score.correct += other.correct
        score.undecided += other.undecided
        score.regressions_called_brittle += other.regressions_called_brittle
        score.brittle_called_regression += other.brittle_called_regression
    return total


def as_epoch_row(found: HealingStudy, *, label: str, commit: str = "", model: str = "") -> dict:
    """The study with the provenance every dissertation number carries."""
    return {"epoch": label, "commit": commit, "model": model, **found.as_dict()}
