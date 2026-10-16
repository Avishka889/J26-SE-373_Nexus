"""What a remediation may not do, checked before anybody is asked to approve it.

The self healing loop has a guard because a model asked to make a test pass can
make it pass by checking nothing. This is the same failure one component over:
a model asked to make a finding go away can make it go away by telling the
scanner not to look.

`// nosemgrep` closes the finding. So does `@SuppressWarnings("SQL_INJECTION")`,
and `# nosec`, and `/* NOSONAR */`. Every one of them passes a re-scan, passes
the test suite, and leaves the weakness exactly where it was. They are the
security analogue of replacing an assertion with `toBeDefined()`, and they are
refused here for the same reason: an outcome that is indistinguishable from
success while delivering none of it is the one thing an automated pipeline must
not be able to produce.

**Three refusals, in the order they matter.**

A patch that only suppresses is refused outright. A patch that suppresses *and*
fixes is still refused, because the suppression is then unnecessary and its
presence means the next reader cannot tell which of the two closed the finding.

A patch that edits test code is refused. Tests are the other loop's territory,
and a remediation that adjusts a test to stop it failing after the fix has
quietly widened the change into somewhere nobody approved.

A patch that touches a file the finding does not name is refused. The proposal
is answering one finding at a location, and a change reaching beyond it is a
change whose risk was assessed against the wrong thing.

None of this says the patch is correct. It says the patch is the kind of thing
that could be correct, which is what a human being asked to approve it is
entitled to assume before they start reading.
"""

import re
from dataclasses import dataclass

from sdlc_contracts import PatchHunk

#: How each toolchain is told to look away. Matched on added lines only: a
#: suppression that was already in the file is somebody else's decision and not
#: this patch's doing.
SUPPRESSIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bnosemgrep\b", re.IGNORECASE), "a semgrep suppression"),
    (re.compile(r"#\s*nosec\b", re.IGNORECASE), "a bandit suppression"),
    (re.compile(r"\bNOSONAR\b"), "a sonarqube suppression"),
    (re.compile(r"@SuppressWarnings\b"), "a java warning suppression"),
    (re.compile(r"@SuppressFBWarnings\b"), "a spotbugs suppression"),
    (re.compile(r"eslint-disable"), "an eslint suppression"),
    (re.compile(r"@ts-(?:ignore|expect-error)\b"), "a typescript error suppression"),
    (re.compile(r"//\s*codeql\[", re.IGNORECASE), "a codeql suppression"),
    (re.compile(r"\bskipcq\b", re.IGNORECASE), "a deepsource suppression"),
)

#: Anything under one of these, or named like one, is test code.
TEST_MARKERS = ("/test/", "/tests/", "/__tests__/", "src/test/", "/spec/")
TEST_SUFFIXES = (
    ".test.ts",
    ".test.tsx",
    ".test.js",
    ".spec.ts",
    ".spec.js",
    "Test.java",
    "_test.py",
)


@dataclass(frozen=True)
class Refusal:
    """Why a patch may not be proposed, in the report's own words."""

    reason: str
    detail: str

    def __str__(self) -> str:
        return f"{self.reason}: {self.detail}"


def added_lines(diff: str) -> list[str]:
    """The lines a hunk introduces, without the marker.

    Added lines only. A diff's context lines are the file as it already was, and
    accusing a patch of a suppression it merely sat next to would refuse honest
    work for something somebody else did.
    """
    return [
        line[1:]
        for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]


def is_test_code(path: str) -> bool:
    lowered = path.replace("\\", "/").lower()
    return any(marker in lowered for marker in TEST_MARKERS) or path.endswith(TEST_SUFFIXES)


def suppressions_in(hunks: list[PatchHunk]) -> list[str]:
    """Every way this patch tells a tool to stop reporting."""
    found: list[str] = []
    for hunk in hunks:
        for line in added_lines(hunk.diff):
            for pattern, what in SUPPRESSIONS:
                if pattern.search(line):
                    found.append(f"{what} in {hunk.path}: {line.strip()[:80]}")
                    break
    return found


def refusal_for(hunks: list[PatchHunk], *, finding_path: str) -> Refusal | None:
    """The reason this patch may not be proposed, or nothing.

    Ordered so the reason a reader sees first is the one that matters most. A
    patch that both suppresses and wanders is reported as suppressing, because
    that is the finding worth recording about the model that produced it.
    """
    if not hunks:
        return Refusal("no-patch", "the proposal carries no change at all")

    suppressed = suppressions_in(hunks)
    if suppressed:
        return Refusal(
            "suppression-not-fix",
            "the patch silences the tool rather than fixing the weakness: "
            + "; ".join(suppressed[:2]),
        )

    tests = [hunk.path for hunk in hunks if is_test_code(hunk.path)]
    if tests:
        return Refusal(
            "touched-test-code",
            "a remediation changes the code the finding is about, not the tests that "
            f"cover it: {', '.join(tests[:3])}",
        )

    wandered = [hunk.path for hunk in hunks if hunk.path != finding_path]
    if wandered:
        return Refusal(
            "outside-the-finding",
            f"the finding is in {finding_path} and the patch also changes "
            f"{', '.join(wandered[:3])}",
        )
    return None


def accepts(hunks: list[PatchHunk], *, finding_path: str) -> bool:
    """Whether this patch is the kind of thing that could be a fix."""
    return refusal_for(hunks, finding_path=finding_path) is None
