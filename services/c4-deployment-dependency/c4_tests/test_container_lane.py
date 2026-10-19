"""The container lane, run for real where Docker answers.

The claim the lane makes for the study is that an observed break is a break the
container saw: a step's outcome is its exit code, a step after a failure did not
run, and the container is gone afterwards. The planted fault here is a syntax
error, checked by `node --check`, so the test needs no network: the image is the
only thing it pulls, and it is pinned.
"""

import json
import shutil
import subprocess

import pytest
from c4.eval.cases import Observed
from c4.eval.rubric import level
from c4.harness.container import (
    LABEL,
    Lane,
    LaneResult,
    StepRun,
    StepSpec,
    download_failure,
)
from c4.harness.reproduce import (
    INSTALLED_SCRIPT,
    PIN_NOT_APPLIED,
    PinNotApplied,
    installed_script,
    new_warnings,
    observed,
    pin_step,
    reproduce,
)
from c4.intake.lockfile import pin

from .docker import needs_docker

CHECK = [
    StepSpec("compile", "node --check app.js", timeout=60),
    StepSpec("test", "node app.js", timeout=60),
]

GOOD = {"app.js": "const total = [1, 2, 3].reduce((a, b) => a + b, 0);\nconsole.log(total);\n"}
BROKEN = {"app.js": "const total = [1, 2, 3].reduce((a, b) => a + b, 0;\nconsole.log(total);\n"}


def _lane_containers() -> list[str]:
    done = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"label={LABEL}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return done.stdout.split()


@pytest.mark.docker
@needs_docker
class TestTheLane:
    def test_every_step_runs_and_says_how_it_went(self) -> None:
        result = Lane().run(GOOD, CHECK)
        assert [(s.name, s.outcome) for s in result.steps] == [
            ("compile", "passed"),
            ("test", "passed"),
        ]
        assert result.steps[1].output.strip() == "6"
        assert all(s.seconds is not None for s in result.steps)

    def test_a_step_after_a_failure_does_not_run(self) -> None:
        result = Lane().run(BROKEN, CHECK)
        assert [(s.name, s.outcome) for s in result.steps] == [
            ("compile", "failed"),
            ("test", "not-run"),
        ]
        assert "SyntaxError" in result.steps[0].tail

    def test_a_planted_fault_is_observed_as_high(self) -> None:
        """Lane, then observation, then rubric: the whole ground truth path."""
        control = Lane().run(GOOD, CHECK)
        candidate = Lane().run(BROKEN, CHECK)
        case = Observed(
            method="container-reproduction",
            captured_at="2026-09-27",
            baseline=[observed(run) for run in control.steps],
            candidate=[observed(run) for run in candidate.steps],
        )
        assert level(case) == "high"

    def test_nothing_is_left_behind(self) -> None:
        before = set(_lane_containers())
        Lane().run(GOOD, CHECK)
        assert set(_lane_containers()) <= before


def test_only_new_warnings_that_name_the_package_count() -> None:
    control = [
        StepRun(
            "resolution", "npm install", 0, "passed", 1.0, "npm warn deprecated old-thing@1.0.0"
        )
    ]
    candidate = [
        StepRun(
            "resolution",
            "npm install",
            0,
            "passed",
            1.0,
            "npm warn deprecated old-thing@1.0.0\n"
            "npm warn deprecated express@5.1.0: use the router package\n"
            "npm warn something unrelated\n"
            "added 60 packages",
        )
    ]
    assert new_warnings(control, candidate, "express") == [
        "npm warn deprecated express@5.1.0: use the router package"
    ]


