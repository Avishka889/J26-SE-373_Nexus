"""The MERN lane: what the tools said, and what this component made of it.

The parsers are tested against files the real tools wrote (see
`golden/README.md`), so these run in milliseconds without a network and still
fail when vitest or Stryker changes its report shape. The lane itself runs for
real behind the `sandbox` marker, which is where the claim that any of this
works against a repository is actually settled.
"""

import json
import shutil
from pathlib import Path

import pytest
from c3.harness import Sandbox, resolve, stage_copy
from c3.harness import node_lane as lane
from c3.harness.sandbox import StepResult
from c3.harness.targets import TargetRepo
from sdlc_contracts import UnmeasuredApp

from .test_targets import Ref

GOLDEN = Path(__file__).parent / "golden" / "node"

needs_npm = pytest.mark.skipif(shutil.which("npm") is None, reason="needs node and npm")


@pytest.fixture
def repo() -> TargetRepo:
    """The workspace the golden files came out of, as the parsers see it."""
    return TargetRepo(root=Path("/workspace"), kind="sample", stack="node", apps=("apps/web",))


def golden(name: str) -> str:
    return (GOLDEN / name).read_text()


class TestAskingTheCompilerAboutOneFile:
    """The check the fill discipline names and never ran.

    "Compiles, runs, at least one assertion, touches only its own file" is the
    rule and three of the four were enforced. Vitest strips types, so a draft
    calling a method the module does not have parses, collects, runs, and fails
    at run time reading as the application's fault. `app.request(...)` on an
    Express app cost this component six repairs and a whole healing run before
    anybody asked `tsc`, and the same command reports it in one line.
    """

    #: Real `tsc` output, from the workspace the live run left behind.
    OUTPUT = (
        "src/__tests__/US-3.criteria.test.ts(13,38): error TS2349: "
        "This expression is not callable.\n"
        "  Type 'Request<ParamsDictionary, any, any, ParsedQs>' has no call signatures.\n"
        "src/__tests__/US-3.criteria.test.ts(22,36): error TS2349: "
        "This expression is not callable.\n"
        "src/__tests__/US-4.criteria.test.ts(15,7): error TS2353: "
        "Object literal may only specify known properties, and 'title' does not exist "
        "in type 'Omit<Task, \"id\">'.\n"
    )

    def _sandbox(self, output: str, outcome: str = "failed"):
        class Fake:
            def run(self, step):
                return StepResult(
                    name=step.name, command="npm run typecheck", outcome=outcome, output=output
                )

        return Fake()

    def test_it_reports_the_diagnostics_about_the_file_it_was_asked_about(self, repo) -> None:
        _, mine = lane.typecheck(
            repo, self._sandbox(self.OUTPUT), "apps/web/src/__tests__/US-3.criteria.test.ts"
        )

        assert len(mine) == 2
        assert all("US-3" in one for one in mine)
        assert "line 13" in mine[0]
        assert "TS2349" in mine[0]

    def test_another_file_s_errors_are_not_this_draft_s_problem(self, repo) -> None:
        """A workspace can already hold type errors from tests written before
        this check existed. Refusing a draft for somebody else's mistake would
        make the rule impossible to satisfy."""
        _, mine = lane.typecheck(
            repo, self._sandbox(self.OUTPUT), "apps/web/src/__tests__/US-1.criteria.test.ts"
        )

        assert mine == []

    def test_a_clean_file_in_a_clean_workspace_reports_nothing(self, repo) -> None:
        _, mine = lane.typecheck(
            repo, self._sandbox("", outcome="passed"), "apps/web/src/a.test.ts"
        )

        assert mine == []

    def test_an_indented_related_line_is_not_a_second_error(self, repo) -> None:
        """`tsc` indents the related information under a diagnostic, and some of
        those lines carry a path and a position of their own. Counting them
        would report several errors where the compiler reported one, and the
        refusal handed to the model would list the same fault repeatedly."""
        output = (
            "src/__tests__/a.test.ts(13,38): error TS2349: This expression is not callable.\n"
            "  src/__tests__/a.test.ts(4,2): error TS2349: the declaration is here.\n"
        )

        _, mine = lane.typecheck(repo, self._sandbox(output), "apps/web/src/__tests__/a.test.ts")

        assert len(mine) == 1
        assert "line 13" in mine[0]


