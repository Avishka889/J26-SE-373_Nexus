"""A stage's processes run off the event loop.

The orchestrator runs this component in its own process, on the event loop
that answers every request the browser makes. Every stage here starts
processes: an install, the runner, the compiler, a mutation pass, a model
server. Each was started with a blocking call from inside an async stage, so
while it ran the orchestrator answered nothing. On 2026-10-18 a mutation pass
held the loop for 10.6 minutes: every read the page made timed out, Retry now
could not be answered, a reload signed the reader out, and the database cut two
of the orchestrator's own connections for sitting idle in a transaction.

Each test runs one stage with every process replaced by a stand-in that, while
it "runs", asks the loop to do one small thing and waits for it. From a worker
thread the loop does it at once. From the loop's own thread it cannot happen
until the process returns, which is the freeze, and the stand-in records the
command that caused it.
"""

import asyncio
import json
import shutil
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from c3.harness import sandbox as sandbox_module
from c3.service import C3
from sdlc_contracts import TestCase, TestReport, TestSuite, TestTrace

from .test_targets import Ref

#: The stand-ins never start npm, but the sandbox looks a command up on PATH
#: before it starts one, and a command it cannot find is never started at all.
needs_npm = pytest.mark.skipif(shutil.which("npm") is None, reason="needs node and npm")

#: How long a stand-in waits for the loop. A free loop answers in well under a
#: millisecond, so this only has to outlast a loaded machine; a held loop does
#: not answer within any wait at all.
PATIENCE_SECONDS = 2.0


class LoopWatch:
    """Every process a stage starts, and whether the loop was free while it ran."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self.started: list[str] = []
        self.held_the_loop: list[str] = []

    def from_here(self) -> None:
        """Start watching, on the loop the stage is about to run on.

        Not before: a fixture's own install goes through the same stand-in, and
        it runs before the stage, where nothing is being measured.
        """
        self._loop = asyncio.get_running_loop()

    def note(self, what: str) -> None:
        if self._loop is None:
            return
        self.started.append(what)
        answered = threading.Event()
        self._loop.call_soon_threadsafe(answered.set)
        if not answered.wait(PATIENCE_SECONDS):
            self.held_the_loop.append(what)

    def run(
        self, command: list[str], *, cwd: Path | None = None, **_: object
    ) -> subprocess.CompletedProcess[str]:
        self.note(" ".join(command))
        _write_the_report(command, cwd)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


def _write_the_report(command: list[str], cwd: Path | None) -> None:
    """One passing test, where a suite's run asks the runner for its report.

    So the stage goes on to what it does with a suite that ran, which for the
    run stage is the order check: the suite again, shuffled. With no report the
    run reports no suites and the check starts nothing.
    """
    wanted = next(
        (part.split("=", 1)[1] for part in command if part.startswith("--outputFile=")), ""
    )
    if cwd is None or not wanted.endswith("vitest.json"):
        return
    report = Path(cwd) / wanted
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps(
            {
                "testResults": [
                    {
                        "name": str(Path(cwd) / "src" / "__tests__" / "watched.test.ts"),
                        "assertionResults": [
                            {"fullName": "is watched", "status": "passed", "duration": 1}
                        ],
                    }
                ]
            }
        )
    )


@pytest.fixture
def watch(monkeypatch: pytest.MonkeyPatch) -> LoopWatch:
    """The sandbox's processes, all of them, through the stand-in."""
    watched = LoopWatch()
    monkeypatch.setattr(
        sandbox_module,
        "subprocess",
        SimpleNamespace(
            run=watched.run,
            TimeoutExpired=subprocess.TimeoutExpired,
            SubprocessError=subprocess.SubprocessError,
        ),
    )
    return watched


def _assert_the_loop_stayed_free(watch: LoopWatch) -> None:
    assert watch.started, "the stage started no process, so this proved nothing"
    assert watch.held_the_loop == [], (
        f"{len(watch.held_the_loop)} of {len(watch.started)} processes held the event loop "
        f"while they ran: {watch.held_the_loop}"
    )


def _green(suite: str) -> TestReport:
    """A suite that passed, which is what lets the mutation pass start."""
    return TestReport(
        version=1,
        generated_at="2026-10-18 10:00",
        target="the checkout",
        isolation="a subprocess",
        suites=[
            TestSuite(
                path=suite,
                framework="vitest",
                cases=[
                    TestCase(
                        id=f"{suite}::lists the orders",
                        name="lists the orders",
                        outcome="passed",
                        origin="skeleton",
                        traces=TestTrace(story_id="US-1", endpoint_ids=["get-orders"]),
                    )
                ],
            )
        ],
        mutation_skipped_reason="not run yet",
    )


