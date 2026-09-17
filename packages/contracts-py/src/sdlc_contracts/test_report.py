"""What the tests did, and what that says about them.

Two disciplines run through this file and both come from C2's experience.

Every count is a `computed_field` over the cases rather than a stored number.
A stored total is a number that starts disagreeing with the thing it describes
the moment either changes, and the C1 dashboard had already conflated a pass
rate with a coverage percentage once. Computed fields are serialised, so the
frontend and the generated TypeScript still get them; they simply cannot be
authored, by a model or by anything else.

And an outcome is what happened, not what was hoped for. `not-run` is a first
class outcome, distinct from `skipped`: a framework skipping a test is a
decision the suite made, and a step never reaching a test is a decision the run
made, and reporting either as a pass is the failure this component exists to
prevent in others.
"""

from collections.abc import Collection, Mapping
from typing import Any, Literal

from pydantic import Field, computed_field, model_validator

from .ids import RequirementId, StoryId
from .wire import WireDatetime, WireModel

#: `skipped` is the framework's decision (a `.skip`, an unmet assumption).
#: `not-run` is the run's: the build failed, the step timed out, the suite
#: never got here. They are different facts and a reader acts on them
#: differently, so they are never collapsed.
TestOutcome = Literal["passed", "failed", "skipped", "errored", "not-run"]

#: Who wrote the test. The evaluation compares the arms, so this must survive
#: on every case rather than being inferred from a path later.
#:
#: `upstream` is everything this component did not write: a human's test, and
#: also the per endpoint tests the code generator ships with the repository.
#: Those are the baseline the arms are measured against, and calling them hand
#: written would have said something false about who wrote them.
TestOrigin = Literal["upstream", "skeleton", "filled", "healed"]

#: What a case exercises. The unit that matters is the acceptance criterion,
#: because that is what C1 wrote and what the reader recognises.
#:
#: `api` is a contract test of one endpoint. `acceptance` is an acceptance
#: criterion exercised through the HTTP API, with the app in process on its
#: in-memory store. `integration` is kept for a test against a real
#: collaborator, a database above all: nothing generated here is one, and the
#: acceptance tests carried this name until 2026-10-11 without touching one.
TestKind = Literal["unit", "api", "acceptance", "integration", "regression"]


class TestTrace(WireModel):
    """What this test was written from. Every reference is an id, never a position.

    This carried a `criterionIndex` into the story's `acceptance` list until
    2026-09-26, on the reasoning that criteria had no ids of their own and
    inventing them here would be a second source of truth for something C1 owns.
    C1 owns them now and they survive a regeneration, so the index was the last
    positional reference left in a trace, and it had the defect every positional
    reference across versions has: a criterion inserted ahead of another moves
    what index 0 names, so a test written at one design version traces to a
    different criterion at the next.

    The index is dropped rather than kept alongside the id. Two references to the
    same thing is how the two start disagreeing, which is the argument every
    count in this file is computed for, and a reader wanting the position can
    take it from the story's own list.
    """

    #: Not a pytest test class. The domain name is right and pytest's
    #: convention collides with it, so the model says so once here rather than
    #: every importing test module aliasing it.
    __test__ = False

    story_id: StoryId | None = None
    #: The acceptance criterion this exists for, by C1's id for it. No pattern:
    #: a trace must not be stricter about an id than the artefact that issues it.
    criterion_id: str = ""
    requirement_ids: list[RequirementId] = Field(default_factory=list)
    #: The api-contract endpoints this exercises.
    #:
    #: A list because a criterion test is written for a story, and a story can be
    #: served by several endpoints. It was a single string while only the oracle
    #: tests filled it in, one endpoint each, and a criterion test carried none
    #: at all. That cost the classifier half its signal on every test this
    #: component writes from a criterion: `diff_contracts` is one of its two
    #: inputs and had nothing to match against, so a criterion test broken by
    #: the API moving under it could only ever be read through the requirement
    #: diff.
    endpoint_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _drop_the_positional_criterion(cls, data: Any) -> Any:
        """Let a report stored before 2026-09-26 still be read.

        `extra="forbid"` would otherwise refuse the whole artefact over a key
        this contract used to declare, and a project would stop opening. The
        index is dropped rather than converted, because converting it needs the
        sprint plan the test was written against and the answer would be a guess
        at exactly the thing that turned out not to be reliable. So an older
        report loads with no criterion in its trace, which is true: it recorded
        a position and this platform no longer trusts one.
        """
        if not isinstance(data, dict):
            return data
        data = {key: value for key, value in data.items() if key != "criterionIndex"}
        if "endpointId" in data:
            # Migrated rather than dropped, because unlike the index this one
            # converts without guessing: one endpoint is a list of one.
            single = data.pop("endpointId")
            data.setdefault("endpointIds", [single] if single else [])
        return data

    @property
    def is_empty(self) -> bool:
        return not (self.story_id or self.criterion_id or self.requirement_ids or self.endpoint_ids)