class TestTheOneIdATestHas:
    """Three places name the same test and the join is the string itself.

    The generator names it before it runs, because the rules that wrote it know
    what it was written from. The runner's report names it afterwards. Stryker's
    attribution names it again when it says which mutants it killed. If any two
    disagree, the information one holds never reaches the other.

    Two of them did disagree, by two characters: the generators joined the
    `describe` and the `it` with `" > "` and vitest's `fullName` joins them with a
    space. So no declared case ever matched the case it became, the traces the
    generator wrote never reached the executed report, and the healing
    classifier answered `undecided` on every real failure for want of them.
    Nothing failed, which is why it went unnoticed for the life of the stage.
    """

    def test_the_id_a_generator_predicts_is_the_id_the_runner_reports(self, repo) -> None:
        """Settled against a report vitest actually wrote, not against a belief
        about how vitest names things."""
        import json as _json

        from c3.harness.report import case_id

        raw = golden("vitest.json")
        reported = {case.id for suite in lane.parse_vitest(raw, repo) for case in suite.cases}

        document = _json.loads(raw)
        predicted = {
            case_id(
                "apps/web/src/__tests__/total.test.ts",
                " ".join(assertion["ancestorTitles"]),
                assertion["title"],
            )
            for result in document["testResults"]
            for assertion in result["assertionResults"]
        }

        assert predicted == reported, predicted.symmetric_difference(reported)

    def test_a_test_outside_any_describe_is_not_given_a_leading_space(self) -> None:
        from c3.harness.report import case_id

        assert case_id("a.test.ts", "", "adds") == "a.test.ts::adds"


class TestReadingWhatVitestWrote:
    def test_the_cases_come_back_with_the_outcomes_they_had(self, repo) -> None:
        suites = lane.parse_vitest(golden("vitest.json"), repo)

        assert len(suites) == 1
        suite = suites[0]
        assert suite.path == "apps/web/src/__tests__/total.test.ts"
        assert suite.framework == "vitest"
        assert [case.outcome for case in suite.cases] == ["passed", "passed", "skipped"]

    def test_a_skip_is_the_framework_declining_and_never_a_pass(self, repo) -> None:
        """The sample has one `it.skip` for exactly this assertion. A runner
        that ran two of three tests has not passed three."""
        suite = lane.parse_vitest(golden("vitest.json"), repo)[0]

        assert suite.passed == 2
        assert sum(1 for case in suite.cases if case.outcome == "skipped") == 1

    def test_an_id_names_the_file_and_the_test(self, repo) -> None:
        """So a case can be found again in a repository, and matched across two
        runs of it."""
        suite = lane.parse_vitest(golden("vitest.json"), repo)[0]

        assert suite.cases[0].id.startswith("apps/web/src/__tests__/total.test.ts::")
        assert "adds price times quantity" in suite.cases[0].id

    def test_a_file_that_could_not_be_loaded_is_not_a_file_with_no_tests(self, repo) -> None:
        """Vitest reports an import failure as a result with a message and no
        assertions. Read literally that is a suite of zero tests, which reads
        as nothing to run rather than as everything failing to run.
        """
        raw = json.dumps(
            {
                "testResults": [
                    {
                        "name": "/workspace/apps/web/src/__tests__/broken.test.ts",
                        "status": "failed",
                        "message": "Cannot find module '../total'",
                        "assertionResults": [],
                    }
                ]
            }
        )

        suite = lane.parse_vitest(raw, repo)[0]

        assert len(suite.cases) == 1
        assert suite.cases[0].outcome == "errored"
        assert "Cannot find module" in suite.cases[0].message

    def test_a_failure_always_carries_its_message(self, repo) -> None:
        """The contract refuses a failure without one, so a runner that says
        nothing gets a sentence rather than a validation error three stages
        later."""
        raw = json.dumps(
            {
                "testResults": [
                    {
                        "name": "/workspace/apps/web/src/__tests__/quiet.test.ts",
                        "status": "failed",
                        "assertionResults": [
                            {"fullName": "it just fails", "status": "failed", "failureMessages": []}
                        ],
                    }
                ]
            }
        )

        case = lane.parse_vitest(raw, repo)[0].cases[0]

        assert case.outcome == "failed"
        assert case.message


