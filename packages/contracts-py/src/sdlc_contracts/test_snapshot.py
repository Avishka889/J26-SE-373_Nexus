"""The testing phase snapshot: one payload the browser reads.

The same shape as the design and code snapshots, for the same reason: every
mutation answers with the whole phase, so the client never has to reconcile a
partial update against what it already had.

Three things about this phase make its snapshot different from the other two.

**Two upstream axes, not one.** The code phase watches the design version. This
phase watches the code version, because tests are run against a code version
and a report about version 3 says nothing about version 4. `testedCodeVersion`
is the version the artefacts were produced from, so "the code moved on" stays
arithmetic over two numbers rather than a flag somebody remembers to set.

**Refusals ride along with results.** The heal report carries repairs that were
refused, and the validation report carries findings whose evidence did not
resolve. Both are the component's most important rows and neither is an error,
so both reach the browser in the ordinary payload rather than through some
separate channel for problems.

**Bodies are absent, exactly as they are in the code snapshot.** A test report
carries every case and a validation report can carry thousands of findings, so
the heavy lists are counted here and served from their own routes. The client
polls this every 1.2 seconds while anything is running.
"""

from typing import Literal

from pydantic import Field, computed_field, model_validator

from .heal_report import HealReport
from .ids import TEST_STAGE_IDS, TestStageId
from .model_use import StageModelUse
from .remediation_proposal import RemediationProposals
from .run_status import RunStatus
from .snapshot import GateState
from .test_report import TestReport
from .validation_report import ValidationReport
from .wire import WireDatetime, WireModel

#: `skipped` is the one the other two phases do not have, and it exists because
#: this phase can be pointed at more than one kind of repository. Test
#: generation writes TypeScript from the contract, so on a Java target there is
#: nothing for it to write, and that is not a failure: failing the run there
#: means a Java repository can never reach the security stage at all. Skipping
#: is not failing and neither is it completing, so it says so.
TestStageStatus = Literal["pending", "generating", "complete", "failed", "skipped"]
TestThreadKind = Literal["user_note", "answer", "stage_summary", "system"]


class TestStageState(WireModel):
    """One stage of the testing phase, as the stepper renders it."""

    #: Not a pytest test class. The domain name is right and pytest's
    #: convention collides with it, so the model says so once here rather than
    #: every importing test module aliasing it.
    __test__ = False

    id: TestStageId
    status: TestStageStatus = "pending"
    #: The test version this stage ran at. Zero means never.
    generated_from_version: int = Field(default=0, ge=0)
    generated_at: WireDatetime | None = None
    summary: str | None = None
    error: str | None = None
    #: What answered this stage's current version, where it asked a model (0015).
    model_use: StageModelUse | None = None

    @model_validator(mode="after")
    def failure_says_why(self) -> "TestStageState":
        if self.status == "failed" and not self.error:
            raise ValueError(f"stage {self.id} failed without saying why")
        if self.status != "failed" and self.error:
            raise ValueError(f"stage {self.id} is {self.status} but carries an error")
        return self

    @model_validator(mode="after")
    def a_skip_says_why_too(self) -> "TestStageState":
        """In the summary, not the error, because nothing went wrong.

        A stage that did not apply and does not say so is indistinguishable
        from one that quietly did nothing, which is the failure mode this
        component is built to refuse everywhere else.
        """
        if self.status == "skipped" and not (self.summary or "").strip():
            raise ValueError(f"stage {self.id} was skipped without saying why")
        return self


class TestThreadMessage(WireModel):
    __test__ = False

    id: str = Field(min_length=1)
    kind: TestThreadKind
    stage_id: TestStageId | None = None
    author: str = Field(min_length=1)
    content: str = Field(min_length=1)
    at: WireDatetime
    #: The test version a change producing message opened. Null on the rest.
    produced_version: int | None = None


class HealDecision(WireModel):
    """What a person decided about one failing test, newest per test.

    About a repair the healing loop made: kept or reverted. The guard decides
    mechanically whether a repair may be accepted; this is the reader's verdict
    afterwards, a second fact about the same repair. It was recorded and never
    read back, so the page changed nothing on a decision.

    Or about a generated test that fails and that no repair will fix, which
    could otherwise block a release for good: quarantined (skipped, with the
    reason above it, until restored) or sent back to be written again (a test
    that never passed, back to a todo the next run fills).
    """

    test_id: str = Field(min_length=1)
    decision: Literal["kept", "reverted", "quarantined", "restored", "rewrite"]
    by: str = Field(min_length=1)
    at: WireDatetime
    note: str = ""


