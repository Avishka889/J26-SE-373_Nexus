"""The MERN lane: install, run, cover, mutate, and report what happened.

Every flag in here was checked against the tools as installed rather than
remembered, and two of them are the kind of detail that quietly produces a
wrong number.

**`--coverage.reportOnFailure`.** Vitest writes no coverage report at all when
a test fails, and a failing suite is this component's normal case: the healing
loop exists because tests fail. Without that flag the coverage of every
interesting run is silently absent, which reads as zero.

**The measurement tools are declared, not slipped in.** Coverage and mutation
are things this harness needs rather than things the project asked for, and the
first version added them with `npm install --no-save` so the manifest stayed
exactly as the code generator wrote it. npm does not support that at the root
of a workspace: see `declare_measurement_tools` for the three ways it fails.
They are written into the workspace copy's manifest instead, which is a scratch
directory this component materialised; the stored files, and therefore the
repository a person clones, are untouched.

The tools are pinned and reported: a mutation score with no tool version on it
cannot be compared with next month's.
"""

import json
import re
import time
from collections.abc import Callable
from pathlib import Path

from sdlc_contracts import CoverageEntry, MutationResult, TestCase, TestSuite, UnmeasuredApp

from .report import Attribution, Authored, LaneRun, MutationOutcome, TestKills, origin_of
from .sandbox import Sandbox, Step, StepResult
from .targets import TargetRepo

#: Where this harness puts what it produces, inside the workspace. One
#: directory so a workspace can be swept clean of measurement output without
#: touching the project.
REPORT_DIR = ".c3"

#: Pinned, because the versions are part of every number's provenance. Stryker
#: 10 requires Node 22 or newer, which this machine has.
STRYKER_VERSION = "10.0.0"

#: Long enough for a real mutation pass on a scoped file set, and no longer:
#: a run that has not finished in twenty minutes has found a hang, not a slow
#: machine. One budget for the whole pass, shared by the apps it runs in: every
#: testing stage beats the run's heartbeat once, at its start, and a run silent
#: past C3's twenty minute window is reclaimed and failed, so a pass per app
#: with twenty minutes each could fail the run mid mutation.
MUTATION_TIMEOUT_SECONDS = 1200.0
#: Less time than this left, and starting Stryker would only time out.
MUTATION_MINIMUM_SECONDS = 60.0

#: Where a mutation run keeps its copies of the project. Excluded from every
#: collection: a killed run leaves it behind, and the suites inside it would be
#: collected and counted a second time.
STRYKER_TEMP = "**/.stryker-tmp/**"

#: One test on its own is seconds. The cap is for a hang, and for a mutant that
#: turned a loop into one that does not end, which is a thing mutants do.
ONE_TEST_TIMEOUT_SECONDS = 120.0

#: One at a time. Five point eight gigabytes of RAM does not run four node
#: workers and a JVM, and the mutation pass is the one that would try.
MUTATION_CONCURRENCY = "1"


def vitest_range(repo: TargetRepo) -> str:
    """The vitest the project asks for, as it asks for it.

    Read out of the app's own manifest rather than resolved, so the root ends
    up asking for the same range the member does and npm can settle on one
    copy. A project with no vitest at all returns nothing, and the caller says
    that rather than installing a test runner the project never wanted.
    """
    manifest = repo.read(str(Path(repo.app_dir) / "package.json"))
    if not manifest:
        return ""
    try:
        declared = json.loads(manifest)
    except json.JSONDecodeError:
        return ""
    for section in ("devDependencies", "dependencies"):
        found = (declared.get(section) or {}).get("vitest")
        if isinstance(found, str) and found:
            return found
    return ""


