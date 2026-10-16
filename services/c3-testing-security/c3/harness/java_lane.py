"""The Java lane: the Maven Wrapper, JUnit 5, JaCoCo and PIT.

The wrapper rather than `mvn`, because Maven is not installed on the machine
this is developed on and the wrapper is how a Java project is built anyway: the
script fetches Maven on its first run, into the sandbox's own home, and every
run after that is warm.

Three shapes are parsed here and all three are XML, which is the older half of
this component. They are read with the standard library rather than with a
hardened parser because the input is a file a tool this harness just ran wrote
into a directory this harness made: a report that arrived from anywhere else
would be a different problem than parsing.

The statuses are where the honesty rules live. PIT's `TIMED_OUT` is a killed
mutant (an infinite loop is detected behaviour) and `NO_COVERAGE` is a survivor
(no test looked, which is what surviving means), while `MEMORY_ERROR`,
`RUN_ERROR` and `NON_VIABLE` are none of the above and are counted separately
rather than quietly folded into either.
"""

import re
import xml.etree.ElementTree as ElementTree
from pathlib import Path

from sdlc_contracts import CoverageEntry, MutationResult, TestCase, TestSuite

from .report import Attribution, Authored, LaneRun, MutationOutcome, TestKills, origin_of
from .sandbox import Sandbox, Step, StepResult
from .targets import TargetRepo

#: The wrapper script the sample carries. Relative, and run as `./mvnw`,
#: because that is what it is: a script in the project, not a tool on the box.
WRAPPER = "./mvnw"

#: A cold first run fetches Maven itself and then every plugin, which on a slow
#: connection is minutes. The cap is for hangs.
BUILD_TIMEOUT_SECONDS = 1500.0

#: One test method on its own, on a warm cache. The cap is for a hang, and for
#: a mutant that turned a loop into one that does not end.
ONE_TEST_TIMEOUT_SECONDS = 300.0
MUTATION_TIMEOUT_SECONDS = 1500.0

#: Where the tools write, with the wrapper's own defaults.
SUREFIRE_DIR = "target/surefire-reports"
JACOCO_XML = "target/site/jacoco/jacoco.xml"
PIT_XML = "target/pit-reports/mutations.xml"

#: PIT's statuses, sorted into the three this component reports.
_KILLED = {"KILLED", "TIMED_OUT"}
_SURVIVED = {"SURVIVED", "NO_COVERAGE"}


def build_and_test(
    repo: TargetRepo, sandbox: Sandbox, *, authored: Authored | None = None
) -> LaneRun:
    """Compile and run the suite, with the coverage agent attached.

    `-B` for a log a parser can read and a human can page. The exit status is
    not what decides whether the tests ran: the sample tells surefire not to
    fail the build on a failing test, because a failing test is this
    component's input rather than its error, and what settles the question is
    whether the reports are there.
    """
    step = sandbox.run(
        Step(
            name="tests",
            command=(WRAPPER, "-B", "test"),
            cwd=repo.app_dir,
            timeout=BUILD_TIMEOUT_SECONDS,
        )
    )
    run = LaneRun(steps=[step])
    run.suites = read_surefire(repo, sandbox, authored=authored)
    coverage = sandbox.read(str(Path(repo.app_dir) / JACOCO_XML))
    if coverage:
        run.coverage = parse_jacoco(coverage, repo)
    return run