@needs_npm
class TestEveryStageLeavesTheLoopFree:
    async def test_running_the_suite(self, tmp_path, watch) -> None:
        from .test_phase_end_to_end import _checkout

        checkout, _, _ = _checkout(tmp_path)
        target = Ref(kind="generated", code_version=1, path=str(checkout))

        watch.from_here()
        await C3("canned").run_tests(target, version=1)

        _assert_the_loop_stayed_free(watch)
        # The order check ran too: it is the suite again, and as long.
        assert any("--sequence.shuffle" in one for one in watch.started), watch.started

    async def test_the_mutation_pass(self, tmp_path, watch) -> None:
        from .test_phase_end_to_end import _checkout

        checkout, _, _ = _checkout(tmp_path)
        routes = checkout / "apps" / "api" / "src" / "routes"
        scope = sorted(str(path.relative_to(checkout)) for path in routes.glob("*.ts"))
        assert scope, "the checkout has no route to mutate"
        target = Ref(kind="generated", code_version=1, path=str(checkout))

        watch.from_here()
        await C3("canned").measure_quality(
            target, _green("apps/api/src/__tests__/orders.contract.test.ts"), scope, version=1
        )

        _assert_the_loop_stayed_free(watch)

    async def test_the_healing_guard(self, tmp_path, watch) -> None:
        from c3.eval.repair_proof import changed_contract, component_for, failing_report, prepare

        repo = prepare(tmp_path)
        target = Ref(kind="generated", code_version=2, path=str(repo.root))

        watch.from_here()
        await component_for("scripted:honest", "minimal").heal(
            target,
            failing_report(),
            from_code_version=1,
            to_code_version=2,
            contract_diff=changed_contract(),
            version=2,
        )

        _assert_the_loop_stayed_free(watch)

    async def test_the_fill_check(self, tmp_path, watch) -> None:
        from .test_generate import TestTheModelFillAgainstARealWorkspace as fill
        from .test_generate import _document_for

        checkout, contract, sprint, story = fill._checkout(tmp_path, "Watched")
        path = f"apps/api/src/__tests__/{story.id}.criteria.test.ts"
        answer = fill._body(
            fill._skeleton(checkout, sprint, contract, path),
            'const found = await request(app).get("/orders");\n'
            "    expect(Array.isArray(found.body)).toBe(true);",
        )
        target = Ref(kind="generated", code_version=1, path=str(checkout))

        watch.from_here()
        await C3("scripted", filler=fill._scripted(answer)).generate_tests(
            target, sprint, contract, _document_for(contract), version=2
        )

        _assert_the_loop_stayed_free(watch)


async def test_a_java_suite_leaves_the_loop_free(tmp_path, watch) -> None:
    """The Maven wrapper is the project's own file, so this needs no npm."""
    from c3.harness import resolve, stage_copy

    repo = stage_copy(resolve(Ref(kind="sample", path="java-sample")), tmp_path / "ws")
    target = Ref(kind="benchmark", path=str(repo.root))

    watch.from_here()
    await C3("canned").run_tests(target, version=1)

    _assert_the_loop_stayed_free(watch)
    assert any("mvnw" in one for one in watch.started), watch.started


async def test_the_trained_arm_leaves_the_loop_free(tmp_path, watch, monkeypatch) -> None:
    """The model server is a process the arm talks to line by line, and every
    line it waits for is a wait on the loop unless the arm waits elsewhere."""
    import c3.detect.trained as trained

    from .test_trained_arm import _repo

    class Watched:
        """The model process as the arm sees it, without the model."""

        failure = ""

        def __init__(self, model_dir: object, *, python: str | None = None) -> None:
            pass

        def __enter__(self) -> "Watched":
            watch.note("start the model process")
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def ask(self, methods: list[str]) -> list[dict]:
            watch.note(f"ask about {len(methods)} methods")
            return [{"vulnerable": False, "score": 0.0} for _ in methods]

    monkeypatch.setattr(trained, "ModelProcess", Watched)
    root = _repo(tmp_path)

    watch.from_here()
    await trained.TrainedArm(model_dir=str(tmp_path / "model")).scan(
        str(root), ["src/Accounts.java"]
    )

    _assert_the_loop_stayed_free(watch)