def test_the_same_warning_at_another_second_is_not_new() -> None:
    """depd stamps each deprecation with the time, and node with its process id."""
    control = [
        StepRun(
            "test",
            "node check.js",
            0,
            "passed",
            1.0,
            "Sun, 27 Sep 2026 08:07:05 GMT express deprecated app.del: Use app.delete instead\n"
            "(node:17) [DEP0040] DeprecationWarning: The `punycode` module is deprecated",
        )
    ]
    candidate = [
        StepRun(
            "test",
            "node check.js",
            0,
            "passed",
            1.0,
            "Sun, 27 Sep 2026 08:09:41 GMT express deprecated app.del: Use app.delete instead\n"
            "(node:23) [DEP0040] DeprecationWarning: The `punycode` module is deprecated",
        )
    ]
    assert new_warnings(control, candidate, "express") == []


MAVEN_TRUNCATED = (
    "[ERROR] \tCould not transfer artifact org.apache.maven.surefire:surefire-shared-utils:jar:"
    "3.5.6 from/to central (https://repo.maven.apache.org/maven2): Premature end of "
    "Content-Length delimited message body (expected: 2,996,047; received: 2,410,048)"
)


@pytest.mark.parametrize(
    ("output", "lost"),
    [
        (MAVEN_TRUNCATED, True),
        ("npm error code ECONNRESET\nnpm error network aborted", True),
        ("npm error code EAI_AGAIN\nnpm error request to https://registry.npmjs.org failed", True),
        ("npm error code ETARGET\nnpm error notarget No matching version found for x@9.9.9", False),
        ("npm error code ERESOLVE\nnpm error ERESOLVE unable to resolve dependency tree", False),
        ("AssertionError [ERR_ASSERTION]: 404 == 204", False),
    ],
)
def test_a_lost_download_is_told_apart_from_a_resolution_that_failed(output, lost) -> None:
    """A version that does not exist, or a peer conflict, is a real break; a
    connection that dropped is not."""
    assert (download_failure(output) is not None) is lost


@pytest.mark.docker
@needs_docker
def test_a_step_that_downloads_is_unavailable_when_the_download_fails() -> None:
    fails = "echo 'npm error code ECONNRESET' >&2; exit 1"
    result = Lane().run(
        {},
        [
            StepSpec("resolution", fails, timeout=60, downloads=True),
            StepSpec("test", "true", timeout=60),
        ],
    )
    assert [(s.name, s.outcome) for s in result.steps] == [
        ("resolution", "unavailable"),
        ("test", "not-run"),
    ]


@pytest.mark.docker
@needs_docker
def test_the_same_output_from_a_step_that_does_not_download_is_a_failure() -> None:
    """A project's own test can print a refused connection, and that is the project's."""
    result = Lane().run(
        {}, [StepSpec("test", "echo 'Error: connect ECONNREFUSED 127.0.0.1:27017'; exit 1")]
    )
    assert result.steps[0].outcome == "failed"


@pytest.mark.docker
@needs_docker
def test_a_shared_cache_keeps_what_is_under_its_path_and_nothing_else() -> None:
    """The cache is the one thing a run leaves behind, and only under its own path."""
    volume = "c4-lane-test-cache"
    lane = Lane(caches={volume: "/cache"})
    try:
        lane.run({}, [StepSpec("resolution", "echo kept > /cache/marker; echo lost > marker")])
        second = lane.run({}, [StepSpec("test", "cat /cache/marker && test ! -e marker")])
        assert second.steps[0].outcome == "passed", second.steps[0].output
        assert second.steps[0].output.strip() == "kept"
    finally:
        subprocess.run(["docker", "volume", "rm", "-f", volume], capture_output=True, check=False)


TWO_WORKSPACES = {
    "package.json": json.dumps({"name": "two", "private": True, "workspaces": ["a", "b"]}),
    "a/package.json": json.dumps({"name": "a", "dependencies": {"ms": "^2.1.0"}}),
    "b/package.json": json.dumps({"name": "b", "dependencies": {"is-number": "^7.0.0"}}),
}


