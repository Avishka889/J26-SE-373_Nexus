"""Does this test notice when the code under it is wrong?

The whole honesty guard reduces to this question, and so does the weak fill
gate: one asks it of a test that was just repaired, the other of a test that was
just written. The answer is evidence, not opinion, and it is the only one of the
three guard checks that a weakened assertion cannot pass.

The procedure is small on purpose. Run the test once to see it green, then break
one thing in the production code it is supposed to be watching and run it again.
Red means it noticed. Green means it did not, and the next candidate fault is
tried, because a test can miss one fault and catch another and the question is
whether it catches any.

Two outcomes that are not "survived" and must not be counted as one. A mutant
that does not compile was never evaluated: nobody learned anything, and the run
moves on. And a test that was not green to begin with cannot demonstrate
anything at all, so the check says so rather than guessing.

The file is always put back. A guard that left a deliberate fault in the
repository would be worse than no guard.
"""

import logging
import re
from collections.abc import Collection
from dataclasses import dataclass, field

from ..harness import Sandbox, TargetRepo, java_lane, node_lane
from .mutants import MAX_ATTEMPTS, Mutant, candidates, inject

log = logging.getLogger(__name__)


#: A relative import in a test file. The code a test exercises is the code it
#: imports, which is the most direct answer available without running a
#: coverage pass per test.
_IMPORT = re.compile(r"""^\s*import\s[^"']*["'](\.{1,2}/[^"']+)["']""", re.MULTILINE)

#: The dynamic form, and the type form beside it. Every generated acceptance
#: test loads its app afresh before each case (`await import("../app.ts")`, its
#: exports typed as `typeof import("../app.ts")`), and with only the static
#: form read, the guard found no code under any of them.
_DYNAMIC_IMPORT = re.compile(r"""\bimport\(\s*["'](\.{1,2}/[^"']+)["']\s*\)""")

#: A module that passes another one's exports on (`export { x } from "./y"`).
_EXPORT_FROM = re.compile(r"""^\s*export\s[^"';]*\bfrom\s*["'](\.{1,2}/[^"']+)["']""", re.MULTILINE)

#: Test files, which are never the code a test is about.
_TEST_FILE = re.compile(r"(^|/)__tests__/|\.(test|spec)\.[cm]?[jt]sx?$")

#: How much of what a test reaches is followed. A test that loads the app
#: reaches its routes and repositories two or three imports down, and the bound
#: keeps one broad import from becoming the whole repository.
MAX_SOURCES = 40

#: What a specifier might resolve to, in the order a bundler would try.
_SUFFIXES = ("", ".ts", ".tsx", ".js", "/index.ts", "/index.tsx")


def _run_one(repo: TargetRepo, sandbox: Sandbox, *, suite_path: str, test_name: str):
    """One test, whichever lane the target is.

    The guard is lane agnostic; only the runner is not.
    """
    lane = java_lane if repo.stack == "java" else node_lane
    return lane.run_one(repo, sandbox, suite_path=suite_path, test_name=test_name)


def sources_under(repo: TargetRepo, suite_path: str) -> list[str]:
    """The production code this test exercises, as repository paths, nearest first.

    Two derivations, one per lane, and neither is a guess. A TypeScript test
    that imports `../total` is exercising `total`, so the imports are read, and
    followed: a test that loads the app reaches the routes the app mounts and
    the repositories they call, which is where its behaviour is. A Java test
    class follows Maven's naming, so `TotalsTest` tests `Totals`; a class that
    does not follow it yields nothing, and the guard says the code could not be
    found rather than breaking a file at random.
    """
    if repo.stack == "java":
        found = java_lane.source_under_test(suite_path)
        return [found] if found and repo.read(found) is not None else []
    found: list[str] = []
    seen = {suite_path}
    waiting = [suite_path]
    while waiting and len(found) < MAX_SOURCES:
        current = waiting.pop(0)
        source = repo.read(current)
        if source is None:
            continue
        directory = current.rsplit("/", 1)[0] if "/" in current else ""
        for specifier in _specifiers(source):
            resolved = _resolve(repo, directory, specifier)
            if resolved is None or resolved in seen:
                continue
            seen.add(resolved)
            if _TEST_FILE.search(resolved):
                continue
            found.append(resolved)
            waiting.append(resolved)
            if len(found) >= MAX_SOURCES:
                break
    return found