class TestCase(WireModel):
    #: Not a pytest test class. The domain name is right and pytest's
    #: convention collides with it, so the model says so once here rather than
    #: every importing test module aliasing it.
    __test__ = False

    id: str = Field(min_length=1)
    #: As the framework reports it, so a reader can find it by searching.
    name: str = Field(min_length=1)
    outcome: TestOutcome
    kind: TestKind = "unit"
    origin: TestOrigin = "skeleton"
    duration_seconds: float = Field(default=0.0, ge=0)
    #: The failure or error as it was reported. Empty on a pass.
    message: str = ""
    traces: TestTrace = Field(default_factory=TestTrace)
    #: The test version that first ran this case. A case carried from an earlier
    #: version keeps the version it was first run at, so the review can tell
    #: what this version added from the regression suite it carried forward.
    #: 0 when it is not known: a report stored before this was recorded.
    since_version: int = Field(default=0, ge=0)
    #: Why this case no longer tests the build, when it does not: its story has
    #: left the build, or its criterion has left its story. It still runs and
    #: still counts. Empty while it tests the build.
    obsolete: str = ""

    @model_validator(mode="after")
    def a_failure_says_what_happened(self) -> "TestCase":
        if self.outcome in ("failed", "errored") and not self.message.strip():
            raise ValueError(f"{self.id} {self.outcome} without a message")
        return self


class TestSuite(WireModel):
    """One test file, and what its cases did."""

    #: Not a pytest test class. The domain name is right and pytest's
    #: convention collides with it, so the model says so once here rather than
    #: every importing test module aliasing it.
    __test__ = False

    path: str = Field(min_length=1)
    #: "vitest", "junit5". Free text: a third runner should not need a schema
    #: change to be reported honestly.
    framework: str = Field(min_length=1)
    cases: list[TestCase] = Field(default_factory=list)

    @computed_field
    @property
    def passed(self) -> int:
        return sum(1 for case in self.cases if case.outcome == "passed")

    @computed_field
    @property
    def failed(self) -> int:
        return sum(1 for case in self.cases if case.outcome in ("failed", "errored"))


class CoverageEntry(WireModel):
    """Coverage for one module, with the raw counts kept.

    Percentages are derived here rather than stored for the same reason the
    totals are: a percentage without its numerator cannot be added to another
    one, and the evaluation adds them.
    """

    module: str = Field(min_length=1)
    lines_covered: int = Field(ge=0)
    lines_total: int = Field(ge=0)
    branches_covered: int = Field(default=0, ge=0)
    branches_total: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def covered_within_total(self) -> "CoverageEntry":
        if self.lines_covered > self.lines_total:
            raise ValueError(f"{self.module}: more lines covered than exist")
        if self.branches_covered > self.branches_total:
            raise ValueError(f"{self.module}: more branches covered than exist")
        return self

    @computed_field
    @property
    def line_percent(self) -> float:
        return round(self.lines_covered / self.lines_total * 100, 2) if self.lines_total else 0.0

    @computed_field
    @property
    def branch_percent(self) -> float:
        if not self.branches_total:
            return 0.0
        return round(self.branches_covered / self.branches_total * 100, 2)