def run_mutation(
    repo: TargetRepo, sandbox: Sandbox, scope: list[str], *, suite_is_green: bool
) -> MutationOutcome:
    """Mutants over the named classes only.

    `scope` arrives as repository paths, because that is what the rest of the
    report speaks, and is turned into the class names PIT wants. Scoped for the
    reasons the node lane is scoped: this machine cannot afford the whole
    project, and the honesty guard wants mutants where a test looks.

    PIT will run against a red suite and report nonsense, so unlike Stryker it
    has to be stopped here: a mutant is detected by turning a green test red,
    and a test that is already red says nothing about one.
    """
    if not suite_is_green:
        step = StepResult(
            name="mutation",
            command=f"{WRAPPER} pitest",
            outcome="not-run",
            output="the suite is not green",
        )
        return MutationOutcome(
            step=step,
            skipped_reason=(
                "the suite has failing tests, and a mutant is detected by turning a "
                "green test red, so mutation cannot say anything until they pass"
            ),
        )

    classes = sorted({name for name in (class_name(path) for path in scope) if name})
    if not classes:
        step = StepResult(
            name="mutation",
            command=f"{WRAPPER} pitest",
            outcome="not-run",
            output="no classes in scope",
        )
        return MutationOutcome(
            step=step,
            skipped_reason="no Java classes were in scope, so there was nothing to mutate",
        )

    step = sandbox.run(
        Step(
            name="mutation",
            command=(
                WRAPPER,
                "-B",
                "org.pitest:pitest-maven:mutationCoverage",
                f"-DtargetClasses={','.join(classes)}",
                # Without this, PIT stops at the first killing test and records
                # only that one, so every other covering test reads as a test
                # that kills nothing. With it, `killingTests`, `succeedingTests`
                # and `coveringTests` are all populated and the singular
                # `killingTest` goes empty. Verdicts are unchanged: the same 19
                # mutants and the same 10 kills either way.
                #
                # PIT calls this "a partially supported feature added due to
                # demand from the research community" and warns that other
                # features are not guaranteed to work with it enabled, which is
                # worth knowing before anything else in this lane depends on it.
                "-DfullMutationMatrix=true",
            ),
            cwd=repo.app_dir,
            timeout=MUTATION_TIMEOUT_SECONDS,
        )
    )
    raw = sandbox.read(str(Path(repo.app_dir) / PIT_XML))
    if not raw:
        return MutationOutcome(
            step=step,
            skipped_reason=f"the mutation run {step.outcome} and left no report: {step.tail[-400:]}",
        )
    try:
        result = parse_pit(raw, repo, scope=scope, duration=step.duration_seconds)
        who = attribution(raw)
    except ElementTree.ParseError as error:
        return MutationOutcome(
            step=step, skipped_reason=f"the mutation report could not be read: {error}"
        )
    if result.total == 0:
        return MutationOutcome(
            step=step,
            skipped_reason="the mutation run produced no mutants for the classes in scope",
        )
    return MutationOutcome(step=step, result=result, attribution=who)


# ------------------------------------------------------------------- parsing


def run_one(
    repo: TargetRepo, sandbox: Sandbox, *, suite_path: str, test_name: str
) -> tuple[StepResult, str]:
    """One test method, run on its own, and what it did.

    The Java side of what the honesty guard works in. `-Dtest=Class#method` is
    surefire's own selector, and `-DfailIfNoTests=false` matters: a selector
    that matches nothing would otherwise fail the build, and "the runner never
    reached it" is a different answer from "the test failed".

    The name arrives as the report writes it, `Class.method`, because that is
    what a reader sees; surefire wants `Class#method`.
    """
    method = test_name.rsplit(".", 1)[-1]
    selector = f"{_class_of(suite_path)}#{method}"
    step = sandbox.run(
        Step(
            name=f"one test: {selector[:60]}",
            command=(
                WRAPPER,
                "-B",
                "test",
                f"-Dtest={selector}",
                "-DfailIfNoTests=false",
                # The coverage agent and the report are the run stage's work,
                # and attaching them here would triple the cost of a check that
                # happens once per candidate fault.
                "-Djacoco.skip=true",
            ),
            cwd=repo.app_dir,
            timeout=ONE_TEST_TIMEOUT_SECONDS,
        )
    )
    for suite in read_surefire(repo, sandbox):
        for case in suite.cases:
            if case.name.rsplit(".", 1)[-1] == method:
                return step, case.outcome
    return step, "not-run"


def _class_of(suite_path: str) -> str:
    """The fully qualified class a test file holds, by Maven's own layout."""
    for root in ("src/test/java/", "src/main/java/"):
        if root in suite_path:
            after = suite_path.split(root, 1)[1]
            return after.removesuffix(".java").replace("/", ".")
    return suite_path.rsplit("/", 1)[-1].removesuffix(".java")


def source_under_test(suite_path: str) -> str:
    """The production file a test class is named for.

    Maven's convention, which is the only thing available: `TotalsTest` tests
    `Totals`. A test whose name does not follow it gets nothing, and the guard
    says the code it watches could not be found rather than breaking a file at
    random.
    """
    qualified = _class_of(suite_path)
    simple = qualified.rsplit(".", 1)[-1]
    for suffix in ("Test", "Tests", "IT"):
        if simple.endswith(suffix) and len(simple) > len(suffix):
            under = qualified[: -len(suffix)]
            return source_path(under, test=False)
    return ""


