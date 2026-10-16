"""The C3 to C4 seam: what was found, how bad it is, and who signed it off.

Three rules are enforced here by shape rather than by discipline, because each
one is a documented way this kind of report goes wrong.

**Severity is arithmetic.** `base_score` is computed from the CVSS v3.1 base
metrics and `severity` from the score, so neither can be authored. The
alternative is a model estimating severity, and the measured behaviour of that
is 59.7% accuracy with seven of nine models *under*estimating: an optimistic
bias in exactly the direction that gets a vulnerability shipped. The LLM names
the weakness and writes the remediation; it never scores.

**Evidence resolves or the finding is not a finding.** A finding carries a file
and a line span, and a span that does not resolve in the repository moves to
`refused_evidence` with its reason and is counted there. Counted, not dropped:
the refusal rate of an arm is a result about that arm, and a fabricated
location silently discarded is a detector flattered by its own errors.

**Confidence is never written by the detector that raised the finding.** There
is no `llm` or `trained` option for `confidence_source`, so the question cannot
arise: confidence comes from agreement between arms, or from a scanner rule's
own precision, or from a calibrated threshold.
"""

from math import floor
from typing import Literal

from pydantic import Field, computed_field, model_validator

from .wire import Prose, WireDatetime, WireModel

#: Which arm raised it. `merged` means more than one did, which is the
#: ensemble's own finding and is kept distinct from either arm alone so the
#: three way comparison can count them separately.
FindingOrigin = Literal["scanner", "llm", "trained", "merged"]

#: Where a confidence number came from. Deliberately without a model option.
ConfidenceSource = Literal["arm-agreement", "scanner-rule", "calibration"]

Severity = Literal["none", "low", "medium", "high", "critical"]

FindingStatus = Literal["open", "dismissed", "fix-proposed", "re-verifying", "verified"]


class EvidenceSpan(WireModel):
    """Where in the repository the finding is, precisely enough to check.

    A span rather than a line, because a taint finding is a flow and a reader
    asked to confirm one line of it is being asked to trust the rest.
    """

    path: str = Field(min_length=1)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    #: The lines as they were read out of the repository at scan time. Carried
    #: so the report stays readable after the code moves on, and so a span that
    #: was verified once can be seen to have been verified.
    snippet: str = ""

    @model_validator(mode="after")
    def the_span_runs_forwards(self) -> "EvidenceSpan":
        if self.end_line < self.start_line:
            raise ValueError(f"{self.path}: span ends at {self.end_line} before it starts")
        return self


class CvssFactors(WireModel):
    """The CVSS v3.1 base metrics. Inputs, so the score is checkable.

    Kept as the metric letters rather than numbers because that is what the
    vector string carries and what a reader can compare against a published
    CVE. The weights live in the scoring code, once.
    """

    attack_vector: Literal["N", "A", "L", "P"]
    attack_complexity: Literal["L", "H"]
    privileges_required: Literal["N", "L", "H"]
    user_interaction: Literal["N", "R"]
    scope: Literal["U", "C"]
    confidentiality: Literal["N", "L", "H"]
    integrity: Literal["N", "L", "H"]
    availability: Literal["N", "L", "H"]

    @computed_field
    @property
    def vector(self) -> str:
        return (
            f"CVSS:3.1/AV:{self.attack_vector}/AC:{self.attack_complexity}"
            f"/PR:{self.privileges_required}/UI:{self.user_interaction}"
            f"/S:{self.scope}/C:{self.confidentiality}/I:{self.integrity}"
            f"/A:{self.availability}"
        )


_AV = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2}
_AC = {"L": 0.77, "H": 0.44}
_PR_UNCHANGED = {"N": 0.85, "L": 0.62, "H": 0.27}
_PR_CHANGED = {"N": 0.85, "L": 0.68, "H": 0.50}
_UI = {"N": 0.85, "R": 0.62}
_CIA = {"H": 0.56, "L": 0.22, "N": 0.0}


