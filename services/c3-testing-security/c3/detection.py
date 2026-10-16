"""The three detectors, behind one interface.

The security pillar's whole design is that these three are interchangeable at
the seam and comparable at the report: the scanners, the prompted LLM, and the
locally trained model. Each answers the same question over the same input, and
the study asks which of them, or which combination, answers it better and at
what cost.

The interface exists before any of the three do, because the shape of the
comparison is the contribution and it should not be retrofitted around whatever
the first implementation happened to return. Two things it forces:

**Every arm reports its own cost.** `DetectorRun` carries duration, tokens,
money and whether the arm needed the network. The trained arm's argument is
made almost entirely of those numbers, and an interface that returned only
findings would have quietly thrown away the half of the result that favours it.

**Every arm declares its provenance.** `model_id` is required and is the exact
version, because "the LLM" is not a provenance and a number in a dissertation
that cannot name what produced it is not a number anybody can use.

The trained backend is deliberately not an import. It runs behind a process
boundary so that torch and transformers, which are around two gigabytes of
wheels, stay out of the orchestrator's environment and out of CI on a machine
with under six gigabytes of memory. It is also the honest shape: the trained
arm is meant to be deployable on its own, offline, which is the claim being
made about it.
"""

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from sdlc_contracts import DetectorRun, RefusedFinding, SecurityFinding, ToolOutcome

Arm = Literal["scanner", "llm", "trained"]


@dataclass(frozen=True)
class Candidate:
    """One thing an arm thinks is wrong, before anything has checked it.

    Not a `SecurityFinding`: a finding carries a CVSS vector and verified
    evidence, and an arm produces neither. An arm proposes a weakness at a
    location, and the pipeline verifies the location, scores the weakness by
    rule, and only then has a finding. Keeping the two types apart is what
    stops an arm from being able to assert a severity.
    """

    cwe: str
    title: str
    path: str
    start_line: int
    end_line: int
    #: The arm's own words, when it has any. The scanners give a rule message,
    #: the LLM gives prose, the trained model gives nothing.
    message: str = ""
    #: The arm's own score, where it has one, on its own scale. Never used as
    #: confidence: confidence is computed from agreement or from a rule.
    raw_score: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DetectionResult:
    """What one arm found, and what it cost to find it."""

    candidates: list[Candidate]
    run: DetectorRun
    #: Candidates this arm produced that could not be used, with the reason.
    #: An arm that invents locations should be visibly the arm that invents
    #: locations, so these are carried rather than dropped.
    refused: list[RefusedFinding] = field(default_factory=list)
    #: How many things this arm actually looked at: methods for an arm that
    #: classifies methods, files for one that reads files. Reported because a
    #: finding count means nothing without it. An arm that flags everything it
    #: is shown has perfect recall and has detected nothing, and without this
    #: the report would show that as a triumph. It is not hypothetical: the
    #: trained arm flagged 7,295 of 7,295 methods on OWASP Benchmark.
    units_examined: int = 0
    #: What did not run, with the reason. A tool that fell over and a tool that
    #: found nothing produce the same empty list, and only one of them is a
    #: result, so the difference is carried to the report instead of being
    #: folded away here.
    failures: list[str] = field(default_factory=list)
    #: Each tool's outcome, ran or not, for the report (review item C3-5).
    tools: list[ToolOutcome] = field(default_factory=list)


class DetectionBackend(Protocol):
    """One arm of the three way comparison.

    `scan` takes the files to look at rather than a repository, because the
    arms disagree about what they can afford: the scanners walk a tree happily,
    the LLM is priced per token and reads slices, and the trained model works
    at method granularity. Handing each one the same explicit list is what
    makes the comparison a comparison.
    """

    #: Which arm this is, for the report and the merge.
    arm: Arm
    #: The exact tool or model version. Required, and recorded per run.
    model_id: str
    #: Whether this arm can work with the network unplugged.
    offline: bool

    async def scan(self, root: str, files: list[str]) -> DetectionResult: ...


def merge(results: list[DetectionResult]) -> list[Candidate]:
    """One list of candidates, with duplicates collapsed by location.

    Two arms naming the same weakness at the same place is the ensemble's own
    evidence and the input to `arm-agreement` confidence, so the merge keeps
    which arms agreed rather than counting. Deliberately simple: the study
    compares the arms against each other, and a clever merge would become a
    fourth arm nobody asked for.
    """
    collapsed: dict[tuple[str, str, int], Candidate] = {}
    for result in results:
        for candidate in result.candidates:
            key = (candidate.cwe, candidate.path, candidate.start_line)
            collapsed.setdefault(key, candidate)
    return list(collapsed.values())


#: The order arms are listed in, so a finding reads the same way twice.
_ARM_ORDER: tuple[Arm, ...] = ("scanner", "llm", "trained")


