"""The finding a rule produces, shared by every C2 catalogue.

A structural twin of c1/rules/findings.py, kept in step by convention rather
than import: services depend only on the contracts package, never on each
other. Three audiences, same as there: `rule_id` for the evaluation, `reason`
for the person, `hint` for the model on the next attempt.
"""

from dataclasses import dataclass
from typing import Literal

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: Severity
    #: Plain words for the reader: what is wrong and where.
    reason: str
    #: Written for the repair loop: what to change, imperative, specific.
    hint: str
    #: What the finding is about: an endpoint id, a screen id, a path.
    subject: str = ""
    traces: tuple[str, ...] = ()


@dataclass(frozen=True)
class Report:
    findings: tuple[Finding, ...] = ()

    @property
    def errors(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity == "error")

    @property
    def warnings(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity == "warning")

    @property
    def ok(self) -> bool:
        return not self.errors

    def hints(self) -> str:
        """What travels back to the model: the hints, not the reasons."""
        return "\n".join(f"- {finding.hint}" for finding in self.errors)

    def rule_ids(self) -> tuple[str, ...]:
        return tuple(sorted({finding.rule_id for finding in self.errors}))


def report(findings: list[Finding]) -> Report:
    return Report(findings=tuple(findings))
