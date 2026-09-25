"""What is wrong with the tests themselves.

A pass rate says whether the suite is green. It says nothing about whether the
suite is worth anything, and the two most common reasons it is not are a test
that asserts nothing and a test that only passes when it runs first. Neither
shows up in any number the run stage produces, so they are found and reported
separately.

Two kinds of finding, and the report says which is which. Most are read out of
the source, using the same detectors the model fill is held to: what this
component refuses to write, it also refuses to stay quiet about in tests it did
not write. Two are observed, because they cannot be read. Order dependence is
found by running the suite again in a different order and comparing what
happened. And a test that kills no mutant is found from the mutation run the
quality stage already does: it is the strongest of the three, because it
catches an assertion that reads perfectly and cannot fail, which no pattern
over the source could tell from one that can.

The catalogue covers tests whoever wrote them. A finding against a test the
code generator shipped is as useful as one against a test the model wrote, and
excluding the first would make the list flattering.
"""

import re
from dataclasses import dataclass

from sdlc_contracts import QualityFinding, TestSuite

from .generate.fill import ASSERTION, UNREPEATABLE, VACUOUS, bodies, declared_names
from .harness import Sandbox, TargetRepo
from .harness import node_lane as lane
from .harness.report import Attribution

#: Which rule each of the fill's unrepeatability patterns reports as. The
#: patterns live with the fill because that is where they are enforced; the
#: names live here because that is where they are reported.
_RULE_FOR = {
    "unseeded randomness": "unseeded-randomness",
    "a sleep": "sleep",
    "and nothing else": "network",
    "depend on when it runs": "wall-clock",
}

_ONLY_LINE = re.compile(r"\b(?:it|describe|test)\.only\b")


@dataclass(frozen=True)
class OrderCheck:
    """What a second, shuffled run said, and whether it could be compared."""

    ran: bool
    reason: str = ""


def _rule_of(why: str) -> str:
    for needle, rule in _RULE_FOR.items():
        if needle in why:
            return rule
    return "sleep"


def read_findings(repo: TargetRepo) -> list[QualityFinding]:
    """Everything that can be seen without running anything.

    Reads every test file under each app, whoever wrote it.
    """
    found: list[QualityFinding] = []
    for app in repo.apps:
        root = repo.root / app / "src"
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.test.ts")) + sorted(root.rglob("*.test.tsx")):
            try:
                source = path.read_text(errors="replace")
            except OSError:
                continue
            found.extend(_findings_in(repo.relative(path), source))
    return found


def _findings_in(path: str, source: str) -> list[QualityFinding]:
    found: list[QualityFinding] = []
    if _ONLY_LINE.search(source):
        found.append(
            QualityFinding(
                rule="focused",
                path=path,
                detail=(
                    "this file uses `.only`, which silently disables every other test in "
                    "it: the suite reports green having run one test"
                ),
            )
        )
    for name, body in bodies(source).items():
        if not ASSERTION.search(body):
            found.append(
                QualityFinding(
                    rule="no-assertion",
                    path=path,
                    test=name,
                    detail="this test asserts nothing, so there is no program it could fail on",
                )
            )
        for pattern, why in VACUOUS:
            if pattern.search(body):
                found.append(
                    QualityFinding(
                        rule="vacuous-assertion",
                        path=path,
                        test=name,
                        detail=f"this test asserts {why}, which holds for every program",
                    )
                )
                break
        for pattern, why in UNREPEATABLE:
            if pattern.search(body):
                found.append(
                    QualityFinding(
                        rule=_rule_of(why),  # type: ignore[arg-type]
                        path=path,
                        test=name,
                        detail=why,
                    )
                )
                break
    return found


def order_findings(
    repo: TargetRepo, sandbox: Sandbox, baseline: list[TestSuite]
) -> tuple[list[QualityFinding], OrderCheck]:
    """The suite again, shuffled, compared case by case.

    A test whose outcome depends on what ran before it is a test that will one
    day fail on somebody else's machine for no reason anybody can find. It
    cannot be read out of a file: the only way to know is to run the suite in a
    different order and see whether anything moved.

    Returns the findings and whether the comparison could be made at all. A
    second run that did not happen is reported as not having happened, rather
    than as a suite with no order dependence in it.
    """
    if not baseline:
        return [], OrderCheck(ran=False, reason="the first run reported on no tests")

    shuffled = lane.run_tests(repo, sandbox, shuffle=True)
    if not shuffled.ran:
        return [], OrderCheck(
            ran=False,
            reason=f"the shuffled run reported on no tests ({shuffled.steps[-1].outcome})",
        )

    first = {case.id: case.outcome for suite in baseline for case in suite.cases}
    second = {case.id: case.outcome for suite in shuffled.suites for case in suite.cases}
    findings: list[QualityFinding] = []
    for suite in baseline:
        for case in suite.cases:
            was = first.get(case.id)
            now = second.get(case.id)
            if now is None or was == now:
                continue
            findings.append(
                QualityFinding(
                    rule="order-dependent",
                    path=suite.path,
                    test=case.name,
                    detail=(
                        f"this test {was} in the order the suite is written and {now} when "
                        "the order was shuffled, so what it reports depends on what ran "
                        "before it"
                    ),
                    observed=True,
                )
            )
    return findings, OrderCheck(ran=True)