class TestAuditEntry(WireModel):
    """One entry in the audit log about this phase, as the report lists it."""

    __test__ = False

    actor: str = Field(min_length=1)
    action: str = Field(min_length=1)
    target: str = ""
    detail: str = ""
    at: WireDatetime


class FindingDecision(WireModel):
    """What a person decided about one security finding, newest per finding.

    Dismissed: it does not apply here, with a note saying why. Accepted: it is
    real, and with a note, the risk is taken knowingly, so the release gate lets
    it ship (G8). A decision was recorded and the page never read it back.
    """

    finding_id: str = Field(min_length=1)
    decision: Literal["accepted", "dismissed"]
    by: str = Field(min_length=1)
    at: WireDatetime
    note: str = ""


class FixShipsWith(WireModel):
    """Where a fix applied now lands, when that is newer code than may ship today.

    A fix patches the newest code version. When the newest approved tests
    measured an older one, the fix reaches production only together with the
    rest of the newer version, once its tests are approved: a fix to the older
    version alone is not offered, so code versions stay one line (review item
    C4-13).
    """

    #: The newest code version, which a fix applied now patches.
    code_version: int = Field(ge=1)
    #: The newest sprint any story in that build was planned in.
    sprint: int = Field(ge=1)
    #: The code version the newest approved tests measured: what may ship now.
    releasable_code_version: int = Field(ge=1)
    releasable_sprint: int = Field(ge=1)

    @model_validator(mode="after")
    def the_fix_goes_into_newer_code(self) -> "FixShipsWith":
        if self.code_version <= self.releasable_code_version:
            raise ValueError(
                f"code version {self.code_version} is not newer than code version "
                f"{self.releasable_code_version}, so a fix ships on its own"
            )
        return self


class TestSnapshot(WireModel):
    """Everything the testing workspace renders, in one read."""

    __test__ = False

    project_id: str = Field(min_length=1)
    #: This phase's own counter. Zero before the first run.
    test_version: int = Field(ge=0)
    #: The upstream axis, for the staleness fact.
    code_version: int = Field(ge=0)
    tested_code_version: int = Field(ge=0)
    #: Which repository the runs work on. `generated` is the application this
    #: project's code phase produced; `sample:<name>` is a checked in sample.
    #: On the snapshot because it changes what every number below is about: a
    #: coverage figure for the Java sample beside a test count for the
    #: generated app would be two facts about two programs in one panel.
    target: str = "generated"
    stages: dict[TestStageId, TestStageState]
    tests: TestReport | None = None
    heal: HealReport | None = None
    validation: ValidationReport | None = None
    remediation: RemediationProposals | None = None
    #: Where a fix applied now lands, when that is newer code than may ship
    #: today; None when a fix would ship on its own.
    fix_ships_with: FixShipsWith | None = None
    gate: GateState
    #: The phase's newest full run, so a run that stopped short of the review
    #: says so here rather than only in the audit log. None before any ran.
    run: RunStatus | None = None
    thread: list[TestThreadMessage] = Field(default_factory=list)
    #: The reader's decision on each repair at this test version, newest per test.
    heal_decisions: list[HealDecision] = Field(default_factory=list)
    #: The reader's decision on each security finding at this test version.
    finding_decisions: list[FindingDecision] = Field(default_factory=list)
    #: This phase's entries in the audit log, newest first: the report's audit
    #: section was the chat thread, which held few of the decisions.
    audit: list[TestAuditEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def every_stage_is_present(self) -> "TestSnapshot":
        """The client indexes `stages[id]` for all seven with no null guard."""
        missing = [stage for stage in TEST_STAGE_IDS if stage not in self.stages]
        if missing:
            raise ValueError(f"snapshot is missing stages: {', '.join(missing)}")
        return self

    @computed_field
    @property
    def code_moved_on(self) -> bool:
        """Whether the tests describe a version that is no longer current.

        Derived rather than stored. A green report about a code version two
        behind is the most misleading thing this phase can show, and a reader
        should be told by the payload rather than by noticing two numbers.
        """
        return self.tested_code_version > 0 and self.code_version > self.tested_code_version

    @computed_field
    @property
    def open_findings(self) -> int:
        return self.validation.open_findings if self.validation else 0

    @computed_field
    @property
    def refused_repairs(self) -> int:
        """Repairs the guard would not accept. The headline count of the
        component's contribution, so it is on the payload rather than behind a
        route the dashboard might not call."""
        return self.heal.refused if self.heal else 0

    @computed_field
    @property
    def awaiting_decision(self) -> int:
        return self.remediation.awaiting_decision if self.remediation else 0