def declare_measurement_tools(repo: TargetRepo) -> dict[str, str]:
    """Write the tools this harness needs into the workspace copy's manifest.

    Not `npm install --no-save`, which is what this did first and what the
    comment here used to defend. Three things were learned by watching npm fail
    against a real generated monorepo, and the third is the reason for the
    shape of this function.

    An unsaved add at the root of a workspace crashes npm with "Cannot read
    properties of null (reading 'edgesOut')". Installing the three packages one
    at a time instead makes each call succeed and each call prune the one
    before it, because an unsaved package is not in the manifest the next call
    recomputes the tree from. And declaring all three in the manifest still
    crashes, until `vitest` is declared at the root beside them: the mutation
    runner has a peer dependency on vitest, the workspace members are where
    vitest lives, and npm cannot resolve a peer across that link.

    So the tools are declared, with vitest at the root beside them, and one
    ordinary install follows. What is edited is the workspace copy, which is a
    scratch directory this component wrote from the file store; the stored
    files are untouched, and the manifest in the repository still says exactly
    what the code generator wrote.
    """
    vitest = vitest_range(repo)
    if not vitest:
        return {}
    tools = {
        # The root asks for what the member asks for, so npm settles on one
        # copy rather than two that cannot see each other.
        "vitest": vitest,
        "@vitest/coverage-v8": vitest,
        "@stryker-mutator/core": STRYKER_VERSION,
        "@stryker-mutator/vitest-runner": STRYKER_VERSION,
    }
    raw = repo.read("package.json") or "{}"
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError:
        manifest = {}
    development = manifest.setdefault("devDependencies", {})
    added = {name: spec for name, spec in tools.items() if development.get(name) != spec}
    development.update(tools)
    repo.write("package.json", json.dumps(manifest, indent=2) + "\n")
    return added


def install(repo: TargetRepo, sandbox: Sandbox) -> StepResult:
    """Dependencies, from the workspace root, with no lifecycle scripts.

    At the root rather than in the app: this is an npm workspace, and
    installing inside `apps/web` would install the app's dependencies twice
    and its siblings' not at all.
    """
    return sandbox.run(
        Step(
            name="install",
            command=("npm", "install", "--no-audit", "--no-fund"),
            cwd=".",
        )
    )


def installed_version(repo: TargetRepo, sandbox: Sandbox, package: str) -> str:
    """What version of a package the workspace actually resolved.

    Asked rather than assumed, because every number this component reports is
    stamped with the tool that produced it and a range is not a version.
    """
    result = sandbox.run(
        Step(
            name=f"{package} version",
            command=("node", "-p", f"require('{package}/package.json').version"),
            cwd=repo.app_dir,
            timeout=60,
        )
    )
    return result.output.strip() if result.passed else ""


#: A fixed seed, so the shuffled run is a different order and the same
#: different order every time. A check for order dependence that shuffled
#: differently on each run would itself be flaky, which is the thing it exists
#: to find.
SHUFFLE_SEED = "20260829"


def run_tests(
    repo: TargetRepo,
    sandbox: Sandbox,
    *,
    authored: Authored | None = None,
    shuffle: bool = False,
) -> LaneRun:
    """The suite, once per app, with coverage, reported as JSON.

    Once per app because a monorepo has more than one runner and each has its
    own config: the web app wants jsdom and the API does not, and one run at
    the workspace root would apply neither. The reports are merged, and every
    path in them is named from the repository root, so a reader sees one suite
    list rather than one per directory.

    The exit status is not consulted for the outcome of the tests: vitest exits
    non zero on a red suite, which is a result rather than a failure of the
    step. What decides whether this ran at all is whether the report is there.
    """
    run = LaneRun()
    for app in repo.apps:
        reports = Path(REPORT_DIR)
        step = sandbox.run(
            Step(
                name=_run_name(app, repo, shuffle),
                command=(
                    "npx",
                    "vitest",
                    "run",
                    "--reporter=json",
                    f"--outputFile={reports / 'vitest.json'}",
                    "--coverage",
                    "--coverage.provider=v8",
                    # Without this, a failing suite produces no coverage at all.
                    "--coverage.reportOnFailure",
                    "--coverage.reporter=json-summary",
                    f"--coverage.reportsDirectory={reports / 'coverage'}",
                    # A target with no tests yet is a fact to report, not a crash.
                    "--passWithNoTests",
                    # A mutation pass that was killed leaves its sandbox behind,
                    # and vitest would collect the copies of every suite inside
                    # it: the same tests, counted twice, from a directory nobody
                    # edits.
                    f"--exclude={STRYKER_TEMP}",
                    "--exclude=**/node_modules/**",
                    *(("--sequence.shuffle", f"--sequence.seed={SHUFFLE_SEED}") if shuffle else ()),
                ),
                cwd=app,
            )
        )
        run.steps.append(step)

        raw = sandbox.read(str(Path(app) / reports / "vitest.json"))
        if raw:
            run.suites.extend(parse_vitest(raw, repo, authored=authored))
        summary = sandbox.read(str(Path(app) / reports / "coverage" / "coverage-summary.json"))
        if summary:
            run.coverage.extend(parse_coverage(summary, repo))

    seen: set[str] = set()
    merged: list[TestSuite] = []
    for suite in run.suites:
        # A suite collected by two apps is one suite: the runners overlap at
        # the root, and counting a file twice would double its cases.
        if suite.path in seen:
            continue
        seen.add(suite.path)
        merged.append(suite)
    run.suites = merged
    run.coverage = _merge_coverage(run.coverage)
    return run