class TestReadingTheCoverage:
    def test_the_totals_row_is_dropped_and_recomputed(self, repo) -> None:
        """Istanbul's summary carries a `total`. Storing it beside the per file
        counts would be two numbers that can disagree, and the report computes
        its own from these, weighted by lines."""
        entries = lane.parse_coverage(golden("coverage-summary.json"), repo)

        assert [entry.module for entry in entries] == ["apps/web/src/total.ts"]
        assert all(entry.lines_covered <= entry.lines_total for entry in entries)

    def test_the_counts_survive_rather_than_the_percentage(self, repo) -> None:
        entry = lane.parse_coverage(golden("coverage-summary.json"), repo)[0]

        assert entry.lines_total > 0
        assert entry.line_percent == round(entry.lines_covered / entry.lines_total * 100, 2)


class TestReadingTheMutants:
    def test_the_score_matches_what_stryker_measured(self, repo) -> None:
        result = lane.parse_mutation(
            golden("mutation.json"), repo, scope=["apps/web/src/total.ts"], duration=9.15
        )

        report = json.loads(golden("mutation.json"))
        statuses = [
            mutant["status"] for entry in report["files"].values() for mutant in entry["mutants"]
        ]
        assert result.total == len(statuses)
        assert len(result.killed) == sum(1 for s in statuses if s in ("Killed", "Timeout"))
        assert len(result.survived) == sum(1 for s in statuses if s in ("Survived", "NoCoverage"))

    def test_a_mutant_can_be_found_again_in_the_repository(self, repo) -> None:
        """Stryker names files from the directory it ran in, which is the app.
        A report that mixed the two spellings would send a reader to a path
        that is not there."""
        result = lane.parse_mutation(
            golden("mutation.json"), repo, scope=["apps/web/src/total.ts"], duration=1.0
        )

        assert all(mutant.startswith("apps/web/src/total.ts:") for mutant in result.survived)
        assert all(mutant.startswith("apps/web/src/total.ts:") for mutant in result.killed)

    def test_a_mutant_nobody_could_decide_is_neither(self) -> None:
        """A compile error in the mutated form is not evidence that a test
        missed it, so it is excluded from the denominator rather than counted
        as a survivor. Three statuses, three answers."""
        raw = json.dumps(
            {
                "files": {
                    "src/a.ts": {
                        "mutants": [
                            {"status": "Killed", "location": {"start": {"line": 1, "column": 1}}},
                            {"status": "Timeout", "location": {"start": {"line": 2, "column": 1}}},
                            {"status": "Survived", "location": {"start": {"line": 3, "column": 1}}},
                            {
                                "status": "NoCoverage",
                                "location": {"start": {"line": 4, "column": 1}},
                            },
                            {
                                "status": "CompileError",
                                "location": {"start": {"line": 5, "column": 1}},
                            },
                        ]
                    }
                }
            }
        )
        repo = TargetRepo(root=Path("/workspace"), kind="sample", stack="node")

        result = lane.parse_mutation(raw, repo, scope=["src/a.ts"], duration=0.0)

        assert (len(result.killed), len(result.survived), len(result.inconclusive)) == (2, 2, 1)
        assert result.total == 5
        # Two killed out of four decided, not out of five.
        assert result.score == 50.0


