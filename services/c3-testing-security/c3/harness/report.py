"""What a lane produces, and who wrote each test in it.

Both lanes answer the same shape, so it lives here rather than in whichever of
them happened to be written first.

Attribution is the other half. A mutation run says which mutants died; what a
reader needs is which test killed them, because that is what turns a score into
a statement about a particular test. Both runners can say, once they are asked
not to stop at the first kill.

The provenance question is the one that matters for the evaluation. A generated
repository arrives with tests already in it: the code generator ships one per
endpoint. Anything this component adds sits beside those, and the whole point
of the comparison is the difference between them, so a case has to remember who
wrote it rather than having it guessed from a path afterwards. `origin_of`
answers that from the manifest of what this component wrote, and everything not
in that manifest is upstream, which is the honest default: not knowing who
wrote a test is not the same as having written it.
"""

from dataclasses import dataclass, field

from sdlc_contracts import CoverageEntry, TestSuite

from .sandbox import StepResult

#: Suite path to the arm that wrote it. What this component generated in this
#: run, and nothing else.
Authored = dict[str, str]


@dataclass(frozen=True)
class TestKills:
    """What one test did to the mutants it covered.

    The question a pass rate cannot answer: this test ran that code, would it
    have noticed if the code were wrong? A test that covers mutants and kills
    none is running the code and watching nothing, which is the same hole the
    honesty guard closes at repair time, seen at the other end.

    Ids rather than counts, because the next thing anybody wants is which
    mutant survived: a reader wants to look at it, and a refill has nothing to
    act on without it.
    """

    #: Not a pytest test class. The domain name is right and pytest's
    #: convention collides with it, as it does with the contract's own test
    #: models, so the class says so once here.
    __test__ = False

    covered: tuple[str, ...] = ()
    killed: tuple[str, ...] = ()

    @property
    def weak(self) -> bool:
        """Covered something and killed nothing.

        Covering nothing is not weak, it is unmeasured: the mutation run is
        scoped, and a test exercising code outside that scope was never asked
        the question.
        """
        return bool(self.covered) and not self.killed


#: Test id to what it did. The ids are the report's own case ids, so a finding
#: can name the test a reader is looking at rather than a runner's internal
#: numbering.
Attribution = dict[str, TestKills]


@dataclass(frozen=True)
class MutationOutcome:
    """What a mutation pass produced, including who killed what.

    A tuple would do for the first three and did, until attribution made it a
    fourth. Exactly one of `result` and `skipped_reason` is ever set: an absent
    score with no reason reads as a score of zero, which is the thing this
    component refuses to let a report say.
    """

    step: StepResult
    result: object | None = None
    skipped_reason: str = ""
    attribution: Attribution = field(default_factory=dict)
    #: Every step the pass took, one per app where there are several; `step`
    #: is the first. Empty means `step` is the only one.
    steps: list[StepResult] = field(default_factory=list)


def origin_of(path: str, authored: Authored | None) -> str:
    return (authored or {}).get(path, "upstream")


def case_id(path: str, describe: str, name: str) -> str:
    """The one id a test has, whoever is naming it.

    Three places name the same test and they have to agree, because that string
    is the only join between them: the generator, which writes the test and knows
    what it was written from; the runner's report, which knows what it did; and
    Stryker's attribution, which knows which mutants it killed. Vitest reports a
    test as its `describe` and its `it` joined by a single space, in `fullName`,
    and Stryker names it the same way, so that is the convention and this is the
    only place that spells it.

    Worth a function rather than an f-string per site. The generators wrote
    `describe > name` and the runner wrote `describe name`, so no declared case
    ever matched the case it became. Nothing failed: the traces the generator
    wrote simply never reached the executed report, and the healing classifier
    answered `undecided` on every real failure for want of them.
    """
    # Joined on the parts that exist, so a test written outside any `describe`
    # is not given a leading space it does not have in the runner's own report.
    return f"{path}::{' '.join(part for part in (describe.strip(), name.strip()) if part)}"


@dataclass
class LaneRun:
    """What one execution of the suite produced."""

    steps: list[StepResult] = field(default_factory=list)
    suites: list[TestSuite] = field(default_factory=list)
    coverage: list[CoverageEntry] = field(default_factory=list)

    @property
    def ran(self) -> bool:
        """Whether the runner actually reported on tests.

        Not whether they passed. A red suite is a result; a suite that never
        started is not, and only the second one makes the report a lie.
        """
        return bool(self.suites)

    @property
    def green(self) -> bool:
        """Whether every test that ran passed, and some did.

        The `and some did` is the whole point. `all()` over an empty list is
        true, so a run that never started reads as a clean suite, and the first
        thing that happens to a clean suite here is a mutation pass measuring
        nothing. This was not hypothetical: the Java lane's first end to end
        run could not find its wrapper, reported no suites, and was called
        green by the caller two lines later.
        """
        if not self.ran:
            return False
        return not any(
            case.outcome in ("failed", "errored") for suite in self.suites for case in suite.cases
        )
