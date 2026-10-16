"""From verified findings to proposals a human can approve.

The stage that turns the security report into decisions. Three rules shape it,
and all three are about what must not reach a reviewer.

**Only findings whose evidence resolved.** Every finding that survives the merge
has a span that resolves in the repository, so this holds by construction rather
than by a check here. It is worth stating anyway: a proposal for a fabricated
location would be a patch against a line that does not exist, and the reviewer
would be the one to discover it.

**Worst first, and only as many as a person will read.** A list of sixty
proposals is a list nobody reads, and a reviewer who stops at the tenth has
stopped at whichever ten the sort order happened to put first. So the order is
severity then location, and the count is capped, and the ones left out are
reported as a number rather than dropped in silence.

**A proposal that could not be patched is still recorded.** The finding stays
open and the reason is on it. An open finding a person can see is worth more
than a quietly shorter list.
"""

import logging
import re
from dataclasses import dataclass, field

from sdlc_contracts import (
    ApiContract,
    RemediationProposal,
    RemediationProposals,
    SecurityFinding,
    TestReport,
    ValidationReport,
    WireDatetime,
)

from .patch import PatchOutcome
from .risk import assess

log = logging.getLogger(__name__)

#: How many proposals one scan offers. Beyond this a reviewer is skimming, and
#: a skimmed security decision is worse than a deferred one.
MAX_PROPOSALS = 10


@dataclass
class Unproposed:
    """A finding no proposal was made for, and why. Counted, never silent."""

    finding_id: str
    cwe: str
    reason: str


@dataclass
class ProposalRun:
    """What the stage produced."""

    proposals: list[RemediationProposal] = field(default_factory=list)
    unproposed: list[Unproposed] = field(default_factory=list)
    #: Findings below the cap that were never looked at. Reported so that
    #: "ten proposals" is never mistaken for "ten findings".
    not_reached: int = 0

    def artefact(self, *, version: int, target: str, at: WireDatetime) -> RemediationProposals:
        return RemediationProposals(
            version=version,
            generated_at=at,
            target=target,
            proposals=self.proposals,
        )


def worst_first(findings: list[SecurityFinding]) -> list[SecurityFinding]:
    """Highest score first, then by location so two runs agree.

    Location as the tiebreak rather than the order the arms happened to answer
    in: a reviewer comparing two reports should see the same order, and arm
    scheduling is not a property of the code.
    """
    return sorted(
        findings,
        key=lambda finding: (
            -finding.base_score,
            finding.evidence.path,
            finding.evidence.start_line,
        ),
    )


def covering_tests(finding: SecurityFinding, tests: TestReport | None) -> int:
    """How many tests exercise the file this finding is in.

    File level rather than line level, and that is a deliberate
    overstatement of what is known: line level coverage attribution exists in
    the harness but is per suite rather than per test, and claiming a precision
    the data does not have is the failure this component spends most of its
    time avoiding. The label on the counted fact says "covering those lines",
    so this is the number that label promises at the granularity available.
    """
    if tests is None:
        return 0
    path = finding.evidence.path
    module = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return sum(
        1
        for suite in tests.suites
        for case in suite.cases
        if module and (module in suite.path or module in case.name)
    )


#: What C2's generator writes above each route it emits. The generated file
#: names the endpoint it implements, which is the only link from a source file
#: back to a contract that a reader can check by opening the file.
IMPLEMENTS = re.compile(r"//\s*implements\s+(?P<id>[\w.-]+)")


def endpoints_in(source: str, contract: ApiContract | None) -> list[str]:
    """Which endpoints this file implements, read out of the file itself.

    C2's API generator writes `// implements <id> <METHOD> <path>` above every
    route, so a generated handler says what it is for. Matching on that marker
    rather than guessing from the file name means the answer is something a
    reviewer can confirm by looking, and a hand written file that carries no
    marker honestly reports none rather than being guessed at.

    Cross checked against the contract, so a stale marker for an endpoint that
    no longer exists does not inflate the count.
    """
    if contract is None or not source:
        return []
    known = {endpoint.id for endpoint in contract.endpoints}
    found = [match.group("id") for match in IMPLEMENTS.finditer(source)]
    return sorted({endpoint for endpoint in found if endpoint in known})


def proposal_for(
    finding: SecurityFinding,
    outcome: PatchOutcome,
    *,
    at: WireDatetime,
    tests: TestReport | None = None,
    contract: ApiContract | None = None,
    source: str = "",
) -> RemediationProposal:
    """One finding and its patch, as something a person can decide on."""
    tests_covering = covering_tests(finding, tests)
    endpoint_ids = endpoints_in(source, contract)
    return RemediationProposal(
        id=f"fix-{finding.id}",
        finding_id=finding.id,
        cwe=finding.cwe,
        generated_at=at,
        summary=outcome.explanation or f"fix the {finding.cwe} in {finding.evidence.path}",
        patch=outcome.hunks,
        risk=assess(
            outcome.hunks,
            covering_tests=tests_covering,
            moved_endpoints=len(endpoint_ids),
        ),
        affected_endpoints=endpoint_ids,
        affected_tests=_test_names(finding, tests),
        state="proposed",
    )


def _test_names(finding: SecurityFinding, tests: TestReport | None) -> list[str]:
    if tests is None:
        return []
    module = finding.evidence.path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return [
        case.name
        for suite in tests.suites
        for case in suite.cases
        if module and (module in suite.path or module in case.name)
    ][:20]


def candidates(report: ValidationReport, *, limit: int = MAX_PROPOSALS) -> tuple[list, int]:
    """The findings worth proposing a fix for, and how many were left behind.

    Open findings only: one already dismissed by a person is one the pipeline
    has been told not to raise again.
    """
    open_findings = [finding for finding in report.findings if finding.status == "open"]
    ordered = worst_first(open_findings)
    return ordered[:limit], max(0, len(ordered) - limit)