class UnmeasuredApp(WireModel):
    """An app in the mutation scope that gave no score, and why.

    Each app is mutated on its own, as its suite runs, so one can score while
    another does not. The score is over the apps that did, and this names the
    rest: until 2026-10-09 every mutant was made in the first scoped file's app,
    and the other app was never mutated at all (review item C3-6).
    """

    app: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class MutationResult(WireModel):
    """Which mutants died, and which lived to tell the reader something.

    `scope` is not decoration. Mutation is run over named files rather than the
    whole workspace, both because this machine cannot afford the whole
    workspace and because the honesty guard only wants mutants in the region a
    test exercises. A mutation score means nothing without the set it was
    measured over, so the set travels with the score.

    Survivors are listed rather than counted. A survived mutant is a piece of
    behaviour no test noticed, which is the actionable half of the result, and
    counting it loses the address.
    """

    tool: str = Field(min_length=1)
    scope: list[str] = Field(min_length=1)
    killed: list[str] = Field(default_factory=list)
    survived: list[str] = Field(default_factory=list)
    #: Mutants the runner could not decide: a timeout, a compile error in the
    #: mutated form. Neither killed nor survived, and never quietly either.
    inconclusive: list[str] = Field(default_factory=list)
    duration_seconds: float = Field(default=0.0, ge=0)
    #: The apps in scope that gave no score; `scope` is only the files that did.
    not_measured: list[UnmeasuredApp] = Field(default_factory=list)

    @computed_field
    @property
    def total(self) -> int:
        return len(self.killed) + len(self.survived) + len(self.inconclusive)

    @computed_field
    @property
    def score(self) -> float:
        """Killed over killed plus survived, as every mutation tool defines it.

        Inconclusive mutants are excluded from the denominator rather than
        counted as survivors, because a mutant that could not be evaluated is
        not evidence that a test missed it.
        """
        decided = len(self.killed) + len(self.survived)
        return round(len(self.killed) / decided * 100, 2) if decided else 0.0


#: What is wrong with a test, as a stable id the evaluation can count.
#: Reader facing: each names a habit, not a line number, because the fix is
#: always the same shape wherever it appears.
QualityRule = Literal[
    "no-assertion",
    "vacuous-assertion",
    "focused",
    "sleep",
    "unseeded-randomness",
    "wall-clock",
    "network",
    "order-dependent",
    "kills-no-mutant",
]


class QualityFinding(WireModel):
    """One thing wrong with one test, said the way a reviewer would say it.

    Findings about tests, not about the code under test: a suite can be green
    and still be worth nothing, and the three most common reasons are a test
    that asserts nothing, a test that only passes when it runs first, and a
    test that runs the code and would not notice if it changed. None of them
    shows up in a pass rate, which is why they are reported separately rather
    than folded into one.

    `kills-no-mutant` is the strongest of the three and the only one that needs
    a mutation run to see. It is named for the observation rather than for the
    author: the same fact about a test a model wrote is a weak fill, and about
    a test that came with the repository it is a gap the repository already
    had. The report counts them per origin so the two stay distinguishable.
    """

    rule: QualityRule
    path: str = Field(min_length=1)
    #: The test's name, or empty when the finding is about the whole file.
    test: str = ""
    detail: str = Field(min_length=1)
    #: Whether a run had to happen to find it. Order dependence cannot be seen
    #: by reading, and the distinction matters to a reader deciding how much to
    #: trust the list.
    observed: bool = False


class ToolStep(WireModel):
    """One command the harness ran, and what it did.

    The same shape as C2's build steps, and for the same reason: a reader who
    is told the tests failed needs to know whether they failed or never ran.
    """

    name: str = Field(min_length=1)
    command: str = Field(min_length=1)
    outcome: Literal["passed", "failed", "not-run", "timed-out"]
    duration_seconds: float = Field(default=0.0, ge=0)
    log_tail: str = ""


class TestGap(WireModel):
    """A contract obligation no test can assert, and why.

    Not a failing test and not an unwritten one. The contract restricts an
    operation to a role and the application has no sign-in, or declares an
    operation on a record nothing can create: a test asserting the obligation
    would fail for ever and say the wrong thing, since the fault is an absent
    feature. So it is named here, on the report, where the page that says what
    was generated can say what was not.
    """

    __test__ = False

    endpoint_id: str = Field(min_length=1)
    #: What stands in the way, as the generator names it: `no-way-to-create`,
    #: `validation-not-enforced`, `auth-not-implemented`.
    kind: str = Field(min_length=1)
    detail: str = Field(min_length=1)


