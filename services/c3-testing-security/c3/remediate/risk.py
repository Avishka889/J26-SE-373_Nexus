"""How dangerous a patch is, counted rather than asserted.

"This is a low risk change" is an opinion, and an opinion in a field a model
filled in is an opinion nobody should act on. "Three tests cover the two lines
this changes, and no endpoint's contract moves" is a claim a reader can check
against the repository in front of them.

So the risk level here is derived by arithmetic from four counts, and the
sentence that goes with it may only restate them. The contract carries the
counts beside the sentence for exactly this reason: a reviewer who doubts the
level can recompute it, which is not true of any adjective.

**Why these four counts.** They are what makes a security fix go wrong in
practice. A change spread over many lines is harder to review than a one line
one. A change no test covers is a change nothing will catch if it is wrong. A
change that moves an endpoint's contract breaks C2's generated client and C3's
own API tests, which is a blast radius well beyond the file being edited. And a
change to a file many tests depend on is one whose failure will be loud but
late.

**The thresholds are deliberately blunt** and stated here rather than tuned.
They are a reviewer's prior, not a model, and pretending to precision would be
the same mistake the severity table refuses to make.
"""

from dataclasses import dataclass

from sdlc_contracts import CountedFact, PatchHunk, RiskAssessment

from .guard import added_lines

#: Above this many changed lines a patch stops being reviewable at a glance.
MANY_LINES = 20

#: A change nothing covers is the single strongest signal here: no test will
#: notice if the fix is wrong, and a security fix that is wrong is worse than
#: the weakness, because everybody now believes it is closed.
UNCOVERED_IS_RISKY = True


@dataclass(frozen=True)
class Blast:
    """What the patch reaches, counted."""

    files: int
    lines_changed: int
    covering_tests: int
    moved_endpoints: int

    def facts(self) -> list[CountedFact]:
        return [
            CountedFact(label="files changed", value=self.files),
            CountedFact(label="lines changed", value=self.lines_changed),
            CountedFact(label="tests covering those lines", value=self.covering_tests),
            CountedFact(label="endpoints whose contract moves", value=self.moved_endpoints),
        ]


def removed_lines(diff: str) -> list[str]:
    return [
        line[1:]
        for line in diff.splitlines()
        if line.startswith("-") and not line.startswith("---")
    ]


def measure(
    hunks: list[PatchHunk],
    *,
    covering_tests: int = 0,
    moved_endpoints: int = 0,
) -> Blast:
    """Count what the patch touches.

    Added and removed lines both count. A patch that deletes fifteen lines and
    adds one is not a one line change, and calling it one would understate
    exactly the patches most worth reading.
    """
    changed = sum(len(added_lines(hunk.diff)) + len(removed_lines(hunk.diff)) for hunk in hunks)
    return Blast(
        files=len({hunk.path for hunk in hunks}),
        lines_changed=changed,
        covering_tests=covering_tests,
        moved_endpoints=moved_endpoints,
    )


def level_of(blast: Blast) -> str:
    """The risk band, by rule.

    High when the change moves a contract other components generate against, or
    when it is both large and uncovered. Low only when it is small and
    something would catch it being wrong. Everything else is medium, which is
    the honest answer most of the time.
    """
    if blast.moved_endpoints > 0:
        return "high"
    if blast.lines_changed > MANY_LINES and blast.covering_tests == 0:
        return "high"
    if blast.covering_tests == 0 and UNCOVERED_IS_RISKY:
        return "medium"
    if blast.lines_changed > MANY_LINES:
        return "medium"
    return "low"


def statement_for(blast: Blast, level: str) -> str:
    """The sentence a reader sees, built from the counts and nothing else.

    Generated rather than written by a model on purpose. This is the one line
    most likely to be read and least likely to be checked, so it is the one
    line that must not contain anything the numbers do not support.
    """
    covered = (
        f"{blast.covering_tests} test{'s' if blast.covering_tests != 1 else ''} cover"
        f"{'' if blast.covering_tests != 1 else 's'} the lines it changes"
        if blast.covering_tests
        else "no test covers the lines it changes"
    )
    endpoints = (
        f", and it moves {blast.moved_endpoints} endpoint contract"
        f"{'s' if blast.moved_endpoints != 1 else ''}"
        if blast.moved_endpoints
        else ", and no endpoint contract moves"
    )
    return (
        f"{level.capitalize()} risk: the patch changes {blast.lines_changed} line"
        f"{'s' if blast.lines_changed != 1 else ''} in {blast.files} file"
        f"{'s' if blast.files != 1 else ''}, {covered}{endpoints}."
    )


def assess(
    hunks: list[PatchHunk],
    *,
    covering_tests: int = 0,
    moved_endpoints: int = 0,
) -> RiskAssessment:
    """The full assessment: a level, a sentence, and the numbers under both."""
    blast = measure(hunks, covering_tests=covering_tests, moved_endpoints=moved_endpoints)
    level = level_of(blast)
    return RiskAssessment(
        level=level,  # type: ignore[arg-type]
        statement=statement_for(blast, level),
        facts=blast.facts(),
    )