def _roundup(value: float) -> float:
    """CVSS v3.1's own rounding, which is not `round`.

    The specification defines it in integer arithmetic precisely because
    floating point rounding produced scores that differed between
    implementations in the first decimal place.
    """
    scaled = round(value * 100_000)
    if scaled % 10_000 == 0:
        return scaled / 100_000.0
    return (floor(scaled / 10_000) + 1) / 10.0


def cvss_base_score(factors: CvssFactors) -> float:
    """The CVSS v3.1 base score, by the published formula.

    Here rather than in the service so that every arm, every benchmark run and
    every report scores the same way, and so that the claim "severity is rule
    based" is something the type system enforces rather than something the
    prose asserts.
    """
    changed = factors.scope == "C"
    privileges = _PR_CHANGED if changed else _PR_UNCHANGED

    iss = 1 - (
        (1 - _CIA[factors.confidentiality])
        * (1 - _CIA[factors.integrity])
        * (1 - _CIA[factors.availability])
    )
    impact = 7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15 if changed else 6.42 * iss
    if impact <= 0:
        return 0.0

    exploitability = (
        8.22
        * _AV[factors.attack_vector]
        * _AC[factors.attack_complexity]
        * privileges[factors.privileges_required]
        * _UI[factors.user_interaction]
    )
    combined = impact + exploitability
    if changed:
        combined *= 1.08
    return _roundup(min(combined, 10.0))


def severity_of(score: float) -> Severity:
    """The published bands. One place, so a report and a filter cannot differ."""
    if score == 0:
        return "none"
    if score < 4.0:
        return "low"
    if score < 7.0:
        return "medium"
    if score < 9.0:
        return "high"
    return "critical"


class SecurityFinding(WireModel):
    id: str = Field(min_length=1)
    #: "CWE-89". The LLM and the trained model both classify; the string is
    #: validated in shape here and against the catalogue in the service.
    cwe: str = Field(pattern=r"^CWE-\d+$")
    title: str = Field(min_length=1)
    origin: FindingOrigin
    #: Every arm that raised this finding, kept even when merged, so the study
    #: can count agreement rather than infer it from `origin`.
    raised_by: list[Literal["scanner", "llm", "trained"]] = Field(min_length=1)
    evidence: EvidenceSpan
    factors: CvssFactors
    status: FindingStatus = "open"
    #: The guarded LLM prose. Empty when the explainer failed or was not run;
    #: the finding still ships with its score, because the score is arithmetic.
    explanation: Prose = ""
    remediation: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_source: ConfidenceSource
    #: Why this weakness class scores what it scores, in one line, from the
    #: rule table. Carried so a reader can disagree with the reasoning rather
    #: than only with the number: a severity nobody can argue with is a
    #: severity nobody can check.
    severity_reasoning: str = ""
    #: Which detector run produced it, so a number can be traced to the model
    #: and date that produced it.
    run_id: str = ""

    @model_validator(mode="after")
    def merged_means_more_than_one(self) -> "SecurityFinding":
        if self.origin == "merged" and len(set(self.raised_by)) < 2:
            raise ValueError(f"{self.id} is merged but only one arm raised it")
        if self.origin != "merged" and list(set(self.raised_by)) != [self.origin]:
            raise ValueError(f"{self.id} says {self.origin} but was raised by {self.raised_by}")
        return self

    @computed_field
    @property
    def base_score(self) -> float:
        return cvss_base_score(self.factors)

    @computed_field
    @property
    def severity(self) -> Severity:
        return severity_of(self.base_score)


class RefusedFinding(WireModel):
    """A finding that was thrown away, and why. Counted, never silent.

    The refusal rate is a result about the arm that produced it: an arm whose
    evidence does not resolve is an arm inventing locations, and dropping those
    quietly would flatter it in exactly the comparison this component exists to
    run.
    """

    origin: Literal["scanner", "llm", "trained"]
    cwe: str = ""
    reason: Literal[
        "file-not-found",
        "span-out-of-range",
        "snippet-does-not-match",
        "malformed-cwe",
        "no-evidence",
    ]
    #: What was claimed, as claimed, so the refusal can be checked.
    claimed_path: str = ""
    claimed_start_line: int | None = Field(default=None, ge=1)
    detail: str = ""


