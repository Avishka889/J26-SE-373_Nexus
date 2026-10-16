"""A proposed fix, its risk, and what happened after somebody approved it.

C3 proposes and C2 applies. That split is the supervisor's rule and it is why
this artefact exists at all: the patch travels as data with an approval state
on it, rather than as an edit C3 makes and mentions afterwards. Everything a
person needs in order to sign it off is on the proposal, and everything that
happened afterwards is appended to it rather than replacing it.

The risk statement is counted, not adjectival. "This is low risk" is an opinion;
"three tests cover the two lines this changes, and no endpoint's contract
moves" is a claim a reader can check, and the counts that make it are carried
so they can be. The same discipline as C2's stack scoring, for the same reason:
a sentence with a number in it that nothing produced is the easiest thing in
this whole system for a model to invent.

Re-verification is a comparison, not a verdict. Findings and tests before,
findings and tests after, and the direction of travel derived from them: a fix
that closes one finding and breaks two tests should be visibly that, and the
rollback offer should follow from the numbers rather than from a judgement
somebody has to trust.
"""

import re
from collections.abc import Sequence
from typing import Literal

from pydantic import Field, computed_field, model_validator

from .tech_stack import CountedFact
from .validation_report import SecurityFinding
from .wire import Prose, WireDatetime, WireModel

#: The lifecycle. `dismissed` is terminal and carries a reason; `rolled-back`
#: means it was applied and re-verification made things worse.
ProposalState = Literal[
    "proposed",
    "dismissed",
    "accepted",
    "applied",
    "verified",
    "rolled-back",
]

RiskLevel = Literal["low", "medium", "high"]


class PatchHunk(WireModel):
    """One file's worth of the proposed change.

    Production code, unlike a heal's diff, because this is the other loop: a
    heal may only touch test code and a remediation may only touch the code the
    finding was about. The two are separate artefacts partly so that rule can
    be enforced separately.
    """

    path: str = Field(min_length=1)
    diff: str = Field(min_length=1)


class RiskAssessment(WireModel):
    """Why this change is as safe or as dangerous as it is claimed to be."""

    level: RiskLevel
    #: The sentence a reader sees. It may only restate the facts below.
    statement: Prose = Field(min_length=1)
    #: What the sentence rests on: files touched, lines changed, tests covering
    #: those lines, endpoints whose contract the change moves.
    facts: list[CountedFact] = Field(min_length=1)

    @model_validator(mode="after")
    def a_high_risk_change_says_what_makes_it_high(self) -> "RiskAssessment":
        if self.level == "high" and len(self.facts) < 2:
            raise ValueError("a high risk assessment rests on more than one number")
        return self


class VerificationSnapshot(WireModel):
    """The measurable state of the target at one moment."""

    open_findings: int = Field(ge=0)
    tests_passed: int = Field(ge=0)
    tests_failed: int = Field(ge=0)
    #: Null when mutation did not run in this pass, distinct from zero.
    mutation_score: float | None = Field(default=None, ge=0, le=100)


class Reverification(WireModel):
    """Before and after, and what the difference says.

    `worsened` is computed rather than asserted so that "re-verification
    passed" cannot be recorded over numbers that say otherwise. A fix that
    closes its finding while breaking a test has not passed, and the rollback
    offer is meant to follow from the arithmetic.
    """

    before: VerificationSnapshot
    after: VerificationSnapshot
    #: The run ids, so both halves can be re-read rather than trusted.
    before_run_id: str = ""
    after_run_id: str = ""
    #: The finding the fix was for, by the id the before pass gave it. Empty on
    #: a comparison recorded before it was looked for (review item C3-7).
    finding_id: str = ""
    #: The after pass's findings that are still that one (`still_raised`), by
    #: id, so a reader can open them. Empty when it is gone.
    still_raised_as: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def findings_closed(self) -> int:
        return max(0, self.before.open_findings - self.after.open_findings)

    @computed_field
    @property
    def tests_broken(self) -> int:
        return max(0, self.after.tests_failed - self.before.tests_failed)

    @computed_field
    @property
    def worsened(self) -> bool:
        return self.tests_broken > 0 or self.after.open_findings > self.before.open_findings

    @computed_field
    @property
    def finding_closed(self) -> bool:
        """Whether the finding the fix was for is gone. A comparison that never
        looked for it proves nothing about it, so that is not closed."""
        return bool(self.finding_id) and not self.still_raised_as

    @computed_field
    @property
    def verified(self) -> bool:
        """The fix closed its finding and made nothing worse. Totals alone
        called a fix verified with its own finding still raised (C3-7)."""
        return self.finding_closed and not self.worsened