#: How many surviving mutants a finding names before it stops listing them.
#: Enough for a reader to go and look, and for a refill to have something to
#: aim at, without putting a mutation report inside a sentence.
NAMED_MUTANTS = 3


def attribution_is_usable(mutation: object | None) -> tuple[bool, str]:
    """Whether a mutation run can be asked which tests kill nothing.

    A run in which nothing died cannot tell a suite that asserts nothing from a
    runner that never activated a mutant, and the second happens: Stryker 10's
    vitest runner does exactly that against vitest 5, reporting a green suite,
    most mutants uncovered and a score of zero. Accusing every test in the
    suite because of somebody else's bug is the failure this refuses.
    """
    if mutation is None:
        return False, "no mutation run, so no test was asked whether it kills anything"
    killed = getattr(mutation, "killed", ())
    if not killed:
        total = getattr(mutation, "total", 0)
        return False, (
            f"the mutation run produced {total} mutants and killed none, which is either "
            "a suite that asserts nothing or a runner that never activated a mutant. "
            "Nothing is accused until that is settled"
        )
    return True, ""


def mutant_findings(suites: list[TestSuite], attribution: Attribution) -> list[QualityFinding]:
    """Tests that run the code and would not notice if it changed.

    The observation a pass rate cannot make and the source catalogue cannot
    see: this test executed that code, and every mutant it touched survived it.
    The classic case is an assertion that cannot fail, `toBeDefined()` where the
    criterion asked for a value, which reads perfectly well and measures
    nothing.

    Named for the observation rather than the author. The same fact about a
    test a model wrote is a weak fill, and about a test that came with the
    repository it is a gap the repository already had; the counts keep them
    apart, and the rule stays true of both.

    A test covering nothing is not here. The mutation run is scoped, so a test
    exercising code outside that scope was never asked the question, and
    accusing it would be reporting an absence of evidence as evidence.
    """
    findings: list[QualityFinding] = []
    for suite in suites:
        for case in suite.cases:
            kills = attribution.get(case.id)
            if kills is None or not kills.weak:
                continue
            named = ", ".join(kills.covered[:NAMED_MUTANTS])
            more = len(kills.covered) - NAMED_MUTANTS
            findings.append(
                QualityFinding(
                    rule="kills-no-mutant",
                    path=suite.path,
                    test=case.name,
                    detail=(
                        f"this test covers {len(kills.covered)} mutant(s) and kills none, so "
                        "the code it runs could change and it would still pass: "
                        f"{named}" + (f" and {more} more" if more > 0 else "")
                    ),
                    observed=True,
                )
            )
    return findings


def weak_by_origin(suites: list[TestSuite], attribution: Attribution) -> dict[str, int]:
    """How many tests kill nothing, per arm, out of how many were measured.

    Per arm because that is the comparison the study makes: a weak fill is a
    number about the model, and the same number about the tests the repository
    arrived with is a number about the code generator. Reported as
    `weak/measured` pairs so a reader can see the denominator: three weak out
    of four measured is not three weak out of forty.
    """
    counts: dict[str, int] = {}
    for suite in suites:
        for case in suite.cases:
            kills = attribution.get(case.id)
            if kills is None or not kills.covered:
                continue
            counts.setdefault(f"{case.origin} measured", 0)
            counts[f"{case.origin} measured"] += 1
            if kills.weak:
                counts.setdefault(f"{case.origin} weak", 0)
                counts[f"{case.origin} weak"] += 1
    return dict(sorted(counts.items()))


def unwritten(repo: TargetRepo) -> int:
    """How many declared tests are still `todo` across the target.

    Not a finding: a declared and unwritten test is an honest state, and the
    report already counts it as a skip. Counted so the summary can say it out
    loud, because a suite of ten tests where six are declarations reads very
    differently from one where none are.
    """
    total = 0
    for app in repo.apps:
        root = repo.root / app / "src"
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.test.ts")):
            try:
                total += len(declared_names(path.read_text(errors="replace")))
            except OSError:
                continue
    return total