def read_surefire(
    repo: TargetRepo, sandbox: Sandbox, *, authored: Authored | None = None
) -> list[TestSuite]:
    """Every `TEST-*.xml` surefire wrote, as suites.

    One file per test class, so the files are found rather than named: a class
    that failed to load still leaves one, and a run that never reached a class
    leaves none, which is the difference this component keeps.
    """
    directory = repo.root / repo.app_dir / SUREFIRE_DIR
    if not directory.is_dir():
        return []
    suites: list[TestSuite] = []
    for report in sorted(directory.glob("TEST-*.xml")):
        raw = report.read_text(errors="replace")
        try:
            suites.extend(parse_surefire(raw, repo, authored=authored))
        except ElementTree.ParseError:
            # A half written report is not a suite of zero tests.
            continue
    return suites


def parse_surefire(
    raw: str, repo: TargetRepo, *, authored: Authored | None = None
) -> list[TestSuite]:
    """One surefire file, as one suite.

    The path is derived from the class name rather than read from the report,
    because surefire names a class and every other path in a test report names
    a file. `com.example.records.TotalsTest` is
    `src/test/java/com/example/records/TotalsTest.java`, which is where it is.
    """
    root = ElementTree.fromstring(raw)
    suite_name = root.get("name") or "unknown"
    path = source_path(suite_name, test=True)
    cases: list[TestCase] = []
    for element in root.iter("testcase"):
        classname = element.get("classname") or suite_name
        name = element.get("name") or "unnamed test"
        outcome = "passed"
        message = ""
        for kind, mapped in (("failure", "failed"), ("error", "errored"), ("skipped", "skipped")):
            found = element.find(kind)
            if found is not None:
                outcome = mapped
                message = (found.get("message") or found.text or "").strip()
                break
        if outcome in ("failed", "errored") and not message:
            message = "surefire reported it as failed and said nothing else"
        cases.append(
            TestCase(
                id=f"{classname}#{name}",
                name=f"{classname.rsplit('.', 1)[-1]}.{name}",
                outcome=outcome,  # type: ignore[arg-type]
                duration_seconds=_seconds(element.get("time")),
                message=message,
                origin=origin_of(path, authored),  # type: ignore[arg-type]
            )
        )
    return [TestSuite(path=path, framework="junit5", cases=cases)]


def parse_jacoco(raw: str, repo: TargetRepo) -> list[CoverageEntry]:
    """JaCoCo's XML report, per source file, with the counts kept.

    JaCoCo counts what it missed and what it covered; the contract wants the
    covered count and the total, so the total is the sum. The report's own
    aggregate counters are ignored for the reason the node lane ignores
    Istanbul's: two totals that can disagree is one too many.
    """
    root = ElementTree.fromstring(raw)
    entries: list[CoverageEntry] = []
    for package in root.iter("package"):
        package_path = (package.get("name") or "").strip("/")
        for source in package.iter("sourcefile"):
            counters = {
                counter.get("type"): counter
                for counter in source.findall("counter")
                if counter.get("type")
            }
            lines = counters.get("LINE")
            branches = counters.get("BRANCH")
            if lines is None:
                continue
            covered = int(lines.get("covered") or 0)
            missed = int(lines.get("missed") or 0)
            branch_covered = int(branches.get("covered") or 0) if branches is not None else 0
            branch_missed = int(branches.get("missed") or 0) if branches is not None else 0
            name = source.get("name") or "unknown"
            entries.append(
                CoverageEntry(
                    module=f"src/main/java/{package_path}/{name}" if package_path else name,
                    lines_covered=covered,
                    lines_total=covered + missed,
                    branches_covered=branch_covered,
                    branches_total=branch_covered + branch_missed,
                )
            )
    return sorted(entries, key=lambda entry: entry.module)


