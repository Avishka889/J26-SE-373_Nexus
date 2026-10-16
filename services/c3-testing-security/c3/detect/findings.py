"""Candidates from three arms as one validation report, with origins preserved.

The step where a proposal becomes a finding. Nothing before this point has a
severity or a confidence, and after it both exist and neither was authored by
the arm that produced the finding. That is the security pillar's flat claim,
and this module is where it is either true or false.

**Severity by rule.** From the CWE, through the table, by the published CVSS
arithmetic. The same weakness class scores the same on every run whichever arm
raised it, so two runs are comparable and a reader who disagrees can argue with
a vector rather than with a number.

**Confidence from agreement.** How many independent arms raised the same
weakness at the same place. A scanner rule and a language model and a fine
tuned classifier agreeing is evidence in a way that any one of them being
certain is not.

**Origin preserved through the merge.** A merged finding names every arm that
raised it, which is the ensemble's own evidence and the input to the confidence
rule, and it is also the whole comparison: the study asks which arm found what,
and a merge that forgot would have thrown that away to produce a tidier list.

**Evidence resolves or the finding does not exist.** Every candidate's span is
checked against the repository and the snippet is read from the file rather
than from the arm, so what a reader sees is what is there. Refusals are counted
per arm, because an arm whose evidence does not resolve is an arm inventing
locations and that is a result about it.
"""

from dataclasses import dataclass, field
from pathlib import Path

from sdlc_contracts import DetectorRun, RefusedFinding, SecurityFinding, ToolOutcome

from ..detection import (
    Candidate,
    DetectionResult,
    is_evidence_resolvable,
    sites,
    to_finding,
)
from .severity import factors_for

#: How much of the file travels with a finding. Enough for a reader to see the
#: statement in its context without the report becoming the repository.
SNIPPET_LINES = 3


@dataclass
class Merged:
    """What the three arms produced together, and what was thrown away."""

    findings: list[SecurityFinding] = field(default_factory=list)
    refused: list[RefusedFinding] = field(default_factory=list)
    runs: list[DetectorRun] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    tools: list[ToolOutcome] = field(default_factory=list)

    @property
    def by_origin(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.origin] = counts.get(finding.origin, 0) + 1
        return counts


def snippet_at(root: str, candidate: Candidate, *, around: int = SNIPPET_LINES) -> str:
    """The code the finding is about, read from the file and not from the arm.

    Read here rather than carried from the arm on purpose: an arm that quoted
    something slightly different from what is in the file would otherwise have
    its version printed in the report, and the report is supposed to say what
    is there.
    """
    try:
        lines = (Path(root) / candidate.path).read_text(errors="replace").splitlines()
    except OSError:
        return ""
    first = max(1, candidate.start_line - around)
    last = min(len(lines), candidate.end_line + around)
    return "\n".join(lines[first - 1 : last])


def merge_findings(root: str, results: list[DetectionResult], *, run_id: str = "") -> Merged:
    """Every arm's candidates as one list of findings, scored by rule.

    Findings are ordered by severity and then by location, because a report
    read from the top should start with the thing that matters most and a
    reader comparing two runs should not have to sort them first.
    """
    merged = Merged(
        runs=[result.run for result in results],
        failures=[failure for result in results for failure in result.failures],
        refused=[refusal for result in results for refusal in result.refused],
        tools=[tool for result in results for tool in result.tools],
    )
    # One finding per weakness, not per arm that mentioned it. The grouping is
    # by overlapping span, because three arms looking at one injection report
    # it at three different lines and a report that lists it three times has
    # merged nothing.
    for site in sites(results):
        candidate = site.candidate
        resolvable, reason = is_evidence_resolvable(root, candidate)
        if not resolvable:
            merged.refused.append(
                RefusedFinding(
                    origin=site.arms[0],
                    cwe=candidate.cwe,
                    reason=reason,  # type: ignore[arg-type]
                    claimed_path=candidate.path,
                    claimed_start_line=candidate.start_line or None,
                    detail=candidate.title,
                )
            )
            continue
        factors, reasoning = factors_for(candidate.cwe)
        finding = to_finding(
            candidate,
            finding_id=_identifier(candidate),
            arms=site.arms,
            factors=factors,
            snippet=snippet_at(root, candidate),
            run_id=run_id,
        )
        merged.findings.append(
            finding.model_copy(
                update={
                    "severity_reasoning": reasoning,
                    "explanation": candidate.message,
                    "remediation": str(candidate.extra.get("remediation") or ""),
                }
            )
        )

    merged.findings.sort(
        key=lambda found: (-found.base_score, found.evidence.path, found.evidence.start_line)
    )
    return merged


def _identifier(candidate: Candidate) -> str:
    """A stable id for one weakness at one place.

    Stable across runs so that two reports of the same repository can be
    compared finding by finding, which is what the remediation stage needs to
    say whether a fix worked.
    """
    return f"{candidate.cwe}:{candidate.path}:{candidate.start_line}".replace("/", "_")
