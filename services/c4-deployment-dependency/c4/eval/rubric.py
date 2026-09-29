"""From what was observed to a risk level: `outcome-rubric/1`.

The proposal fixes the principle: ground truth is the observed build, test,
deployment or runtime outcome, not judgement and not the system's own score
(Table 18). It leaves the three level mapping open. This is the mapping, and it
waits on the supervisor's sign off; because cases store observations rather
than labels, changing it relabels nothing.

- **High**: the update broke something that was observed, whether resolution,
  compilation or typechecking, the tests, the build, the boot, the health check
  or a smoke request. All six of BUMP's failure categories are breaks.
- **Medium**: nothing broke, but the update brought warning or deprecation lines
  that name the package or a changed symbol. Something needs attention, and a
  person should look before it ships.
- **Low**: nothing broke and nothing new was said.

A case whose control run, at the installed version, is already broken says
nothing about the update, and is excluded with that reason rather than labelled.
So is a case where nothing ran at all, and one where a download failed in either
run: a registry that did not answer is not the project and not the update.
"""

from dataclasses import dataclass

from sdlc_contracts import RiskLevel

from .cases import Observed

RUBRIC = "outcome-rubric/1"

#: BUMP's categories, every one of which is an observed break.
BUMP_BREAKS = frozenset(
    {
        "COMPILATION_FAILURE",
        "TEST_FAILURE",
        "DEPENDENCY_RESOLUTION_FAILURE",
        "ENFORCER_FAILURE",
        "DEPENDENCY_LOCK_FAILURE",
        "WERROR_FAILURE",
    }
)


@dataclass(frozen=True)
class Excluded:
    reason: str


def level(observed: Observed) -> RiskLevel | Excluded:
    if any(step.outcome == "unavailable" for step in (*observed.baseline, *observed.candidate)):
        return Excluded("a download failed during a run, so it says nothing about the update")
    if any(step.outcome in ("failed", "timed-out") for step in observed.baseline):
        return Excluded("the control run at the installed version is already broken")
    if observed.failure_category:
        if observed.failure_category not in BUMP_BREAKS:
            return Excluded(f"unknown failure category {observed.failure_category}")
        return "high"
    if all(step.outcome == "not-run" for step in observed.candidate):
        return Excluded("nothing was observed with the update applied")
    if any(step.outcome in ("failed", "timed-out") for step in observed.candidate):
        return "high"
    if observed.warnings:
        return "medium"
    return "low"