def _specifiers(source: str) -> list[str]:
    """Every relative module a file names, in the order it names them."""
    matches = [
        match
        for pattern in (_IMPORT, _DYNAMIC_IMPORT, _EXPORT_FROM)
        for match in pattern.finditer(source)
    ]
    return [match.group(1) for match in sorted(matches, key=lambda match: match.start())]


def _resolve(repo: TargetRepo, directory: str, specifier: str) -> str | None:
    """The file a relative specifier names, as a bundler would find it, or None."""
    base = specifier.removesuffix(".ts").removesuffix(".tsx").removesuffix(".js")
    for suffix in _SUFFIXES:
        candidate = _normalise(f"{directory}/{base}{suffix}")
        if candidate and repo.read(candidate) is not None:
            return candidate
    return None


def _normalise(path: str) -> str:
    """`a/b/../c` as `a/c`, without touching the filesystem."""
    parts: list[str] = []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


@dataclass(frozen=True)
class KillCheck:
    """What one test did when the code under it was broken."""

    killed: bool
    #: The fault it noticed, when it noticed one. This is what a reader is
    #: shown to justify accepting a repair.
    mutant: Mutant | None = None
    tried: int = 0
    #: Candidates that could not be evaluated, usually because the mutated form
    #: did not compile. Never counted as survivors.
    inconclusive: int = 0
    detail: str = ""
    #: Faults it did not notice, for the report and for a refill to aim at.
    survived: tuple[str, ...] = field(default_factory=tuple)


def kills_a_mutant(
    repo: TargetRepo,
    sandbox: Sandbox,
    *,
    suite_path: str,
    test_name: str,
    source_path: str,
    lines: Collection[int] | None = None,
    attempts: int = MAX_ATTEMPTS,
) -> KillCheck:
    """Break the code this test watches, and see whether it goes red.

    `lines` narrows the faults to the region the test is being asked about,
    which for a repaired test is the production code that changed between the
    two versions: that is what made it fail, so that is where it has to be
    looking.

    Fails closed. A check that could not be decided answers `killed=False`,
    because a guard that accepted a repair for want of a way to test it would
    not be a guard.
    """
    source = repo.read(source_path)
    if source is None:
        return KillCheck(
            killed=False,
            detail=f"{source_path} is not in the target, so nothing could be broken in it",
        )

    baseline_step, baseline = _run_one(repo, sandbox, suite_path=suite_path, test_name=test_name)
    if baseline != "passed":
        return KillCheck(
            killed=False,
            detail=(
                f"the test was {baseline} before anything was broken, so it cannot show that "
                f"it notices a fault ({baseline_step.outcome})"
            ),
        )

    found = candidates(source, path=source_path, lines=lines)
    if not found:
        return KillCheck(
            killed=False,
            detail=(
                f"nothing in {source_path}"
                + (f" on the {len(lines)} lines that changed" if lines else "")
                + " could be broken in a way that is certain to compile, so the test was "
                "never asked the question"
            ),
        )

    tried = 0
    inconclusive = 0
    survived: list[str] = []
    try:
        for mutant in found[:attempts]:
            tried += 1
            repo.write(source_path, inject(source, mutant))
            _, outcome = _run_one(repo, sandbox, suite_path=suite_path, test_name=test_name)
            if outcome in ("failed", "errored"):
                return KillCheck(
                    killed=True,
                    mutant=mutant,
                    tried=tried,
                    inconclusive=inconclusive,
                    survived=tuple(survived),
                    detail=f"the test noticed: {mutant.describe()}",
                )
            if outcome == "not-run":
                # The mutated form did not build, or the runner could not reach
                # the test. Nobody learned anything about the test from that.
                inconclusive += 1
                continue
            survived.append(mutant.id)
    finally:
        repo.write(source_path, source)

    if survived:
        return KillCheck(
            killed=False,
            tried=tried,
            inconclusive=inconclusive,
            survived=tuple(survived),
            detail=(
                f"the test stayed green through {len(survived)} deliberate faults in "
                f"{source_path}, so it is running that code and watching nothing"
            ),
        )
    return KillCheck(
        killed=False,
        tried=tried,
        inconclusive=inconclusive,
        detail=(
            f"none of the {tried} candidate faults in {source_path} could be evaluated, so "
            "whether this test notices anything is unknown, and unknown is not accepted"
        ),
    )