@dataclass
class Site:
    """One weakness at one place, as every arm that saw it.

    Not one candidate: three arms looking at the same SQL injection report it
    at three different places, because a static analyser points at the
    statement, a token classifier at the method that contains it and a model at
    whichever line it thought was the interesting one. They are the same
    weakness and a report that lists them three times has not merged anything.
    """

    #: The narrowest span of the group, which is the most checkable evidence a
    #: reader can be given. Whoever produced it, a statement beats a method.
    candidate: Candidate
    #: Every arm that raised something overlapping, in a fixed order.
    arms: list[Arm]


def _span(candidate: Candidate) -> tuple[int, int]:
    start = candidate.start_line or 0
    return start, max(candidate.end_line or start, start)


def sites(results: list[DetectionResult]) -> list[Site]:
    """Group every arm's candidates into the weaknesses they are about.

    **Overlap, not an identical start line.** Keying agreement on the exact
    first line was the original rule, and it meant the arms essentially never
    agreed: the first live three arm run found the same injection in the same
    file at lines 33 to 39, 34, and 36, recorded it as three findings at the
    lowest confidence each, and merged exactly one finding out of seventeen.
    Confidence from independent agreement is the security pillar's whole claim
    about not letting a detector score itself, and an exact line match made it
    unreachable in practice.

    Spans that do not touch stay apart, so two real weaknesses of the same
    class in one file are still two findings. Touching at all is enough:
    one arm naming a method and another naming a line inside it are looking at
    the same code, and requiring more than that would put a tuned threshold
    where a containment test does.
    """
    by_place: dict[tuple[str, str], list[tuple[Arm, Candidate]]] = {}
    for result in results:
        for candidate in result.candidates:
            by_place.setdefault((candidate.cwe, candidate.path), []).append(
                (result.run.arm, candidate)
            )

    found: list[Site] = []
    for entries in by_place.values():
        entries.sort(key=lambda pair: _span(pair[1]))
        groups: list[list[tuple[Arm, Candidate]]] = []
        reach = 0
        for arm, candidate in entries:
            start, end = _span(candidate)
            if groups and start <= reach:
                groups[-1].append((arm, candidate))
                reach = max(reach, end)
            else:
                groups.append([(arm, candidate)])
                reach = end
        for group in groups:
            narrowest = min(
                group, key=lambda pair: (_span(pair[1])[1] - _span(pair[1])[0], pair[1].start_line)
            )[1]
            raised = {arm for arm, _ in group}
            found.append(
                Site(
                    candidate=narrowest,
                    arms=[arm for arm in _ARM_ORDER if arm in raised],
                )
            )
    return found


def confidence_from_agreement(arms: list[Arm]) -> float:
    """How much to trust a candidate, from how many arms independently raised it.

    A rule rather than a model's opinion, and a deliberately blunt one: the
    point is that no detector scores its own finding, not that this particular
    curve is optimal. Calibrating it against the benchmark is evaluation work
    and belongs in the study, where it can be reported.
    """
    return {1: 0.5, 2: 0.8, 3: 0.95}.get(len(set(arms)), 0.5)


def is_evidence_resolvable(root: str, candidate: Candidate) -> tuple[bool, str]:
    """Whether the candidate's location exists in the repository.

    The span verification discipline, applied to security. An arm that names a
    file that is not there, or a line past the end of one, has produced a
    fabrication rather than a finding, and the pipeline counts it as such.

    Returns the verdict and the refusal reason, so the caller records why
    rather than inventing a reason from a boolean.
    """
    from pathlib import Path

    if not candidate.path:
        return False, "no-evidence"
    if candidate.start_line < 1 or candidate.end_line < candidate.start_line:
        # Line zero is what an arm produces when it has a weakness and no
        # location for it: npm audit emits it for a package that is not in the
        # manifest. There is no line zero in any file, so it is refused here
        # rather than resolving to something a reader would believe.
        return False, "no-evidence"
    target = Path(root) / candidate.path
    if not target.is_file():
        return False, "file-not-found"
    try:
        lines = target.read_text(errors="replace").splitlines()
    except OSError:
        return False, "file-not-found"
    if candidate.start_line > len(lines) or candidate.end_line > len(lines):
        return False, "span-out-of-range"
    return True, ""


def to_finding(
    candidate: Candidate,
    *,
    finding_id: str,
    arms: list[Arm],
    factors: Any,
    snippet: str,
    run_id: str = "",
) -> SecurityFinding:
    """A verified candidate, scored by rule, as a finding.

    The only path from a candidate to a finding, so an arm cannot construct one
    directly and therefore cannot set a severity or a confidence. Both are
    computed: the severity from the CVSS factors by the published formula, the
    confidence from how many arms agreed.
    """
    unique = list(dict.fromkeys(arms))
    return SecurityFinding(
        id=finding_id,
        cwe=candidate.cwe,
        title=candidate.title,
        origin="merged" if len(unique) > 1 else unique[0],
        raised_by=unique,
        evidence={
            "path": candidate.path,
            "startLine": candidate.start_line,
            "endLine": candidate.end_line,
            "snippet": snippet,
        },
        factors=factors,
        confidence=confidence_from_agreement(unique),
        confidence_source="arm-agreement" if len(unique) > 1 else "scanner-rule",
        run_id=run_id,
    )