def _run_name(app: str, repo: TargetRepo, shuffle: bool) -> str:
    label = "tests in a shuffled order" if shuffle else "tests"
    return f"{label} ({app})" if len(repo.apps) > 1 else label


def _merge_coverage(entries: list[CoverageEntry]) -> list[CoverageEntry]:
    """One row per module, keeping the run that saw the most of it.

    Two apps can both report on a shared package. Adding the numbers would
    invent lines that do not exist, so the better measurement wins and the
    other is dropped.
    """
    best: dict[str, CoverageEntry] = {}
    for entry in entries:
        current = best.get(entry.module)
        if current is None or entry.lines_covered > current.lines_covered:
            best[entry.module] = entry
    return sorted(best.values(), key=lambda entry: entry.module)


def run_one(
    repo: TargetRepo, sandbox: Sandbox, *, suite_path: str, test_name: str
) -> tuple[StepResult, str]:
    """One test, run on its own, and what it did.

    The unit the honesty guard works in: inject a fault, ask one test whether it
    noticed, put the file back. Running the suite would answer a slower and
    different question, and would drag every other failing test into an answer
    about this one.

    Returns the step and the outcome of the named case, which is `not-run` when
    the runner never reached it. A runner that reports nothing about a test it
    was asked to run has not told us the test passed.
    """
    app = repo.app_for(suite_path)
    reports = Path(REPORT_DIR)
    inside = suite_path[len(app) + 1 :] if app != "." and suite_path.startswith(app) else suite_path
    step = sandbox.run(
        Step(
            name=f"one test: {test_name[:60]}",
            command=(
                "npx",
                "vitest",
                "run",
                inside,
                # A regex, so a test called `a + b` is not a pattern.
                "--testNamePattern",
                re.escape(test_name),
                "--reporter=json",
                f"--outputFile={reports / 'one.json'}",
                "--passWithNoTests",
                f"--exclude={STRYKER_TEMP}",
                "--exclude=**/node_modules/**",
            ),
            cwd=app,
            timeout=ONE_TEST_TIMEOUT_SECONDS,
        )
    )
    raw = sandbox.read(str(Path(app) / reports / "one.json"))
    if not raw:
        return step, "not-run"
    for suite in parse_vitest(raw, repo):
        for case in suite.cases:
            if case.name == test_name:
                return step, case.outcome
    return step, "not-run"


def app_of(repo: TargetRepo, path: str) -> str:
    """The app a file belongs to, for a command that has to run somewhere."""
    return next(
        (one for one in repo.apps if path.startswith(f"{one}/")), repo.apps[0] if repo.apps else ""
    )


#: A TypeScript diagnostic, as `tsc` prints it: `path(line,col): error TSxxxx: ...`.
_DIAGNOSTIC = re.compile(r"^(?P<path>[^(\s][^(]*)\((?P<line>\d+),\d+\): (?P<rest>error .*)$")


