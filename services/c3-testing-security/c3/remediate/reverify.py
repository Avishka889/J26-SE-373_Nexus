"""Did the fix work, answered by subtraction rather than by opinion.

A remediation is applied and then the target is scanned and tested again. What
comes back is two snapshots, and the question "did this work" has an arithmetic
answer: fewer open findings and no more failing tests than before.

**The contract computes the verdict, not this module.** `Reverification.worsened`
is a computed field, so a report cannot record "verified" over numbers that say
otherwise, and the model validator on the proposal refuses that combination
outright. What is here is the part that builds the two snapshots honestly, which
is where the real mistake is available.

**The mistake this is written to avoid.** A re-verification that scans with a
different arm, or a narrower file list, or a re-run that skipped mutation,
produces a smaller "after" number for reasons that have nothing to do with the
patch. That reads as success and is not. So the comparison refuses a pair of
snapshots that were not taken the same way, and says so, rather than
subtracting two numbers that were never comparable.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from sdlc_contracts import (
    PatchHunk,
    Reverification,
    TestReport,
    ValidationReport,
    VerificationSnapshot,
    still_raised,
)


# Not frozen, and not a detail: Python's exception machinery assigns to an
# exception while raising it, so a frozen dataclass raises FrozenInstanceError
# from inside the raise and buries the real failure.
@dataclass
class NotComparable(Exception):
    """Two passes that cannot honestly be subtracted, and why."""

    why: str

    def __str__(self) -> str:
        return self.why


def outcomes(report: TestReport) -> dict[str, str]:
    """Every case in the report, by id, as it came out."""
    return {case.id: case.outcome for suite in report.suites for case in suite.cases}


def snapshot_of(
    validation: ValidationReport, tests: TestReport, *, only: set[str] | None = None
) -> VerificationSnapshot:
    """One moment, as the four numbers the comparison needs.

    `only` restricts the test counts to named cases, and the comparison always
    passes the cases both passes ran. **The suite is regenerated between runs**,
    so the second pass is not the first pass's suite: a model that filled a
    criterion one way today and another way tomorrow changes the pass count for
    reasons that have nothing to do with the patch. The first live run of this
    loop broke a test with `expect is not defined`, which was the fill's doing
    and would have been reported as the fix breaking something.
    """
    counted = outcomes(tests)
    if only is not None:
        counted = {case: outcome for case, outcome in counted.items() if case in only}
    return VerificationSnapshot(
        open_findings=validation.open_findings,
        tests_passed=sum(1 for outcome in counted.values() if outcome == "passed"),
        tests_failed=sum(1 for outcome in counted.values() if outcome in ("failed", "errored")),
        # Null rather than zero when mutation did not run: zero is a real score
        # and means every mutant survived, which is the opposite of not knowing.
        # `TestReport` carries the whole result or nothing, and says why when
        # it is nothing, so the absence is already explained by the time it
        # reaches here.
        mutation_score=tests.mutation.score if tests.mutation else None,
    )


def compare(
    before_validation: ValidationReport,
    before_tests: TestReport,
    after_validation: ValidationReport,
    after_tests: TestReport,
    *,
    before_run_id: str = "",
    after_run_id: str = "",
    finding_id: str = "",
    patch: Sequence[PatchHunk] = (),
) -> Reverification:
    """Before and after, refused when the two were not measured alike.

    With `finding_id`, the finding the fix was for is looked for in the after
    pass too, where `patch` left it (`still_raised`): totals alone called a fix
    verified with its own finding still raised (review item C3-7). A finding
    the before pass does not raise is refused, because there is then nothing
    to look for.

    Three ways a pair can be incomparable, and all three have produced a
    flattering number somewhere:

    The arms differ. A before pass with three detection arms and an after pass
    with one will close findings the patch never touched.

    A fourth thing is not a refusal but a correction: the test halves are
    counted over the cases that passed in the first run and ran again in the
    second. The suite is regenerated on every run, so comparing two different
    suites reports the generator's choices as the patch's effect, and a test
    that was not passing before cannot have been broken by the patch.

    The file counts differ sharply. A narrower after pass looks like a fix.
    Sharply rather than exactly, because a remediation may legitimately add or
    remove a file.

    The suite did not run after. Zero failures out of zero tests is not a
    passing suite, and neither is a suite whose every case reports `not-run`,
    which is what a lane that could not start produces.
    """
    before_arms = {run.arm for run in before_validation.detector_runs}
    after_arms = {run.arm for run in after_validation.detector_runs}
    if before_arms != after_arms:
        raise NotComparable(
            f"the before pass used {sorted(before_arms) or 'no arm'} and the after pass used "
            f"{sorted(after_arms) or 'no arm'}, so a change in findings says as much about "
            "the arms as about the patch"
        )

    before_files = sum(run.files_scanned for run in before_validation.detector_runs)
    after_files = sum(run.files_scanned for run in after_validation.detector_runs)
    if before_files and abs(after_files - before_files) > max(2, before_files * 0.1):
        raise NotComparable(
            f"the before pass read {before_files} files and the after pass read {after_files}, "
            "which is too different to subtract"
        )

    if after_tests.total == 0 or after_tests.not_run == after_tests.total:
        raise NotComparable(
            "the suite did not run after the patch, so nothing is known about whether it broke "
            "anything. A suite that did not run is not a suite that passed"
        )

    # The tests that passed before and exist after. Two corrections in one set,
    # and the live run needed both.
    #
    # Generation runs again on every run, so the second pass is not the first
    # pass's suite and a case only one of them has says nothing about the patch.
    # And a case that did not pass before cannot have been broken by the patch:
    # the first live comparison counted a criterion that was an unwritten todo
    # in the before pass and a filled failing test in the after pass, which is
    # the generator's doing and read as the fix breaking something.
    #
    # Restricted this way the arithmetic is right by construction: nothing in
    # the set failed before, so what fails after is exactly what broke.
    after_ran = set(outcomes(after_tests))
    common = {
        case for case, outcome in outcomes(before_tests).items() if outcome == "passed"
    } & after_ran
    if not common:
        raise NotComparable(
            "no test passed in the first run and ran again in the second, so nothing can be "
            "said about whether the patch broke anything"
        )

    raised: list[str] = []
    if finding_id:
        target = next(
            (finding for finding in before_validation.findings if finding.id == finding_id), None
        )
        if target is None:
            raise NotComparable(
                f"the before pass does not raise {finding_id}, the finding this fix was for, so "
                "there is nothing to look for in the after pass"
            )
        raised = still_raised(target, patch, after_validation.findings)

    return Reverification(
        before=snapshot_of(before_validation, before_tests, only=common),
        after=snapshot_of(after_validation, after_tests, only=common),
        before_run_id=before_run_id,
        after_run_id=after_run_id,
        finding_id=finding_id,
        still_raised_as=raised,
    )


def rollback_advice(result: Reverification) -> str:
    """What to tell a reader, from the arithmetic.

    Offered rather than taken. Rolling back automatically would make the
    pipeline decide something a person approved, and the whole component is
    built the other way round.
    """
    still = ", ".join(result.still_raised_as)
    if not result.worsened:
        if still:
            return (
                f"not verified: the finding it was for is still raised, as {still}, "
                "though nothing broke"
            )
        closed = result.findings_closed
        counted = f"{closed} finding{'s' if closed != 1 else ''} closed"
        if result.finding_closed:
            return f"keep: the finding it was for is gone, {counted} and no test broken"
        return (
            f"keep: {counted} and no test broken"
            if closed
            else "keep: nothing broke, though no finding closed either"
        )
    parts = []
    if result.tests_broken:
        parts.append(f"{result.tests_broken} test{'s' if result.tests_broken != 1 else ''} broke")
    if result.after.open_findings > result.before.open_findings:
        parts.append(
            f"open findings rose from {result.before.open_findings} to {result.after.open_findings}"
        )
    if still:
        parts.append(f"the finding it was for is still raised, as {still}")
    return "roll back offered: " + " and ".join(parts)
