"""The sandbox: honest step outcomes, scrubbed environment, and the real build.

The machinery is tested with trivial commands, so CI without node still
proves the honesty rules. The real npm build of the generated fixture
monorepo runs behind the `sandbox` marker: it is the load bearing proof that
what the generators emit actually typechecks and passes its own tests under
the real toolchain.
"""

import shutil

import pytest
from c2.codegen.monorepo import generate_monorepo
from c2.contract.rule_arm import generate_rule_contract
from c2.sandbox import BuildStep, run_build

from .design_fixture import graph, scope, wireframes

needs_npm = pytest.mark.skipif(shutil.which("npm") is None, reason="needs node and npm")


class TestTheStepMachinery:
    def test_outcomes_are_recorded_as_they_happened(self, tmp_path) -> None:
        report = run_build(
            {"README.md": "machinery case\n"},
            steps=(
                BuildStep(name="works", command=("true",)),
                BuildStep(name="breaks", command=("false",)),
                BuildStep(name="after the break", command=("true",)),
            ),
            workdir=str(tmp_path),
        )
        outcomes = [(step.name, step.outcome) for step in report.steps]
        assert outcomes == [
            ("works", "passed"),
            ("breaks", "failed"),
            ("after the break", "not-run"),
        ]
        assert report.passed is False

    def test_a_not_run_step_carries_no_duration(self, tmp_path) -> None:
        report = run_build(
            {"README.md": "x\n"},
            steps=(
                BuildStep(name="breaks", command=("false",)),
                BuildStep(name="skipped", command=("true",)),
            ),
            workdir=str(tmp_path),
        )
        skipped = report.steps[1]
        assert skipped.outcome == "not-run"
        assert skipped.duration_seconds is None

    def test_a_hang_times_out_instead_of_hanging_the_run(self, tmp_path) -> None:
        report = run_build(
            {"README.md": "x\n"},
            steps=(BuildStep(name="hangs", command=("sleep", "5")),),
            per_step_timeout=0.5,
            workdir=str(tmp_path),
        )
        assert report.steps[0].outcome == "timed-out"
        assert report.steps[0].duration_seconds is not None

    def test_the_environment_is_scrubbed(self, tmp_path, monkeypatch) -> None:
        """A provider key in the platform's environment must not reach the
        generated project's build."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "planted-key-a1b2c3")
        report = run_build(
            {"README.md": "x\n"},
            steps=(BuildStep(name="env", command=("env",)),),
            workdir=str(tmp_path),
        )
        assert report.steps[0].outcome == "passed"
        assert "planted-key-a1b2c3" not in report.steps[0].log_tail
        assert "ANTHROPIC_API_KEY" not in report.steps[0].log_tail

    def test_the_log_tail_is_the_real_output(self, tmp_path) -> None:
        report = run_build(
            {"README.md": "x\n"},
            steps=(BuildStep(name="says", command=("echo", "the real output")),),
            workdir=str(tmp_path),
        )
        assert "the real output" in report.steps[0].log_tail

    def test_the_isolation_statement_is_honest_about_docker(self, tmp_path) -> None:
        report = run_build(
            {"README.md": "x\n"},
            steps=(BuildStep(name="noop", command=("true",)),),
            workdir=str(tmp_path),
        )
        assert "Docker is not installed" in report.isolation
        assert "not claimed" in report.isolation


@pytest.mark.sandbox
@needs_npm
class TestTheRealBuild:
    def test_the_generated_monorepo_installs_typechecks_and_tests(self, tmp_path) -> None:
        """The load bearing proof: the generators' output survives the real
        toolchain. Slow (a cold npm install), which is what the marker is for."""
        contract = generate_rule_contract(1, graph(), wireframes(), scope())
        files = generate_monorepo(
            "ShopFlow", contract, wireframes(), scope(), design_version=1, arm="rule"
        )
        sources = {generated.path: generated.content for generated in files.files}

        report = run_build(sources, workdir=str(tmp_path / "repo"))

        outcomes = {step.name: step.outcome for step in report.steps}
        transcript = "\n\n".join(
            f"== {step.name} ({step.outcome}) ==\n{step.log_tail}" for step in report.steps
        )
        assert outcomes == {
            "install": "passed",
            "typecheck": "passed",
            "unit tests": "passed",
        }, transcript
        assert report.passed


@pytest.mark.sandbox
@needs_npm
class TestEveryContractShapeCompiles:
    """The generators must handle every shape the contract type permits.

    The ablation compares a rule arm and an LLM arm on, among other things,
    whether their contracts compile. If the generators only handle the shapes
    the rule arm emits, that measurement reports a blind spot in this component
    as a property of the other arm, which would be wrong and not obviously
    wrong. This is what stops that: a contract using every field type, a
    literal sub path beside a parameterised one, and a nested route with two
    parameters, built with the real toolchain.
    """

    def test_a_kitchen_sink_contract_installs_typechecks_and_tests(self, tmp_path) -> None:
        from .kitchen_contract import kitchen_sink_contract

        contract = kitchen_sink_contract()
        files = generate_monorepo(
            "Kitchen Sink", contract, wireframes(), scope(), design_version=1, arm="llm"
        )
        report = run_build(
            {generated.path: generated.content for generated in files.files},
            workdir=str(tmp_path / "kitchen"),
        )
        transcript = "\n\n".join(
            f"== {step.name} ({step.outcome}) ==\n{step.log_tail}" for step in report.steps
        )
        assert report.passed, transcript


class TestWhoOwnsTheDirectory:
    """A build that made its own directory deletes it; one that was given a
    directory leaves it alone.

    Found by looking at /tmp after an afternoon of live runs: eight build trees
    holding 1.1 GB, because `cleanup` was written and never called. The rule is
    ownership rather than a flag, so a caller that wants the tree (the preview
    serves it) keeps it by passing one.
    """

    def test_a_build_that_made_its_own_directory_removes_it(self) -> None:
        import glob

        before = set(glob.glob("/tmp/c2-build-*"))
        run_build({"README.md": "x\n"}, steps=(BuildStep(name="ok", command=("true",)),))
        after = set(glob.glob("/tmp/c2-build-*"))
        assert after == before, "the build left its own directory behind"

    def test_a_directory_it_was_given_survives(self, tmp_path) -> None:
        workdir = tmp_path / "kept"
        run_build(
            {"README.md": "x\n"},
            steps=(BuildStep(name="ok", command=("true",)),),
            workdir=str(workdir),
        )
        assert (workdir / "README.md").exists()