class TestDeclaringTheMeasurementTools:
    """npm would not let these be added without saving them, so they are saved.

    Three failures taught this, in order: an unsaved add at a workspace root
    crashes npm outright; adding one package at a time succeeds and each call
    prunes the one before it; and declaring all three still crashes until
    vitest is declared at the root beside them, because the mutation runner has
    a peer dependency on vitest and npm cannot resolve a peer across a
    workspace link.
    """

    def test_the_root_asks_for_the_vitest_the_app_asks_for(self, tmp_path) -> None:
        repo = stage_copy(resolve(Ref(kind="sample", path="node-sample")), tmp_path / "ws")

        added = lane.declare_measurement_tools(repo)

        manifest = json.loads(repo.read("package.json") or "{}")
        app = json.loads(repo.read("apps/web/package.json") or "{}")
        assert added["vitest"] == app["devDependencies"]["vitest"]
        assert manifest["devDependencies"]["vitest"] == app["devDependencies"]["vitest"]
        assert manifest["devDependencies"]["@vitest/coverage-v8"] == added["vitest"]

    def test_the_app_is_left_exactly_as_it_was(self, tmp_path) -> None:
        """Only the workspace root's manifest is touched, and only in the
        scratch copy: what the repository declares is what was generated."""
        source = resolve(Ref(kind="sample", path="node-sample"))
        repo = stage_copy(source, tmp_path / "ws")

        lane.declare_measurement_tools(repo)

        assert (
            repo.read("apps/web/package.json")
            == (source.root / "apps/web/package.json").read_text()
        )
        assert "@stryker-mutator/core" not in (source.root / "package.json").read_text()

    def test_a_project_with_no_test_runner_gets_no_tools(self, tmp_path) -> None:
        """Installing a runner the project never asked for would be measuring
        something nobody wrote."""
        (tmp_path / "ws").mkdir()
        (tmp_path / "ws" / "package.json").write_text('{"name": "no-tests"}')
        repo = TargetRepo(root=tmp_path / "ws", kind="benchmark", stack="node")

        assert lane.declare_measurement_tools(repo) == {}
        assert "devDependencies" not in json.loads(repo.read("package.json") or "{}")

    def test_declaring_twice_changes_nothing_the_second_time(self, tmp_path) -> None:
        repo = stage_copy(resolve(Ref(kind="sample", path="node-sample")), tmp_path / "ws")

        first = lane.declare_measurement_tools(repo)
        second = lane.declare_measurement_tools(repo)

        assert first and second == {}


class TestWhatTheLaneRefusesToMeasure:
    def test_mutation_does_not_start_on_a_red_suite(self, repo) -> None:
        """Stryker refuses this itself, with a stack trace after a minute of
        work. Asking first turns a crash into a reason, and the reason is a
        true statement about mutation testing: a mutant is detected by turning
        a green test red.
        """
        outcome = lane.run_mutation(
            repo, Sandbox(repo.root), ["apps/web/src/total.ts"], suite_is_green=False
        )

        assert outcome.step.outcome == "not-run"
        assert outcome.result is None
        assert "green test red" in outcome.skipped_reason

    def test_nothing_in_scope_is_said_rather_than_scored(self, repo) -> None:
        outcome = lane.run_mutation(repo, Sandbox(repo.root), [], suite_is_green=True)

        assert (outcome.step.outcome, outcome.result) == ("not-run", None)
        assert "nothing to mutate" in outcome.skipped_reason


@pytest.mark.sandbox
@needs_npm
class TestTheLaneAgainstARealRepository:
    """The load bearing proof: the tools really run and really report.

    One test rather than four, because the four steps are one sequence and
    splitting them would install the workspace four times.
    """

    def test_it_installs_runs_covers_and_mutates(self, tmp_path) -> None:
        repo = stage_copy(resolve(Ref(kind="sample", path="node-sample")), tmp_path / "ws")
        box = Sandbox(repo.root)

        assert lane.declare_measurement_tools(repo)
        assert lane.install(repo, box).passed
        run = lane.run_tests(repo, box)

        assert run.ran, run.steps[0].tail
        cases = [case for suite in run.suites for case in suite.cases]
        assert [case.outcome for case in cases] == ["passed", "passed", "skipped"]
        assert run.coverage, "coverage was requested and the report should be there"
        covered = {entry.module for entry in run.coverage}
        assert "apps/web/src/total.ts" in covered

        outcome = lane.run_mutation(repo, box, ["apps/web/src/total.ts"], suite_is_green=True)

        assert outcome.result is not None, f"{outcome.step.outcome}: {outcome.skipped_reason}"
        mutation = outcome.result
        # The fixture has a function no test reaches, so some mutants live.
        assert mutation.killed and mutation.survived
        assert 0 < mutation.score < 100

    def test_a_red_suite_still_reports_its_coverage(self, tmp_path) -> None:
        """The flag this lane would most easily be missing.

        Vitest writes no coverage report at all when a test fails, unless it is
        asked to, and a failing suite is this component's normal case: the
        healing loop exists because tests fail. Without the flag the coverage
        of every interesting run is absent, and absent reads as zero.
        """
        repo = stage_copy(resolve(Ref(kind="sample", path="node-sample")), tmp_path / "ws")
        box = Sandbox(repo.root)
        lane.declare_measurement_tools(repo)
        lane.install(repo, box)
        repo.write(
            "apps/web/src/__tests__/red.test.ts",
            'import { expect, it } from "vitest";\n'
            'import { total } from "../total";\n'
            'it("expects the wrong answer on purpose", () => {\n'
            "  expect(total([{ price: 2, quantity: 3 }])).toBe(7);\n"
            "});\n",
        )

        run = lane.run_tests(repo, box)

        failures = [
            case
            for suite in run.suites
            for case in suite.cases
            if case.outcome in ("failed", "errored")
        ]
        assert failures, "the added test should have failed"
        assert run.coverage, "a red suite still has coverage, and this is where it goes missing"


