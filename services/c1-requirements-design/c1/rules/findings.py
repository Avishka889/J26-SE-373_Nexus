"""What a rule says when it fires, for the three audiences that read it.

Shared by every rule catalogue in C1 rather than defined once per artefact. The
evaluation counts findings across all of them and reports one consistency rate,
so two near-identical finding types would eventually disagree about what
"severity" means and the number would stop being comparable.

Every finding carries three sentences for three readers:

    rule_id   the evaluation, which counts them
    reason    the person reading the design, in plain words
    hint      the model, on the next attempt of the repair loop

The hint earns its place. "Screen s4 has no way out and is not a confirmation;
add a link back to s1 or rename it" gets a useful second attempt, where "invalid
flow" gets the same answer again.

Errors block: an artefact carrying one is not promoted to the strict contract
type. Warnings inform: a gap worth showing a reader is not a reason to refuse the
whole artefact and show them nothing.
"""

from dataclasses import dataclass, field
from typing import Literal

from sdlc_contracts import DesignStageId, ValidationFinding

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class Finding:
    """One rule, one subject, one sentence for each audience."""

    rule_id: str
    severity: Severity
    #: Written for the person reading the design.
    reason: str
    #: Written for the model, on the next attempt.
    hint: str
    #: The thing this is about, or None when it concerns the whole artefact.
    subject: str | None = None
    #: The requirements this concerns, so the warning links somewhere useful.
    traces: tuple[str, ...] = field(default=())
    #: The stage a reader should go and look at. Left unset by the rules that run
    #: inside one artefact, because the reader is already there. The checks that
    #: compare artefacts set it, since "a must-have has no story" is read at the
    #: gate and fixed somewhere else.
    stage_id: DesignStageId | None = None

    def to_contract(self) -> ValidationFinding:
        """The finding as the frontend renders it."""
        return ValidationFinding(
            ruleId=self.rule_id,
            reason=self.reason,
            traces=list(self.traces),
        )


@dataclass(frozen=True)
class Report:
    findings: tuple[Finding, ...] = field(default=())

    @property
    def errors(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity == "error")

    @property
    def warnings(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity == "warning")

    @property
    def ok(self) -> bool:
        return not self.errors

    def for_subject(self, subject: str) -> Finding | None:
        """The finding a subject carries, if any. Errors first, then warnings."""
        mine = [f for f in self.findings if f.subject == subject]
        if not mine:
            return None
        mine.sort(key=lambda f: 0 if f.severity == "error" else 1)
        return mine[0]

    def hints(self) -> str:
        """Every error as instructions for the next attempt."""
        return "\n".join(f"- {finding.hint}" for finding in self.errors)

    def rule_ids(self) -> tuple[str, ...]:
        return tuple(sorted({finding.rule_id for finding in self.findings}))