def parse_pit(raw: str, repo: TargetRepo, *, scope: list[str], duration: float) -> MutationResult:
    """PIT's `mutations.xml`, as killed, survived and undecided.

    Ids are `file:line:mutator#index`, the same shape the node lane produces
    plus PIT's own index, so the two stacks' reports can be read by one reader
    and one frontend. The index is not decoration: the sample alone has five
    pairs of mutants that share a file, a line and a mutator, and without it
    they would collapse into one another in a set.
    """
    root = ElementTree.fromstring(raw)
    killed: list[str] = []
    survived: list[str] = []
    inconclusive: list[str] = []
    for mutation in root.iter("mutation"):
        mutated_class = _text(mutation, "mutatedClass")
        line = _text(mutation, "lineNumber") or "0"
        mutator = (_text(mutation, "mutator") or "mutant").rsplit(".", 1)[-1]
        index = _first_index(mutation)
        identifier = f"{source_path(mutated_class, test=False)}:{line}:{mutator}#{index}"
        status = (mutation.get("status") or "").upper()
        if status in _KILLED:
            killed.append(identifier)
        elif status in _SURVIVED:
            survived.append(identifier)
        else:
            inconclusive.append(identifier)
    return MutationResult(
        tool="pitest 1.19.1 with the junit5 plugin 1.2.2",
        scope=sorted(scope),
        killed=sorted(killed),
        survived=sorted(survived),
        inconclusive=sorted(inconclusive),
        duration_seconds=duration,
    )


# ------------------------------------------------------------------- naming


#: How PIT names a test: `com.example.RecordsTest.[engine:junit-jupiter]/`
#: `[class:com.example.RecordsTest]/[method:adds_two()]`. The class and the
#: method are what the report's own case ids are built from.
_PIT_TEST = re.compile(r"\[class:(?P<cls>[^\]]+)\]/\[method:(?P<method>[^\](]+)")


def attribution(raw: str) -> Attribution:
    """Which test covered and killed which mutant, by the report's own case ids.

    Reads the full mutation matrix, which the mutation step asks PIT for.
    Without it `coveringTests` is absent and nothing here can be answered.
    """
    root = ElementTree.fromstring(raw)
    covered: dict[str, list[str]] = {}
    killed: dict[str, list[str]] = {}
    for mutation in root.iter("mutation"):
        mutated_class = _text(mutation, "mutatedClass")
        line = _text(mutation, "lineNumber") or "0"
        mutator = (_text(mutation, "mutator") or "mutant").rsplit(".", 1)[-1]
        index = _first_index(mutation)
        identifier = f"{source_path(mutated_class, test=False)}:{line}:{mutator}#{index}"
        for tag, into in (("coveringTests", covered), ("killingTests", killed)):
            for name in _test_ids(_text(mutation, tag)):
                into.setdefault(name, []).append(identifier)
    return {
        name: TestKills(
            covered=tuple(sorted(covered.get(name, ()))),
            killed=tuple(sorted(killed.get(name, ()))),
        )
        for name in {*covered, *killed}
    }


def _test_ids(value: str) -> list[str]:
    """PIT's pipe separated test list, as `class#method` ids."""
    found: list[str] = []
    for part in value.split("|"):
        match = _PIT_TEST.search(part)
        if match:
            found.append(f"{match.group('cls')}#{match.group('method')}")
    return found


def source_path(class_name: str, *, test: bool) -> str:
    """Where Maven's layout says a class lives.

    A convention rather than a lookup, and it is the convention every Maven
    project follows. An inner class (`Totals$Line`) is its outer file.
    """
    if not class_name:
        return "unknown"
    outer = class_name.split("$", 1)[0]
    root = "src/test/java" if test else "src/main/java"
    return f"{root}/{outer.replace('.', '/')}.java"


def class_name(path: str) -> str:
    """The class a source path holds, or nothing if it is not Java source.

    The inverse of `source_path`, for turning the scope the report speaks in
    into what PIT's `targetClasses` wants.
    """
    for root in ("src/main/java/", "src/test/java/"):
        if root in path and path.endswith(".java"):
            after = path.split(root, 1)[1]
            return after[: -len(".java")].replace("/", ".")
    return ""


def _seconds(value: str | None) -> float:
    try:
        return round(float(value or 0), 4)
    except ValueError:
        return 0.0


def _first_index(mutation: ElementTree.Element) -> str:
    """PIT's own index for a mutant, which is what tells two apart."""
    indexes = mutation.find("indexes")
    if indexes is None:
        return "0"
    for child in indexes:
        if child.text and child.text.strip():
            return child.text.strip()
    return "0"


def _text(element: ElementTree.Element, tag: str) -> str:
    found = element.find(tag)
    return (found.text or "").strip() if found is not None and found.text else ""
