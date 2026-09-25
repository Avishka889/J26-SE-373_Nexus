"""The scanner arm as one detector, so the three way comparison can run it.

Three tools with different report shapes, different notions of a location and
different ideas of what a weakness is, presented as one arm that answers the
same question as the prompted LLM and the trained model over the same input.
Everything awkward about doing that is here, and it is worth naming, because
each awkwardness is a place the comparison could quietly have become unfair.

**Which tools run is a property of the target, not a setting.** Semgrep reads
both stacks, npm audit needs a manifest, FindSecBugs needs bytecode. Running a
Java analyser at a React app and counting its silence as a clean result would
make the arm look precise on targets it never examined.

**A weakness at a line is one weakness, however many rules fired.** SpotBugs
reports the sample's SQL injection twice, under two rules that describe the
same sink; semgrep and FindSecBugs both report it as well. Counting those as
four findings would halve the arm's measured precision for a reason that is
about rule packs rather than about the code, so they collapse to one candidate
that names every tool that raised it.

**This arm is not offline, and says so.** Semgrep fetches its rules from the
registry and npm audit asks a service which versions are affected. Only
FindSecBugs works with the network unplugged once its jar is cached. Offline
operation is the trained arm's headline claim in this study, and it would be
worthless if the baseline claimed it untruthfully.

**A tool that fell over is not a tool that found nothing.** Failures are
carried on the result rather than folded into an empty finding list, because
the second is a result and the first is a missing measurement.
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sdlc_contracts import DetectorRun, RefusedFinding, ToolOutcome

from ..detection import Arm, Candidate, DetectionResult, is_evidence_resolvable
from ..harness import Sandbox, TargetRepo
from .scanners import ScanOutput, run_findsecbugs, run_npm_audit, run_semgrep

#: What a dependency advisory's evidence points at. Such a finding is about the
#: project rather than about a file anyone touched, so it survives a scan
#: narrowed to changed files.
PROJECT_SCOPE = "project"


def tools_for(repo: TargetRepo) -> tuple[str, ...]:
    """Which of the three can say anything about this target.

    Semgrep always, because it is the only arm that reads the MERN side at all.
    The other two are asked only where their input exists.
    """
    if repo.stack == "java":
        return ("semgrep", "findsecbugs")
    if repo.stack == "node":
        return ("semgrep", "npm audit")
    return ("semgrep",)


@dataclass
class ScannerArm:
    """The static analysis baseline, behind the detector interface.

    Costs nothing per run, makes no API call the study pays for, and answers
    the same way every time. Those are the properties the other two arms have
    to beat on accuracy while losing on cost, which is the comparison the
    security pillar exists to make.
    """

    repo: TargetRepo
    sandbox: Sandbox | None = None
    arm: Arm = "scanner"
    #: The exact versions that ran, filled in by the run itself. A composite,
    #: because the arm is three tools and reporting one of their versions as
    #: the arm's provenance would be a provenance that cannot be reproduced.
    model_id: str = "scanners (not yet run)"
    #: Semgrep fetches rules and npm audit asks a service. Truthfully false.
    offline: bool = False
    #: Set by the run, so a caller can say which tools did not answer.
    failures: list[str] = field(default_factory=list)

    async def scan(self, root: str, files: list[str]) -> DetectionResult:
        """Run every applicable tool, verify every location, report the cost.

        `files` narrows the result to the slice the other arms were given, so
        the comparison is over the same input. It never narrows what the tools
        look at: a scanner reads a tree, that is how it works, and pretending
        otherwise would cost time without changing the answer.
        """
        return await asyncio.to_thread(self.scan_now, root, files)

    def scan_now(self, root: str, files: list[str]) -> DetectionResult:
        started = datetime.now(UTC)
        clock = time.monotonic()
        sandbox = self.sandbox or Sandbox(self.repo.root)

        outputs: list[ScanOutput] = []
        for tool in tools_for(self.repo):
            if tool == "semgrep":
                outputs.append(run_semgrep(self.repo, sandbox))
            elif tool == "npm audit":
                outputs.append(run_npm_audit(self.repo, sandbox))
            elif tool == "findsecbugs":
                outputs.append(run_findsecbugs(self.repo, sandbox))

        ran = [output for output in outputs if output.ran]
        self.failures = [f"{output.tool}: {output.failure}" for output in outputs if not output.ran]
        tools = [
            ToolOutcome(
                tool=output.tool,
                ran=output.ran,
                version=output.version if output.ran else "",
                detail=output.failure,
            )
            for output in outputs
        ]
        self.model_id = (
            " + ".join(
                f"{output.tool} {output.version or 'version not reported'}" for output in ran
            )
            or "no scanner ran"
        )

        wanted = set(files or ())
        kept: dict[tuple[str, str, int], Candidate] = {}
        refused: list[RefusedFinding] = []
        for output in ran:
            for candidate in output.candidates:
                if wanted and not _in_scope(candidate, wanted):
                    continue
                resolvable, reason = is_evidence_resolvable(root, candidate)
                if not resolvable:
                    refused.append(
                        RefusedFinding(
                            origin="scanner",
                            cwe=candidate.cwe,
                            reason=reason,
                            claimed_path=candidate.path,
                            claimed_start_line=candidate.start_line or None,
                            detail=f"{output.tool}: {candidate.title}",
                        )
                    )
                    continue
                _collapse(kept, candidate, output.tool)

        return DetectionResult(
            candidates=list(kept.values()),
            refused=refused,
            failures=list(self.failures),
            tools=tools,
            units_examined=len({path for output in ran for path in output.files}),
            run=DetectorRun(
                arm="scanner",
                model_id=self.model_id,
                started_at=started,
                duration_seconds=round(time.monotonic() - clock, 3),
                offline=self.offline,
                # Zero rather than null, and the difference matters: this arm
                # makes no API call, so its cost is known to be nothing. An
                # arm on a free tier reports null, because nobody said.
                cost_usd=0.0,
                # The union, not the sum. Two tools reading the same six files
                # examined six files, and a denominator that said twelve would
                # make every coverage claim built on it wrong.
                files_scanned=len({path for output in ran for path in output.files}),
            ),
        )


def _in_scope(candidate: Candidate, wanted: set[str]) -> bool:
    """Whether a narrowed scan keeps this one.

    A dependency advisory always survives: it is about what the project
    depends on, and a scan narrowed to the files a commit touched would drop
    it for a reason that has nothing to do with whether it is true.
    """
    return candidate.extra.get("scope") == PROJECT_SCOPE or candidate.path in wanted


def _collapse(kept: dict[tuple[str, str, int], Candidate], candidate: Candidate, tool: str) -> None:
    """One weakness at one line, naming every tool that raised it.

    Agreement between tools is information, so it is recorded rather than
    counted twice. The first tool's title and message win, because a merged
    message reads like neither tool and cites neither.
    """
    key = (candidate.cwe, candidate.path, candidate.start_line)
    existing = kept.get(key)
    if existing is None:
        kept[key] = Candidate(
            cwe=candidate.cwe,
            title=candidate.title,
            path=candidate.path,
            start_line=candidate.start_line,
            end_line=candidate.end_line,
            message=candidate.message,
            raw_score=candidate.raw_score,
            extra={**candidate.extra, "tools": [tool]},
        )
        return
    tools = list(existing.extra.get("tools") or [])
    if tool not in tools:
        tools.append(tool)
    kept[key] = Candidate(
        cwe=existing.cwe,
        title=existing.title,
        path=existing.path,
        start_line=existing.start_line,
        end_line=max(existing.end_line, candidate.end_line),
        message=existing.message,
        raw_score=existing.raw_score,
        extra={**existing.extra, "tools": tools},
    )