def _stryker(path: str, statuses: list[str]) -> str:
    """A mutation report as Stryker writes it in an app, over one file."""
    return json.dumps(
        {
            "schemaVersion": "2",
            "thresholds": {"high": 80, "low": 60},
            "files": {
                path: {
                    "language": "typescript",
                    "source": "",
                    "mutants": [
                        {
                            "id": str(number),
                            "mutatorName": "BooleanLiteral",
                            "status": status,
                            "location": {
                                "start": {"line": 1 + number, "column": 1},
                                "end": {"line": 1 + number, "column": 5},
                            },
                            "coveredBy": [],
                            "killedBy": [],
                        }
                        for number, status in enumerate(statuses)
                    ],
                }
            },
            "testFiles": {},
        }
    )


class Stryking:
    """A sandbox in which Stryker leaves the given report in each app, or none."""

    def __init__(self, reports: dict[str, str | None]) -> None:
        self.reports = reports
        self.ran: list[tuple[str, str]] = []

    def run(self, step) -> StepResult:
        self.ran.append((step.cwd, step.command[step.command.index("--mutate") + 1]))
        failed = self.reports.get(step.cwd) is None
        return StepResult(
            name=step.name,
            command=" ".join(step.command),
            outcome="failed" if failed else "passed",
            output="no tests ran" if failed else "",
        )

    def read(self, path: str) -> str | None:
        return self.reports.get(path.split("/reports/")[0])