def typecheck(repo: TargetRepo, sandbox: Sandbox, path: str) -> tuple[StepResult, list[str]]:
    """Whether the compiler accepts a file, and what it said about that file.

    The check the fill discipline has always named and never run. "Compiles,
    runs, at least one assertion, touches only its own file" is the rule, and
    three of the four were enforced: vitest strips types, so a draft calling a
    method that does not exist runs, fails at run time, and reads in the report
    as the application's fault. `app.request(...)` on an Express app cost this
    component six repairs and a whole healing run before anybody asked the
    compiler.

    Filtered to diagnostics about this file. A workspace can already hold type
    errors from tests written before this check existed, and refusing a draft
    for somebody else's mistake would make the rule impossible to satisfy.
    """
    app = app_of(repo, path)
    step = sandbox.run(
        Step(
            name=f"typecheck {path}",
            command=("npm", "run", "typecheck"),
            cwd=app,
            timeout=180,
        )
    )
    name = path.rsplit("/", 1)[-1]
    mine = [
        f"{match.group('path').rsplit('/', 1)[-1]} line {match.group('line')}: "
        f"{match.group('rest')}"
        # The raw line, not a stripped one. `tsc` indents the related
        # information under a diagnostic and some of those lines carry a path
        # and a position of their own, so the leading space is what tells them
        # apart from a second error. Stripping first threw that away and
        # reported one fault twice.
        for line in step.output.splitlines()
        if (match := _DIAGNOSTIC.match(line.rstrip())) and match.group("path").endswith(name)
    ]
    return step, mine


def collect_one(repo: TargetRepo, sandbox: Sandbox, path: str) -> StepResult:
    """Ask the runner to collect one file, and report what it said about it.

    For the diagnostic rather than for the answer. `collect` walks every app and
    keeps only the last step, so in a two app repository a criteria test in
    `apps/api` that would not parse was refused with the tail of `apps/web`'s
    output, which names other files' tests and explains nothing. A model handed
    that learns nothing from it and neither does a reader.
    """
    return sandbox.run(
        Step(
            name=f"collect {path}",
            command=(
                "npx",
                "vitest",
                "list",
                "--json",
                "--passWithNoTests",
                path.split("/", 2)[-1],
            ),
            cwd=app_of(repo, path),
            timeout=180,
        )
    )


def collect(repo: TargetRepo, sandbox: Sandbox) -> tuple[StepResult, list[tuple[str, str]]]:
    """Which tests exist, without running any of them.

    This is how a filled file is checked. Running the suite would answer a
    different question, and would make the generation stage's report, whose
    every case is `not-run`, into a claim that was true only because nobody
    looked. Collection proves the file parses and that the tests the model was
    asked to write are really there, which is exactly what the fill is
    responsible for; whether they pass is the next stage's result to report.

    Every app, for the reason `run_tests` uses every app. Returns the last
    step and the pairs of file and test name found across all of them.
    """
    found: list[tuple[str, str]] = []
    step: StepResult | None = None
    for app in repo.apps:
        step = sandbox.run(
            Step(
                name=f"collect ({app})" if len(repo.apps) > 1 else "collect",
                command=(
                    "npx",
                    "vitest",
                    "list",
                    "--json",
                    "--passWithNoTests",
                    f"--exclude={STRYKER_TEMP}",
                    "--exclude=**/node_modules/**",
                ),
                cwd=app,
                timeout=180,
            )
        )
        if not step.passed:
            return step, found
        text = step.output[step.output.find("[") :] if "[" in step.output else ""
        try:
            listed = json.loads(text)
        except json.JSONDecodeError:
            continue
        found.extend(
            (repo.relative(entry.get("file", "")), str(entry.get("name", "")))
            for entry in listed
            if isinstance(entry, dict)
        )
    if step is None:
        step = StepResult(name="collect", command="npx vitest list", outcome="not-run")
    return step, sorted(set(found))