class RemediationProposal(WireModel):
    id: str = Field(min_length=1)
    #: The finding this answers. Proposals exist only for findings whose
    #: evidence resolved, so this id always names something a reader can open.
    finding_id: str = Field(min_length=1)
    cwe: str = Field(pattern=r"^CWE-\d+$")
    generated_at: WireDatetime
    summary: Prose = Field(min_length=1)
    patch: list[PatchHunk] = Field(min_length=1)
    risk: RiskAssessment
    #: What the change is near, so a reviewer knows what to re-read.
    affected_endpoints: list[str] = Field(default_factory=list)
    affected_tests: list[str] = Field(default_factory=list)

    state: ProposalState = "proposed"
    decided_by: str = ""
    decided_at: WireDatetime | None = None
    #: Required to dismiss. A proposal thrown away without a reason is a
    #: decision nobody can review, and these are security findings.
    decision_note: str = ""

    #: The code version C2 produced when it applied this. Null until then, and
    #: the reason this artefact can say "applied" without C3 having edited
    #: anything itself.
    applied_code_version: int | None = Field(default=None, ge=1)
    reverification: Reverification | None = None

    @model_validator(mode="after")
    def a_dismissal_says_why(self) -> "RemediationProposal":
        if self.state == "dismissed" and not self.decision_note.strip():
            raise ValueError(f"{self.id}: dismissed without a reason")
        return self

    @model_validator(mode="after")
    def a_decision_names_its_author(self) -> "RemediationProposal":
        if self.state in ("accepted", "dismissed") and not self.decided_by.strip():
            raise ValueError(f"{self.id}: {self.state} by nobody")
        return self

    @model_validator(mode="after")
    def applied_means_a_version_to_point_at(self) -> "RemediationProposal":
        if (
            self.state in ("applied", "verified", "rolled-back")
            and self.applied_code_version is None
        ):
            raise ValueError(f"{self.id}: {self.state} without the code version that carries it")
        return self

    @model_validator(mode="after")
    def verified_means_it_was_measured(self) -> "RemediationProposal":
        if self.state != "verified":
            return self
        if self.reverification is None:
            raise ValueError(f"{self.id}: verified without a re-verification")
        if self.reverification.worsened:
            raise ValueError(f"{self.id}: verified over numbers that got worse")
        if self.reverification.finding_id != self.finding_id:
            raise ValueError(
                f"{self.id}: re-verified {self.reverification.finding_id or 'no finding'}, "
                f"not {self.finding_id}"
            )
        if not self.reverification.finding_closed:
            raise ValueError(f"{self.id}: verified while the finding it was for is still raised")
        return self

    @computed_field
    @property
    def awaiting_decision(self) -> bool:
        return self.state == "proposed"


class RemediationProposals(WireModel):
    """Every proposal one scan produced, as one stored artefact.

    The artefact kind is `remediation-proposal` because that is what it is
    about; the body is a set because a scan answers several findings at once
    and storing one artefact per proposal would put the version axis in a place
    it does not belong.
    """

    version: int = Field(ge=1)
    generated_at: WireDatetime
    target: str = Field(min_length=1)
    proposals: list[RemediationProposal] = Field(default_factory=list)

    @computed_field
    @property
    def awaiting_decision(self) -> int:
        return sum(1 for proposal in self.proposals if proposal.awaiting_decision)


#: `@@ -12,7 +12,8 @@`, the hunk header difflib writes, which writes every
#: patch in this system.
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def still_raised(
    finding: SecurityFinding, patch: Sequence[PatchHunk], after: Sequence[SecurityFinding]
) -> list[str]:
    """The after pass's findings that are still `finding`, by id.

    Still it means the same weakness class, in the same file, over the lines
    the patch left it on. Not the same id: an id names a line, and a fix that
    adds an import moves every line under it, so a finding the fix did not
    close came back under a new id and read as closed. The finding's lines are
    taken through the patch's own diff instead: lines a change removed go to
    where its added lines are, and every other line moves by what the changes
    above it added and removed. A dismissal is a person's decision, so a
    dismissed finding is not counted as raised.
    """
    blocks = sorted(
        block
        for hunk in patch
        if hunk.path == finding.evidence.path
        for block in _changes(hunk.diff)
    )
    start = _moved(finding.evidence.start_line, blocks)[0]
    end = _moved(finding.evidence.end_line, blocks)[1]
    return [
        other.id
        for other in after
        if other.cwe == finding.cwe
        and other.evidence.path == finding.evidence.path
        and other.status != "dismissed"
        and other.evidence.start_line <= end
        and start <= other.evidence.end_line
    ]


def _changes(diff: str) -> list[tuple[int, int, int, int]]:
    """Each change in a unified diff: old lines [a, b) became new lines [c, d).

    One per run of removed and added lines rather than per hunk, so the
    context around a change keeps its own place.
    """
    changes: list[tuple[int, int, int, int]] = []
    old = new = 0
    opened: tuple[int, int] | None = None
    in_hunk = False

    def close() -> None:
        nonlocal opened
        if opened is not None:
            changes.append((opened[0], old, opened[1], new))
            opened = None

    for line in diff.splitlines():
        header = _HUNK.match(line)
        if header:
            close()
            in_hunk = True
            # An empty range starts after the line it names.
            old = int(header[1]) + (1 if header[2] == "0" else 0)
            new = int(header[3]) + (1 if header[4] == "0" else 0)
            continue
        if not in_hunk or line.startswith("\\"):
            continue
        marker = line[:1]
        if marker in ("-", "+"):
            if opened is None:
                opened = (old, new)
            if marker == "-":
                old += 1
            else:
                new += 1
        else:
            close()
            old += 1
            new += 1
    close()
    return changes


def _moved(line: int, changes: list[tuple[int, int, int, int]]) -> tuple[int, int]:
    """Where one line of the old file is in the new: one line, or the lines a
    change put in its place, or the two either side of a change that only
    removed."""
    shift = 0
    for old_start, old_end, new_start, new_end in changes:
        if line < old_start:
            break
        if line < old_end:
            return (
                (new_start, new_end - 1)
                if new_end > new_start
                else (max(1, new_start - 1), new_start)
            )
        shift = new_end - old_end
    return line + shift, line + shift