class TestMutationOncePerApp:
    """The scope names files in both apps, and every mutant was made in the first
    scoped file's app: the other app's files were handed to it under paths it
    does not have, so apps/web was never mutated (review item C3-6). Once per
    app now, as the suite runs, and an app that gave no score says why."""

    REPO = TargetRepo(
        root=Path("/workspace"), kind="generated", stack="node", apps=("apps/api", "apps/web")
    )
    SCOPE = ("apps/api/src/routes/movies.ts", "apps/web/src/pages/Movies.tsx")
    NO_REPORT = "the mutation run failed and left no report: no tests ran"

    def test_each_app_mutates_its_own_files(self) -> None:
        box = Stryking(
            {
                "apps/api": _stryker("src/routes/movies.ts", ["Killed", "Survived"]),
                "apps/web": _stryker("src/pages/Movies.tsx", ["Killed"]),
            }
        )

        outcome = lane.run_mutation(self.REPO, box, list(self.SCOPE), suite_is_green=True)

        assert box.ran == [
            ("apps/api", "src/routes/movies.ts"),
            ("apps/web", "src/pages/Movies.tsx"),
        ]
        assert [step.name for step in outcome.steps] == [
            "mutation (apps/api)",
            "mutation (apps/web)",
        ]
        assert outcome.result is not None
        assert outcome.result.scope == list(self.SCOPE)
        assert outcome.result.killed == [
            "apps/api/src/routes/movies.ts:1:1:BooleanLiteral",
            "apps/web/src/pages/Movies.tsx:1:1:BooleanLiteral",
        ]
        assert outcome.result.survived == ["apps/api/src/routes/movies.ts:2:1:BooleanLiteral"]
        assert outcome.result.not_measured == []

    def test_an_app_that_gave_no_score_is_named_and_left_out_of_the_scope(self) -> None:
        box = Stryking(
            {"apps/api": _stryker("src/routes/movies.ts", ["Killed", "Survived"]), "apps/web": None}
        )

        outcome = lane.run_mutation(self.REPO, box, list(self.SCOPE), suite_is_green=True)

        assert outcome.result is not None
        assert outcome.result.scope == ["apps/api/src/routes/movies.ts"]
        assert outcome.result.score == 50.0
        assert outcome.result.not_measured == [UnmeasuredApp(app="apps/web", reason=self.NO_REPORT)]

    def test_no_app_giving_a_score_says_why_for_each(self) -> None:
        box = Stryking({"apps/api": None, "apps/web": None})

        outcome = lane.run_mutation(self.REPO, box, list(self.SCOPE), suite_is_green=True)

        assert outcome.result is None
        assert outcome.skipped_reason == (f"apps/api: {self.NO_REPORT}; apps/web: {self.NO_REPORT}")
        assert len(outcome.steps) == 2

    def test_the_apps_share_one_time_budget(self) -> None:
        # Every testing stage beats the run's heartbeat once, at its start, and a
        # run silent past C3's twenty minute window is reclaimed and failed: a
        # pass per app with twenty minutes each could fail it mid mutation.
        now = [0.0]

        class Timed(Stryking):
            def __init__(self, reports, used: float) -> None:
                super().__init__(reports)
                self.used = used
                self.timeouts: list[float] = []

            def run(self, step) -> StepResult:
                self.timeouts.append(step.timeout)
                now[0] += min(self.used, step.timeout)
                return super().run(step)

        reports = {
            "apps/api": _stryker("src/routes/movies.ts", ["Killed"]),
            "apps/web": _stryker("src/pages/Movies.tsx", ["Killed"]),
        }
        budget = lane.MUTATION_TIMEOUT_SECONDS

        quick = Timed(reports, used=300.0)
        lane.run_mutation(
            self.REPO, quick, list(self.SCOPE), suite_is_green=True, clock=lambda: now[0]
        )
        now[0] = 0.0
        slow = Timed(reports, used=budget)
        outcome = lane.run_mutation(
            self.REPO, slow, list(self.SCOPE), suite_is_green=True, clock=lambda: now[0]
        )

        assert quick.timeouts == [budget, budget - 300.0]
        assert slow.timeouts == [budget]
        assert outcome.result is not None
        assert outcome.result.not_measured == [
            UnmeasuredApp(
                app="apps/web",
                reason="the mutation time budget of 20 minutes ran out before this app",
            )
        ]

    def test_one_app_keeps_the_plain_step_name(self, repo) -> None:
        box = Stryking({"apps/web": _stryker("src/total.ts", ["Killed"])})

        outcome = lane.run_mutation(repo, box, ["apps/web/src/total.ts"], suite_is_green=True)

        assert [step.name for step in outcome.steps] == ["mutation"]
        assert outcome.result is not None and outcome.result.score == 100.0

    async def test_the_quality_stage_keeps_every_apps_step(self, tmp_path, monkeypatch) -> None:
        from datetime import UTC, datetime

        from c3.harness.report import MutationOutcome
        from c3.service import C3
        from sdlc_contracts import TestReport

        for app in ("apps/api", "apps/web"):
            (tmp_path / app).mkdir(parents=True)
            (tmp_path / app / "package.json").write_text("{}")
        steps = [
            StepResult(name=f"mutation ({app})", command="npx stryker run", outcome="failed")
            for app in ("apps/api", "apps/web")
        ]
        monkeypatch.setattr(
            lane,
            "run_mutation",
            lambda *args, **kwargs: MutationOutcome(
                step=steps[0], steps=steps, skipped_reason="apps/api: no; apps/web: no"
            ),
        )
        report = TestReport(
            version=1,
            generated_at=datetime.now(UTC),
            target="the generated app",
            isolation="sandbox",
            mutation_skipped_reason="the quality stage's work",
        )

        measured = await C3("no model").measure_quality(
            Ref(kind="generated", code_version=1, path=str(tmp_path)), report, [], version=2
        )

        assert [step.name for step in measured.artefact.steps] == [
            "mutation (apps/api)",
            "mutation (apps/web)",
        ]
        assert measured.artefact.mutation_skipped_reason == "apps/api: no; apps/web: no"