def run_mutation(
    repo: TargetRepo,
    sandbox: Sandbox,
    scope: list[str],
    *,
    suite_is_green: bool,
    clock: Callable[[], float] = time.monotonic,
) -> MutationOutcome:
    """Mutants, over the named files only, once per app.

    Scoped for two reasons that happen to agree. This machine cannot afford a
    whole workspace mutation pass, and the honesty guard wants mutants in the
    region a test exercises rather than everywhere, so the narrow glob is what
    the contribution needs anyway.

    `suite_is_green` is not a convenience. Stryker refuses to start when the
    initial run has a failing test ("There were failed tests in the initial
    test run") and it is right to: a mutant is detected by turning a green test
    red, and a test that is already red cannot say anything about a mutant.
    Asking anyway costs a minute and produces a crash instead of a reason, so
    the lane asks first and reports the reason.

    Once per app, as the suite runs: each app has its own runner config, and
    Stryker reads its globs from the directory it runs in. Every mutant used to
    be made in the first scoped file's app, and the other app's files were
    handed to it under paths it does not have, so apps/web was never mutated
    (review item C3-6). The results are merged. An app that gave no score is
    named with its reason and left out of the scope, so the score says what it
    was measured over.

    Returns the steps, the result, and the reason there is no result. Exactly
    one of the last two is ever set: an absent mutation score with no reason is
    indistinguishable from a score of zero.
    """
    if not suite_is_green:
        step = StepResult(
            name="mutation",
            command="npx stryker run",
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
    if not scope:
        step = StepResult(
            name="mutation",
            command="npx stryker run",
            outcome="not-run",
            output="no files in scope",
        )
        return MutationOutcome(
            step=step, skipped_reason="no files were in scope, so there was nothing to mutate"
        )

    by_app: dict[str, list[str]] = {}
    for path in scope:
        by_app.setdefault(repo.app_for(path), []).append(path)
    order = sorted(by_app, key=lambda app: repo.apps.index(app) if app in repo.apps else 99)
    deadline = clock() + MUTATION_TIMEOUT_SECONDS
    outcomes: list[tuple[str, MutationOutcome]] = []
    for app in order:
        left = deadline - clock()
        if left < MUTATION_MINIMUM_SECONDS:
            outcomes.append((app, _out_of_time(repo, app)))
            continue
        outcomes.append((app, _mutate_app(repo, sandbox, app, by_app[app], timeout=left)))
    steps = [outcome.step for _, outcome in outcomes]
    missed = [
        UnmeasuredApp(app=app, reason=outcome.skipped_reason)
        for app, outcome in outcomes
        if outcome.result is None
    ]
    results = [outcome.result for _, outcome in outcomes if outcome.result is not None]
    if not results:
        reason = (
            outcomes[0][1].skipped_reason
            if len(outcomes) == 1
            else "; ".join(f"{one.app}: {one.reason}" for one in missed)
        )
        return MutationOutcome(step=steps[0], steps=steps, skipped_reason=reason)
    merged = MutationResult(
        tool=results[0].tool,
        scope=sorted(path for result in results for path in result.scope),
        killed=sorted(mutant for result in results for mutant in result.killed),
        survived=sorted(mutant for result in results for mutant in result.survived),
        inconclusive=sorted(mutant for result in results for mutant in result.inconclusive),
        duration_seconds=round(sum(result.duration_seconds for result in results), 2),
        not_measured=missed,
    )
    attribution: Attribution = {}
    for _, outcome in outcomes:
        attribution.update(outcome.attribution)
    return MutationOutcome(step=steps[0], steps=steps, result=merged, attribution=attribution)


def _step_name(repo: TargetRepo, app: str) -> str:
    return f"mutation ({app})" if len(repo.apps) > 1 else "mutation"


def _out_of_time(repo: TargetRepo, app: str) -> MutationOutcome:
    """An app the shared budget did not reach, said rather than scored."""
    step = StepResult(
        name=_step_name(repo, app),
        command="npx stryker run",
        outcome="not-run",
        output="the time budget ran out",
    )
    return MutationOutcome(
        step=step,
        skipped_reason=(
            f"the mutation time budget of {MUTATION_TIMEOUT_SECONDS / 60:g} minutes ran out "
            "before this app"
        ),
    )


def _mutate_app(
    repo: TargetRepo, sandbox: Sandbox, app: str, scope: list[str], *, timeout: float
) -> MutationOutcome:
    """One app's mutants, over its own files, from its own directory."""
    globs = [_app_relative(repo, path, app) for path in scope]
    step = sandbox.run(
        Step(
            name=_step_name(repo, app),
            command=(
                "npx",
                "stryker",
                "run",
                "--testRunner",
                "vitest",
                "--reporters",
                "json",
                "--concurrency",
                MUTATION_CONCURRENCY,
                # Without this, Stryker stops testing a mutant as soon as one
                # test kills it, so `killedBy` names only whichever test
                # happened to run first and every other test that would have
                # killed it looks like a test that kills nothing. On the node
                # sample that misreported one of two tests. It changes who gets
                # the credit, not the verdict: the status counts are identical
                # either way, so the score is unaffected and only the run is
                # longer.
                "--disableBail",
                "--mutate",
                ",".join(globs),
            ),
            cwd=app,
            timeout=timeout,
        )
    )
    raw = sandbox.read(str(Path(app) / "reports" / "mutation" / "mutation.json"))
    if not raw:
        return MutationOutcome(
            step=step,
            skipped_reason=f"the mutation run {step.outcome} and left no report: {step.tail[-400:]}",
        )
    try:
        result = parse_mutation(raw, repo, app=app, scope=scope, duration=step.duration_seconds)
        who = attribution(raw, repo, app=app)
    except (ValueError, KeyError, json.JSONDecodeError) as error:
        return MutationOutcome(
            step=step, skipped_reason=f"the mutation report could not be read: {error}"
        )
    if result.total == 0:
        return MutationOutcome(
            step=step,
            skipped_reason="the mutation run produced no mutants for the files in scope",
        )
    return MutationOutcome(step=step, result=result, attribution=who)


# ------------------------------------------------------------------- parsing


#: How vitest names an outcome, and what this component calls it. `todo` and
#: `pending` are the framework's own decisions to not run something, which is
#: what `skipped` means here; the run's decision not to reach a test is
#: `not-run` and is never produced by a runner that reached it.
_OUTCOMES = {
    "passed": "passed",
    "failed": "failed",
    "skipped": "skipped",
    "todo": "skipped",
    "pending": "skipped",
}


def parse_vitest(
    raw: str, repo: TargetRepo, *, authored: Authored | None = None
) -> list[TestSuite]:
    """Vitest's JSON reporter, as suites and cases.

    One case deserves saying out loud: a file that throws while loading has a
    status and a message but no assertions at all. Reporting it as an empty
    suite would say the file contained no tests, so it becomes one `errored`
    case carrying the import failure, which is what happened.
    """
    report = json.loads(raw)
    suites: list[TestSuite] = []
    for file_result in report.get("testResults", []):
        path = repo.relative(file_result.get("name", "")) or "unknown"
        cases: list[TestCase] = []
        for assertion in file_result.get("assertionResults", []):
            name = assertion.get("fullName") or assertion.get("title") or "unnamed test"
            outcome = _OUTCOMES.get(assertion.get("status", ""), "errored")
            messages = [m for m in assertion.get("failureMessages") or [] if m and m.strip()]
            message = messages[0].strip() if messages else ""
            if outcome in ("failed", "errored") and not message:
                message = "the runner reported it as failed and said nothing else"
            cases.append(
                TestCase(
                    id=f"{path}::{name}",
                    name=name,
                    outcome=outcome,  # type: ignore[arg-type]
                    duration_seconds=round((assertion.get("duration") or 0) / 1000, 4),
                    message=message,
                    origin=origin_of(path, authored),  # type: ignore[arg-type]
                )
            )
        if not cases:
            failure = (file_result.get("message") or "").strip()
            if failure or file_result.get("status") == "failed":
                cases.append(
                    TestCase(
                        id=f"{path}::the file itself",
                        name=f"{path} could not be loaded",
                        outcome="errored",
                        message=failure or "the file failed before any test ran",
                        origin=origin_of(path, authored),  # type: ignore[arg-type]
                    )
                )
        suites.append(TestSuite(path=path, framework="vitest", cases=cases))
    return suites


def parse_coverage(raw: str, repo: TargetRepo) -> list[CoverageEntry]:
    """Istanbul's summary shape, per file, with the counts kept.

    The `total` row is dropped rather than stored: the report computes its own
    total from these, weighted by lines, and two totals that can disagree is
    exactly the thing the contract refuses to carry.
    """
    summary = json.loads(raw)
    entries: list[CoverageEntry] = []
    for path, numbers in summary.items():
        if path == "total":
            continue
        lines = numbers.get("lines") or {}
        branches = numbers.get("branches") or {}
        entries.append(
            CoverageEntry(
                module=repo.relative(path),
                lines_covered=int(lines.get("covered") or 0),
                lines_total=int(lines.get("total") or 0),
                branches_covered=int(branches.get("covered") or 0),
                branches_total=int(branches.get("total") or 0),
            )
        )
    return sorted(entries, key=lambda entry: entry.module)


#: Stryker's statuses, sorted into the three this component reports.
#: `Timeout` counts as killed because an infinite loop is a detected mutant,
#: which is how every mutation tool scores it. `NoCoverage` is a survivor: no
#: test looked, which is precisely what a survivor means. The rest could not
#: be decided and are never quietly counted as either.
_KILLED = {"Killed", "Timeout"}
_SURVIVED = {"Survived", "NoCoverage"}


def parse_mutation(
    raw: str, repo: TargetRepo, *, scope: list[str], duration: float, app: str | None = None
) -> MutationResult:
    """The mutation testing report schema, as killed, survived and undecided.

    Ids are `file:line:column:mutator`, not Stryker's per file counter, so a
    mutant can be found again by a human and compared between two runs of a
    file that has moved.

    Paths are put back into the repository's vocabulary on the way out. Stryker
    names files from the directory it ran in, which is the app, and everything
    else in a test report names them from the repository root: two spellings of
    one path in one report is how a reader ends up looking for a file that is
    not where the report says.
    """
    report = json.loads(raw)
    killed: list[str] = []
    survived: list[str] = []
    inconclusive: list[str] = []
    for path, entry in (report.get("files") or {}).items():
        for mutant in entry.get("mutants") or []:
            start = (mutant.get("location") or {}).get("start") or {}
            identifier = (
                f"{_repo_relative(repo, path, app)}:{start.get('line', 0)}:"
                f"{start.get('column', 0)}:{mutant.get('mutatorName', 'mutant')}"
            )
            status = mutant.get("status", "")
            if status in _KILLED:
                killed.append(identifier)
            elif status in _SURVIVED:
                survived.append(identifier)
            else:
                inconclusive.append(identifier)
    return MutationResult(
        tool=f"stryker {STRYKER_VERSION}",
        scope=sorted(scope),
        killed=sorted(killed),
        survived=sorted(survived),
        inconclusive=sorted(inconclusive),
        duration_seconds=duration,
    )


def attribution(raw: str, repo: TargetRepo, *, app: str | None = None) -> Attribution:
    """Which test covered and killed which mutant, by the report's own case ids.

    Stryker names tests by `describe` and `it` joined with a space, which is
    exactly what the JSON reporter puts in `fullName`, so the ids built here
    are the same ids `parse_vitest` built and a finding can name a test the
    reader is looking at.

    Only meaningful when the run had `--disableBail`, which the mutation step
    passes: with bail on, `killedBy` names one test per mutant and every other
    covering test reads as a test that kills nothing.
    """
    report = json.loads(raw)
    names = {
        str(test.get("id")): f"{_repo_relative(repo, path, app)}::{test.get('name', '')}"
        for path, entry in (report.get("testFiles") or {}).items()
        for test in (entry.get("tests") or [])
    }
    covered: dict[str, list[str]] = {}
    killed: dict[str, list[str]] = {}
    for path, entry in (report.get("files") or {}).items():
        for mutant in entry.get("mutants") or []:
            start = (mutant.get("location") or {}).get("start") or {}
            identifier = (
                f"{_repo_relative(repo, path, app)}:{start.get('line', 0)}:"
                f"{start.get('column', 0)}:{mutant.get('mutatorName', 'mutant')}"
            )
            for test_id in mutant.get("coveredBy") or []:
                covered.setdefault(names.get(str(test_id), str(test_id)), []).append(identifier)
            for test_id in mutant.get("killedBy") or []:
                killed.setdefault(names.get(str(test_id), str(test_id)), []).append(identifier)
    return {
        name: TestKills(
            covered=tuple(sorted(covered.get(name, ()))), killed=tuple(sorted(killed.get(name, ())))
        )
        for name in {*covered, *killed}
    }


def _repo_relative(repo: TargetRepo, path: str, app: str | None = None) -> str:
    """An app relative path as the repository names it."""
    prefix = (app or repo.app_dir).strip("./")
    return f"{prefix}/{path}" if prefix and not path.startswith(f"{prefix}/") else path


def _app_relative(repo: TargetRepo, path: str, app: str | None = None) -> str:
    """A repository path as the app directory sees it.

    Reports name files from the repository root, and Stryker's globs are read
    from the directory it runs in, which is the app. One conversion, here,
    rather than two vocabularies in the caller.
    """
    chosen = app or repo.app_dir
    prefix = f"{chosen.strip('./')}/" if chosen not in (".", "") else ""
    return path[len(prefix) :] if prefix and path.startswith(prefix) else path
