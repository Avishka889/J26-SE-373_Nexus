"""What the self healing loop did, and what it refused to do.

This is the component's headline contribution written down as a shape, so two
things about it are structural rather than conventional.

**A refusal is a row, not an error.** `HealAttempt` covers accepted and refused
alike, and the refusals carry their diff. A loop that reports only its
successes is measuring its own optimism: the published number that motivates
this component is 6 of 8 GPT-4 "successful" repairs being assertion weakening,
and those six are only visible if refusing produces evidence.

**Acceptance is the conjunction, and it is computed.** `accepted` is derived
from the three checks rather than stored, so nothing can be marked accepted
without them: the repair touched test code only, the healed test passes against
the production code it accused, and it still kills a mutant. Miss any one and
the value is False, whatever anybody writes.

The classification is the other half. A failing test is brittle or it is a real
regression, and healing a regression hides a bug, so the decision carries the
evidence that made it. The first signal is this platform's own traceability: a
test tracing to an artefact that changed between the two versions is a
brittleness candidate, one tracing only to unchanged artefacts is a regression
candidate, and the model referees only what remains and must cite the diff span
it relied on.
"""

from typing import Literal

from pydantic import Field, computed_field, model_validator

from .wire import Prose, WireDatetime, WireModel

Classification = Literal["brittle", "regression", "undecided"]

#: How the classification was reached. The trace based signals are the novel
#: ones and are named separately from the model's judgement so the evaluation
#: can report how often the rules alone sufficed.
ClassifiedBy = Literal["trace-changed", "trace-unchanged", "model-referee", "unclassified"]

#: Why a repair was refused. Every one of these is a way an LLM has been
#: observed to make a failing test pass without fixing anything, except the
#: last: `no-code-to-check` is the guard unable to ask its third question,
#: because it found no production code the test reaches. Refused, because a
#: guard fails closed, and never counted as a caught cheat, because nobody
#: cheated: it is the guard's limit, said as one.
RefusalReason = Literal[
    "touched-production-code",
    "assertion-weakened",
    "test-deleted",
    "still-failing",
    "kills-no-mutant",
    "no-repair-produced",
    "malformed-output",
    "no-code-to-check",
]


class ChangedCode(WireModel):
    """Production code that changed between the two tested code versions.

    One stretch of one file, as lines of the newer version. What the honesty
    guard breaks first: a repaired test has to notice a fault in the code whose
    change made it fail, so that is where the fault goes. Worked out by the
    orchestrator from the file store, with the tests left out, and handed to
    the healing stage beside the contract and requirement diffs.
    """

    path: str = Field(min_length=1)
    #: 1-based and inclusive, in the newer version of the file.
    start: int = Field(ge=1)
    end: int = Field(ge=1)

    @model_validator(mode="after")
    def a_stretch_runs_forwards(self) -> "ChangedCode":
        if self.end < self.start:
            raise ValueError(f"{self.path}: line {self.end} comes before line {self.start}")
        return self


class DiffSpan(WireModel):
    """The change, as a unified diff over test files only.

    Kept verbatim rather than summarised. A refusal whose diff is paraphrased
    cannot be audited, and the refused diffs are the evidence this component is
    judged on.
    """

    path: str = Field(min_length=1)
    diff: str = Field(min_length=1)


class ClassificationEvidence(WireModel):
    """Why this failure was called brittle or a regression.

    `changed_artefacts` is what the test traces to that moved between the two
    versions, and it is the whole argument when the rules decide alone. The
    referee's citation is required when the model decided, because a verdict
    that cannot point at a diff is a guess with a confident tone.
    """

    #: Requirement ids, endpoint ids and story ids the failing test traces to.
    traced_to: list[str] = Field(default_factory=list)
    #: Those of them that differ between the version the test was written
    #: against and the version it now runs against.
    changed_artefacts: list[str] = Field(default_factory=list)
    #: Where the referee looked, when a referee was needed.
    cited_diff_span: str = ""
    referee_reasoning: Prose = ""


class GuardCheck(WireModel):
    """One of the three conditions, with what was observed.

    `detail` is not optional prose. A guard that says False without saying what
    it saw cannot be argued with, and the point of the guard is that a person
    can check it.
    """

    name: Literal["test-code-only", "passes-unchanged-code", "kills-a-mutant"]
    passed: bool
    detail: str = Field(min_length=1)


