"""The static contract agreement report: validation before execution.

The novelty this artefact carries: the generated frontend and backend are
checked against the contract by parsing what was generated, before anything
runs. Findings carry real file and line locations, and the counts are what the
evaluation reports, so nothing here may be invented or approximated.
"""

from typing import Literal

from pydantic import Field, model_validator

from .wire import WireModel

AgreementSeverity = Literal["error", "warning"]


class CodeLocation(WireModel):
    path: str = Field(min_length=1)
    #: 1 indexed. None when the finding is about a file's absence.
    line: int | None = Field(default=None, ge=1)


class AgreementFinding(WireModel):
    rule_id: str = Field(min_length=1)
    severity: AgreementSeverity
    #: Written for the person deciding at the gate.
    reason: str = Field(min_length=1)
    #: Written for the model on a regeneration, C1's repair loop convention.
    hint: str = ""
    #: What the finding is about: an endpoint id, a path, a method name.
    subject: str = ""
    location: CodeLocation | None = None


class AgreementCounts(WireModel):
    endpoints_total: int = Field(ge=0)
    endpoints_implemented: int = Field(ge=0)
    endpoints_missing: list[str] = Field(default_factory=list)
    endpoints_called: int = Field(ge=0)
    endpoints_unused: list[str] = Field(default_factory=list)
    #: Routes the backend serves that the contract never declared.
    orphan_routes: list[str] = Field(default_factory=list)
    #: Frontend requests that bypass the generated client.
    foreign_calls: list[str] = Field(default_factory=list)
    schema_mismatches: int = Field(default=0, ge=0)
    #: implemented over total. 1.0 when every contract endpoint is served.
    agreement_rate: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def the_lists_and_the_numbers_agree(self) -> "AgreementCounts":
        if self.endpoints_total - self.endpoints_implemented != len(self.endpoints_missing):
            raise ValueError("implemented plus missing must account for every endpoint")
        return self


class ContractAgreement(WireModel):
    contract_version: int = Field(ge=1)
    findings: list[AgreementFinding] = Field(default_factory=list)
    counts: AgreementCounts

    @property
    def errors(self) -> list[AgreementFinding]:
        return [finding for finding in self.findings if finding.severity == "error"]