class TestReport(WireModel):
    """One execution of one target's tests.

    Replaced by the next run rather than accumulated: a heal report outlives
    it, and the evaluation reads the stamped copies rather than this one.
    """

    #: Not a pytest test class. The domain name is right and pytest's
    #: convention collides with it, so the model says so once here rather than
    #: every importing test module aliasing it.
    __test__ = False

    version: int = Field(ge=1)
    generated_at: WireDatetime
    #: Which repository this ran against: the generated monorepo, the Spring
    #: sample, a benchmark checkout. Named so a number can never be attributed
    #: to the wrong target.
    target: str = Field(min_length=1)
    #: How the sandbox isolated the run, stated in words, as C2's build report
    #: states it. This machine has no container for it, and the report says so
    #: rather than implying one.
    isolation: str = Field(min_length=1)
    steps: list[ToolStep] = Field(default_factory=list)
    suites: list[TestSuite] = Field(default_factory=list)
    coverage: list[CoverageEntry] = Field(default_factory=list)
    mutation: MutationResult | None = None
    #: What is wrong with the tests themselves. A green suite with findings in
    #: it is the case this list exists for.
    quality: list[QualityFinding] = Field(default_factory=list)
    #: Why mutation did not run, when it did not. Required in that case: an
    #: absent mutation score with no reason reads as a score of zero.
    mutation_skipped_reason: str = ""
    #: What the contract obliges and no test can assert. Written by the
    #: generation stage, which is the only one that knows, and kept by the
    #: stages that replace the report after it (`with_traces_from`).
    gaps: list[TestGap] = Field(default_factory=list)

    @model_validator(mode="after")
    def an_absent_mutation_run_says_why(self) -> "TestReport":
        if self.mutation is None and not self.mutation_skipped_reason.strip():
            raise ValueError("mutation did not run and the report does not say why")
        if self.mutation is not None and self.mutation_skipped_reason:
            raise ValueError("mutation ran, so it cannot also carry a skip reason")
        return self

    @property
    def cases(self) -> list[TestCase]:
        return [case for suite in self.suites for case in suite.cases]

    @computed_field
    @property
    def total(self) -> int:
        return len(self.cases)

    @computed_field
    @property
    def passed(self) -> int:
        return sum(1 for case in self.cases if case.outcome == "passed")

    @computed_field
    @property
    def failed(self) -> int:
        return sum(1 for case in self.cases if case.outcome in ("failed", "errored"))

    @computed_field
    @property
    def skipped(self) -> int:
        return sum(1 for case in self.cases if case.outcome == "skipped")

    @computed_field
    @property
    def not_run(self) -> int:
        return sum(1 for case in self.cases if case.outcome == "not-run")

    @computed_field
    @property
    def untraced(self) -> int:
        """Tests this component wrote that say nothing about what they came from.

        The self healing classifier's first signal is what a failing test traces
        to, so a report full of untraced cases is a report the classifier can say
        nothing about: every failure comes back `undecided`, which reads like
        caution and is actually an absence of evidence.

        It was exactly that, silently, until 2026-09-26. The generation stage
        wrote the traces and the run stage replaced its report with one built from
        the runner's output, which knows nothing about stories or criteria, so
        every executed failure reached the classifier with an empty trace. The
        loop was never wrong; it just could not answer. A derived count makes that
        state loud rather than invisible, which is the whole reason it is here.

        `upstream` cases are excluded and their absence of a trace is not a
        defect: they came with the repository and were not written from an
        artefact, so there is nothing for them to point at. Counting them would
        make this number describe the target rather than the platform.
        """
        return sum(1 for case in self.cases if case.origin != "upstream" and case.traces.is_empty)

    @computed_field
    @property
    def line_coverage(self) -> float:
        """Weighted by lines, not the mean of the per module percentages.

        Averaging percentages weights a ten line module the same as a thousand
        line one, which is how a coverage number ends up describing nothing.
        """
        total = sum(entry.lines_total for entry in self.coverage)
        covered = sum(entry.lines_covered for entry in self.coverage)
        return round(covered / total * 100, 2) if total else 0.0

    @computed_field
    @property
    def branch_coverage(self) -> float:
        total = sum(entry.branches_total for entry in self.coverage)
        covered = sum(entry.branches_covered for entry in self.coverage)
        return round(covered / total * 100, 2) if total else 0.0