class ToolOutcome(WireModel):
    """One scanning tool in a pass: whether it ran, and if not, why.

    A tool that failed and a tool that found nothing look the same in a list of
    zero findings, and only one of them is a result. The failure reached only
    the stage's notes, so the Security step could not say that npm audit had
    never run on a generated app (review item C3-5).
    """

    tool: str = Field(min_length=1)
    ran: bool
    version: str = ""
    #: Why it did not run. Required then: a failure with no reason reads like a
    #: clean run.
    detail: str = ""

    @model_validator(mode="after")
    def a_tool_that_did_not_run_says_why(self) -> "ToolOutcome":
        if not self.ran and not self.detail.strip():
            raise ValueError(f"{self.tool} did not run and does not say why")
        return self


class DetectorRun(WireModel):
    """One arm's pass over one target: the operational half of the study.

    Cost, latency and offline operation are reported beside accuracy because
    the trained arm's argument is largely made of them, and a comparison that
    reports only F1 cannot see it.
    """

    arm: Literal["scanner", "llm", "trained"]
    #: The exact model or tool version. "the LLM" is not a provenance.
    model_id: str = Field(min_length=1)
    started_at: WireDatetime
    duration_seconds: float = Field(ge=0)
    #: Zero for the arms that make no API call, which is the point.
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    #: What these tokens cost at the provider's public list price, computed
    #: from the token counts rather than read off a bill. Null when the model
    #: is not in the price table.
    #:
    #: It is never zero for a call that was made, and that is the point. An arm
    #: running on a free tier is billed nothing, and recording that as zero
    #: would make it indistinguishable from the scanner arm, which spends
    #: nothing because it makes no API call at all. Those are different facts
    #: and this comparison is largely about the difference, so which tier a run
    #: used belongs in its epoch note beside this number.
    cost_usd: float | None = Field(default=None, ge=0)
    #: Whether this arm needed the network. The trained arm's headline claim.
    offline: bool
    files_scanned: int = Field(default=0, ge=0)


class TestSummary(WireModel):
    """The test side in one block, so C4 reads one artefact rather than two."""

    #: Not a pytest test class. The domain name is right and pytest's
    #: convention collides with it, so the model says so once here rather than
    #: every importing test module aliasing it.
    __test__ = False

    run: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    skipped: int = Field(ge=0)
    line_coverage: float = Field(ge=0, le=100)
    #: Null rather than zero when mutation did not run. Zero is a real score
    #: and means every mutant survived, which is the opposite of not knowing.
    mutation_score: float | None = Field(default=None, ge=0, le=100)


class ValidationReport(WireModel):
    report_version: str = "1.0.0"
    version: int = Field(ge=1)
    generated_at: WireDatetime
    target: str = Field(min_length=1)
    findings: list[SecurityFinding] = Field(default_factory=list)
    refused_evidence: list[RefusedFinding] = Field(default_factory=list)
    detector_runs: list[DetectorRun] = Field(default_factory=list)
    #: Each scanning tool's outcome, ran or not, so a tool that never ran is
    #: said rather than read as a clean scan.
    tools: list[ToolOutcome] = Field(default_factory=list)
    tests: TestSummary
    #: Null until a human decides. C4 refuses to start without it.
    approved_by: str | None = None
    approved_at: WireDatetime | None = None

    @computed_field
    @property
    def open_findings(self) -> int:
        return sum(1 for finding in self.findings if finding.status == "open")

    @computed_field
    @property
    def open_critical_or_high(self) -> int:
        return sum(
            1
            for finding in self.findings
            if finding.status == "open" and finding.severity in ("critical", "high")
        )

    @computed_field
    @property
    def refused_count(self) -> int:
        return len(self.refused_evidence)