@pytest.mark.docker
@pytest.mark.sandbox
@needs_docker
@pytest.mark.skipif(shutil.which("npm") is None, reason="needs node and npm to pin the tree")
def test_pinning_one_workspace_still_installs_the_whole_project() -> None:
    """npm installs only the named workspace's dependencies under `-w`, which
    left a generated API without Express when its web side was pinned."""
    files = {
        **TWO_WORKSPACES,
        "package-lock.json": pin(TWO_WORKSPACES).text,
        INSTALLED_SCRIPT: installed_script(),
    }
    files["check.js"] = (
        "const assert = require('node:assert');\n"
        "assert.equal(require('./a/package.json').dependencies.ms, '2.1.2');\n"
        "const ms = require.resolve('ms/package.json', { paths: ['a'] });\n"
        "assert.equal(require(ms).version, '2.1.2');\n"
        "require.resolve('is-number', { paths: ['b'] });\n"
    )
    check = StepSpec("test", "node check.js", timeout=60)
    result = Lane().run(files, [pin_step("ms", "2.1.2", ("a",)), check])
    assert [(s.name, s.outcome) for s in result.steps] == [
        ("resolution", "passed"),
        ("test", "passed"),
    ], result.steps[-1].output
    assert "a resolves ms@2.1.2" in result.steps[0].output


def _installed(place_versions: dict[str, str]) -> dict[str, str]:
    """A tree with `left-pad` installed at the given versions, under the given places."""
    files = {INSTALLED_SCRIPT: installed_script()}
    for place, version in place_versions.items():
        prefix = "" if place == "." else f"{place}/"
        files[f"{prefix}node_modules/left-pad/package.json"] = json.dumps({"version": version})
    return files


@pytest.mark.docker
@needs_docker
class TestThePinCheck:
    """The check that a pin took, looked up the way Node looks a package up."""

    def test_the_pinned_version_passes_and_is_printed(self) -> None:
        result = Lane().run(
            _installed({".": "1.3.0"}),
            [StepSpec("resolution", f"node {INSTALLED_SCRIPT} left-pad 1.3.0")],
        )
        assert result.steps[0].outcome == "passed"
        assert ". resolves left-pad@1.3.0" in result.steps[0].output

    def test_a_workspace_that_resolves_its_own_nested_copy_is_caught(self) -> None:
        """The root has 1.3.0, and workspace a has a nested 1.1.0 that Node
        would load first; a pin to 1.3.0 did not take for a."""
        result = Lane().run(
            _installed({".": "1.3.0", "a": "1.1.0"}),
            [StepSpec("resolution", f"node {INSTALLED_SCRIPT} left-pad 1.3.0 a")],
        )
        assert result.steps[0].outcome == "failed"
        assert result.steps[0].exit_code == 3
        assert PIN_NOT_APPLIED in result.steps[0].output


class _Lane:
    """A lane that answers every run with the same resolution output."""

    image = "fake"

    def __init__(self, output: str) -> None:
        self.output = output

    def run(self, files, steps):
        return LaneResult(
            steps=[StepRun("resolution", steps[0].command, 3, "failed", 1.0, self.output)]
        )


def test_a_pin_that_did_not_take_stops_the_study_instead_of_being_scored() -> None:
    lane = _Lane(f"apps/api resolves typescript@5.9.3\n{PIN_NOT_APPLIED}: typescript ...")
    with pytest.raises(PinNotApplied):
        reproduce(lane, {}, package="typescript", old="5.9.3", new="7.0.2", steps=[])


def test_a_time_of_day_is_not_what_makes_a_warning_new() -> None:
    """Vite starts its lines with the time of day."""
    line = "[vite] warning: `esbuild` option was specified by a plugin. This option is deprecated"
    control = [StepRun("build", "vite build", 0, "passed", 1.0, f"9:05:59 AM {line}")]
    candidate = [StepRun("build", "vite build", 0, "passed", 1.0, f"9:07:12 AM {line}")]
    assert new_warnings(control, candidate, "vite") == []
