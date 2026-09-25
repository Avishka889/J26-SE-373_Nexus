"""Is this failing test stale, or is it telling the truth?

The decision the whole loop turns on, and the one that decides whether a repair
is even attempted. Healing a regression hides a bug, so the classifier is not
allowed to be a model with an opinion: it is a rule over evidence the platform
already holds, and the model is called only for what the rule cannot reach.

**The signal.** Every test this component writes carries what it was written
from: a story, a criterion index, requirement ids, an endpoint id. Between the
version a test was written against and the version it now fails on, the
platform knows exactly which endpoints and which requirements moved, because
both diffs are contract functions computed from stored artefacts. So:

- a failing test tracing to something that changed is a brittleness candidate,
  because the thing it was written to check is not what it was;
- a failing test tracing only to things that did not change is a regression
  candidate, because nothing it depends on was supposed to move;
- a failing test tracing to nothing, or to a mixture, is what the referee is
  for.

That signal is available because this is a platform rather than a tool pointed
at a repository. A general purpose test repairer sees a red test and a diff; it
cannot ask which requirement the test exists for, because nobody wrote it down.

**What the rules will not do.** They will not call a failure a regression on
the strength of an empty trace. A test that traces to nothing has not told us
anything, and the honest answer to a question nobody has evidence about is that
it is undecided, which is a first class outcome here and reaches a human.
"""

from dataclasses import dataclass

from sdlc_contracts import (
    ClassificationEvidence,
    ContractDiff,
    RequirementDiff,
    TestCase,
)


@dataclass(frozen=True)
class Verdict:
    """What the rules concluded, and the evidence that concluded it."""

    classification: str
    classified_by: str
    evidence: ClassificationEvidence

    @property
    def needs_referee(self) -> bool:
        return self.classification == "undecided"


def endpoints_touched(diff: ContractDiff | None) -> frozenset[str]:
    """Every endpoint id that is not the same in both versions.

    Added and removed count alongside changed: a test against an endpoint that
    no longer exists is testing something the contract stopped promising.
    """
    if diff is None:
        return frozenset()
    return frozenset([*diff.added, *diff.removed, *(change.endpoint_id for change in diff.changed)])


def traced_to(case: TestCase) -> list[str]:
    """Everything this test says it was written from, as flat ids.

    The story id is included even though nothing diffs stories directly: it is
    what a reader recognises, and the evidence is read by people.
    """
    traces = case.traces
    found: list[str] = []
    if traces.story_id:
        found.append(traces.story_id)
    found.extend(traces.requirement_ids)
    found.extend(traces.endpoint_ids)
    return found


def classify(
    case: TestCase,
    *,
    contracts: ContractDiff | None = None,
    requirements: RequirementDiff | None = None,
) -> Verdict:
    """The rules, before any model is asked.

    Deliberately three outcomes. Forcing a binary here is how a loop ends up
    repairing a test that was right: `undecided` is what the referee exists for
    and, if the referee cannot decide either, what a human sees.
    """
    traces = traced_to(case)
    endpoints = endpoints_touched(contracts)
    requirement_ids = requirements.touched if requirements is not None else frozenset()
    moved = endpoints | requirement_ids

    changed = [trace for trace in traces if trace in moved]
    evidence = ClassificationEvidence(traced_to=traces, changed_artefacts=changed)

    if not traces:
        return Verdict(
            classification="undecided",
            classified_by="unclassified",
            evidence=evidence,
            # A test that traces to nothing has told us nothing. Calling that a
            # regression would be inventing evidence for the safer answer, and
            # calling it brittle would be inventing evidence for the dangerous
            # one.
        )
    if contracts is None and requirements is None:
        return Verdict(classification="undecided", classified_by="unclassified", evidence=evidence)
    if changed:
        return Verdict(classification="brittle", classified_by="trace-changed", evidence=evidence)
    return Verdict(classification="regression", classified_by="trace-unchanged", evidence=evidence)


def summarise(verdicts: dict[str, Verdict]) -> dict[str, int]:
    """How many the rules settled and how many they handed on.

    The evaluation reports this: a classifier whose rules decide almost
    everything is a different contribution from one that defers to a model,
    and the only way to know which this is, is to count.
    """
    counts: dict[str, int] = {}
    for verdict in verdicts.values():
        counts[verdict.classified_by] = counts.get(verdict.classified_by, 0) + 1
    return dict(sorted(counts.items()))