class HealAttempt(WireModel):
    """One failing test, and what happened to it.

    Accepted and refused attempts share this shape deliberately: they are the
    same event with different outcomes, and separating them into two lists is
    how a refusal rate stops being reported.
    """

    test_id: str = Field(min_length=1)
    test_name: str = Field(min_length=1)
    suite_path: str = Field(min_length=1)
    #: What the run saw before anything was attempted.
    failure_message: str = Field(min_length=1)

    classification: Classification
    classified_by: ClassifiedBy
    evidence: ClassificationEvidence = Field(default_factory=ClassificationEvidence)

    #: Attempts the repair loop made before this outcome, C1's convention.
    attempts: int = Field(default=0, ge=0)
    #: The drafts the loop rejected on its way, kept for the evaluation's
    #: convergence numbers rather than discarded as noise.
    rejected_drafts: list[str] = Field(default_factory=list)

    diff: DiffSpan | None = None
    checks: list[GuardCheck] = Field(default_factory=list)
    refusal_reason: RefusalReason | None = None

    #: The run that proved the healed test passes the unchanged production
    #: code, and the mutants it killed. Named so the proof can be re-read.
    passed_on_unchanged_run_id: str = ""
    killed_mutant_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def a_regression_is_not_repaired(self) -> "HealAttempt":
        """Healing a regression hides a bug, so the shape forbids it.

        The loop flags regressions and moves on. A diff attached to one means
        the loop tried to repair a test that was telling the truth.
        """
        if self.classification == "regression" and self.diff is not None:
            raise ValueError(f"{self.test_id}: a regression was repaired rather than flagged")
        return self

    @model_validator(mode="after")
    def the_referee_cites_something(self) -> "HealAttempt":
        if self.classified_by == "model-referee" and not self.evidence.cited_diff_span.strip():
            raise ValueError(f"{self.test_id}: the referee decided without citing a diff span")
        return self

    @model_validator(mode="after")
    def a_refusal_names_its_reason(self) -> "HealAttempt":
        if not self.accepted and self.diff is not None and self.refusal_reason is None:
            raise ValueError(f"{self.test_id}: a repair was refused without a reason")
        return self

    @computed_field
    @property
    def accepted(self) -> bool:
        """All three checks, and a repair to apply them to.

        Computed rather than stored: acceptance is the conjunction of the
        guard's conditions, and a stored flag is a place for it to be set
        without them.
        """
        if self.diff is None or self.classification != "brittle":
            return False
        required = {"test-code-only", "passes-unchanged-code", "kills-a-mutant"}
        passing = {check.name for check in self.checks if check.passed}
        return required <= passing


class HealReport(WireModel):
    """One pass of the loop over one version's failures.

    Outlives the test report that produced it. A test report is replaced by the
    next run; a refused repair is evidence about how the model behaves, and the
    study reads it long after the suite has moved on.
    """

    version: int = Field(ge=1)
    generated_at: WireDatetime
    target: str = Field(min_length=1)
    #: The two versions the classification compares. Named, because the whole
    #: trace based signal is a statement about the difference between them.
    from_code_version: int = Field(ge=1)
    to_code_version: int = Field(ge=1)
    attempts: list[HealAttempt] = Field(default_factory=list)

    @model_validator(mode="after")
    def the_versions_move_forwards(self) -> "HealReport":
        if self.to_code_version <= self.from_code_version:
            raise ValueError("a heal compares a version against a later one")
        return self

    @computed_field
    @property
    def healed(self) -> int:
        return sum(1 for attempt in self.attempts if attempt.accepted)

    @computed_field
    @property
    def refused(self) -> int:
        return sum(1 for attempt in self.attempts if attempt.refusal_reason is not None)

    @computed_field
    @property
    def flagged_regressions(self) -> int:
        return sum(1 for attempt in self.attempts if attempt.classification == "regression")

    @computed_field
    @property
    def naive_convergence(self) -> float:
        """The number a loop without the guard would have reported.

        Every brittle test the model produced a repair for, whether or not the
        repair kept the test's power. Reported beside the strict rate because
        the gap between them is the guard's effect, and the gap is the result.
        """
        brittle = [a for a in self.attempts if a.classification == "brittle"]
        if not brittle:
            return 0.0
        produced = sum(1 for a in brittle if a.diff is not None)
        return round(produced / len(brittle) * 100, 2)

    @computed_field
    @property
    def strict_convergence(self) -> float:
        """The number this loop reports: repairs that cleared the guard."""
        brittle = [a for a in self.attempts if a.classification == "brittle"]
        if not brittle:
            return 0.0
        return round(sum(1 for a in brittle if a.accepted) / len(brittle) * 100, 2)