def with_traces_from(executed: TestReport, declared: TestReport) -> TestReport:
    """Put back the traceability a test runner has no way to know.

    Two reports describe the same tests. The generation stage's says what each
    test was written from, because the rules that wrote it knew; the run stage's
    says what each test did, because the runner reported it. Neither is complete
    on its own, and the run stage used to replace the first with the second at the
    same artefact version, so the traces were not merely absent from the result,
    they were destroyed.

    That silently disabled the self healing classifier on every real run. Its
    first signal is what a failing test traces to, and an empty trace is an
    honest `undecided` rather than a wrong answer, so nothing failed and nothing
    said anything: the loop reported that it could not classify what it was given
    and the reason was one stage overwriting another's work.

    Matched on the case id, which both sides build as `path::fullName` from the
    same convention, deliberately, so a declared case and the executed case it
    became are the same string. A case the declaration does not know about keeps
    its empty trace rather than being given a neighbour's, which is what upstream
    tests are: they came with the repository and were written from nothing this
    platform holds. Nothing is added and nothing is dropped, because what ran is
    the executed report's to say and inventing a case here would be the same
    mistake in the other direction.
    """
    known = {case.id: case for case in declared.cases}
    # What no test can assert is the generator's to say as well, and a runner
    # has no way to know it: kept whether or not any case was declared.
    if not known:
        return executed.model_copy(update={"gaps": declared.gaps})

    def kept(case: TestCase) -> TestCase:
        declared_case = known.get(case.id)
        if declared_case is None:
            return case
        # Where it stands is the declaration's to say too: the runner cannot know
        # which version first ran a test, or whether its criterion is still planned.
        # Nor what kind of test it is. Every case a runner returned was "unit",
        # so after the run no test was an API test, and the two places that
        # refuse to keep a repair to one, or have one written again, by asking
        # the report its kind, had stopped refusing.
        update: dict[str, Any] = {
            "kind": declared_case.kind,
            "since_version": declared_case.since_version,
            "obsolete": declared_case.obsolete,
        }
        if not declared_case.traces.is_empty:
            update["traces"] = declared_case.traces
        return case.model_copy(update=update)

    return executed.model_copy(
        update={
            "gaps": declared.gaps,
            "suites": [
                suite.model_copy(update={"cases": [kept(case) for case in suite.cases]})
                for suite in executed.suites
            ],
        }
    )


def with_standing(
    report: TestReport,
    *,
    previous: TestReport | None,
    criteria: Mapping[str, Collection[str]],
) -> TestReport:
    """Each case, with the version that first ran it and whether it still tests the build.

    The test review could not tell this version's new tests from the regression
    suite carried forward, and a test whose criterion had left the plan passed as
    if it still tested the build (review item C3-10).

    `previous` is the report of the test version before this one. A case it ran
    (matched on the id, `path::fullName`, as `with_traces_from` matches) is
    carried, and keeps the version it was first run at, or that report's version
    when it was stored before this was recorded. Any other case is new here.

    `criteria` is the build's stories, each with its acceptance criteria. A case
    this platform wrote that traces a story not among them, or a criterion its
    story no longer has, still runs and still counts, and says why it no longer
    tests the build. A test that came with the repository traces nothing this
    platform planned, so it is never called obsolete.
    """
    earlier = {case.id: case for case in previous.cases} if previous else {}

    def stood(case: TestCase) -> TestCase:
        before = earlier.get(case.id)
        if before is not None and previous is not None:
            since = before.since_version or previous.version
        else:
            since = report.version
        return case.model_copy(
            update={"since_version": since, "obsolete": _obsolete(case, criteria)}
        )

    return report.model_copy(
        update={
            "suites": [
                suite.model_copy(update={"cases": [stood(case) for case in suite.cases]})
                for suite in report.suites
            ]
        }
    )


def _obsolete(case: TestCase, criteria: Mapping[str, Collection[str]]) -> str:
    story, criterion = case.traces.story_id, case.traces.criterion_id
    if case.origin == "upstream" or not story:
        return ""
    if story not in criteria:
        return f"{story} is no longer in the build"
    if criterion and criterion not in criteria[story]:
        return f"{criterion} is no longer one of {story}'s acceptance criteria"
    return ""
