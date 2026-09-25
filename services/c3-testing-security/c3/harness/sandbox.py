"""Running somebody else's build, honestly and with the doors shut.

C2 has a sandbox already and this one is its sibling, with three differences
that matter enough to justify a second module rather than a shared one.

**A directory, not a dict of sources.** C2 writes the files it just generated
and throws the tree away. C3 runs four tools over the same repository in
sequence, and two of them (mutation, coverage) are minutes of work that must
land beside the first, so the tree is the unit and the caller owns it.

**The whole output, not a tail.** C2 reports what a human reads. Every step
here feeds a parser: a JSON report, an XML surefire file, a mutation matrix.
The tail is for the report; the parser gets the rest.

**A home of its own.** C2 passes the real `HOME` through, so an npm cache is
warm. That also puts `~/.npmrc`, `~/.gitconfig`, `~/.aws` and every other
dotfile credential inside the sandbox, and this component runs tools that
fetch and execute code from the network. The home here is a directory this
module owns: the caches stay warm because they live in it across runs, and
nothing in the developer's home is reachable from inside.

What is not claimed: this is not a container. Docker is available on this
machine but the generated projects are not built to run in one, and adding an
image build per stage would cost more than it guards. This stops accidents and
leaked environment. It does not stop a hostile build script.
"""

import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

#: Long enough for a cold `npm install` or a Maven wrapper fetching the world,
#: because the cap is for hangs rather than for slowness. Mutation gets its own,
#: passed by the lane that runs it.
PER_STEP_TIMEOUT_SECONDS = 600.0

#: What a report carries. The parser gets `output` in full.
LOG_TAIL_CHARS = 4000

StepOutcome = Literal["passed", "failed", "not-run", "timed-out"]

ISOLATION = (
    "A subprocess under a home directory this component owns, with a small "
    "environment allow list and time caps per step. Package caches live in "
    "that home, so nothing in the developer's home, including any dotfile "
    "credential, is reachable from inside. Not a container: this guards "
    "against accidents and leaked environment, not against a hostile build."
)


def cache_home() -> Path:
    """The home every sandboxed step runs under.

    Shared across runs on purpose: a cold `npm install` is minutes and a cold
    Maven wrapper downloads Maven itself, so throwing the caches away between
    stages would make the harness unusable for the thing it exists to measure.
    """
    home = Path(os.environ.get("C3_SANDBOX_HOME") or Path(tempfile.gettempdir()) / "c3-home")
    home.mkdir(parents=True, exist_ok=True)
    return home


def _java_home() -> str:
    """Where the `java` on PATH lives, as a JDK home.

    Derived rather than required, because this machine does not export
    `JAVA_HOME` and the Maven Wrapper prints a warning and then guesses. It
    guesses correctly here, but a lane that depends on a guess is a lane that
    breaks on the first machine that has two JDKs.
    """
    found = shutil.which("java")
    if not found:
        return ""
    home = Path(found).resolve().parent.parent
    return str(home) if (home / "bin" / "javac").exists() else ""


def sandbox_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """The whole environment a step gets, and nothing else.

    `PATH` because there is no way to run node or java without it, and the
    two of them are what this is for. Everything else is either a cache
    location or a flag saying "you are not on a terminal".
    """
    home = cache_home()
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "CI": "1",
        "NO_COLOR": "1",
        "npm_config_cache": str(home / ".npm"),
        # Never run a package's own install scripts. The generated project is
        # written by a model and its dependencies are whatever the model asked
        # for, so an install here is a download, not an execution.
        "npm_config_ignore_scripts": "true",
        "npm_config_fund": "false",
        "npm_config_audit": "false",
    }
    if java_home := os.environ.get("JAVA_HOME") or _java_home():
        env["JAVA_HOME"] = java_home
    env.update(extra or {})
    return env


@dataclass(frozen=True)
class Step:
    """One command, and what to call it in the report."""

    name: str
    command: tuple[str, ...]
    #: Relative to the repository root, for a monorepo whose app is in apps/web.
    cwd: str = "."
    timeout: float = PER_STEP_TIMEOUT_SECONDS
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class StepResult:
    """What happened, in the words of what happened.

    `outcome` is never inferred from anything but the exit status and the
    clock. A tool that writes "0 tests" and exits zero passed the step; whether
    zero tests is a result is the lane's question, not the sandbox's.
    """

    name: str
    command: str
    outcome: StepOutcome
    duration_seconds: float = 0.0
    exit_code: int | None = None
    output: str = ""

    @property
    def passed(self) -> bool:
        return self.outcome == "passed"

    @property
    def tail(self) -> str:
        return self.output[-LOG_TAIL_CHARS:]


def not_run(step: Step, why: str) -> StepResult:
    """A step that never started, saying so.

    The distinction the component argues for, at the smallest scale it exists:
    a step nobody ran is not a step that passed, and the reason it did not run
    belongs on it.
    """
    return StepResult(
        name=step.name,
        command=" ".join(step.command),
        outcome="not-run",
        output=why,
    )


def _runnable(command: str, *, cwd: Path, path: str) -> bool:
    """Whether this command can actually be started from that directory.

    Two kinds of command reach here and they are found differently. A bare name
    (`npm`, `java`) is looked up on PATH. A path (`./mvnw`) is a file in the
    project, and `shutil.which` would resolve it against this process's working
    directory rather than the step's, which is how the Java lane first reported
    a Maven Wrapper that was sitting right there as a missing tool.
    """
    if os.sep in command or command.startswith("."):
        candidate = (cwd / command).resolve()
        return candidate.is_file() and os.access(candidate, os.X_OK)
    return shutil.which(command, path=path) is not None


class Sandbox:
    """A repository on disk, and a way to run things in it.

    Deliberately without a policy about failure. C2's build stops at the first
    failing step because a typecheck failure makes the test run meaningless.
    Here a failing test suite is the input to the next four stages, so the lane
    decides what a failure means and the sandbox only reports it.
    """

    def __init__(self, root: Path | str, *, env: dict[str, str] | None = None) -> None:
        self.root = Path(root)
        self._env = sandbox_env(env)

    def run(self, step: Step) -> StepResult:
        command = " ".join(step.command)
        cwd = self.root / step.cwd
        env = {**self._env, **step.env}

        if not _runnable(step.command[0], cwd=cwd, path=env["PATH"]):
            return StepResult(
                name=step.name,
                command=command,
                outcome="failed",
                output=(
                    f"{step.command[0]} cannot be run from {step.cwd}: it is neither on "
                    "the sandbox PATH nor an executable file there. This is a missing "
                    "tool, not a failing build."
                ),
            )
        if not cwd.is_dir():
            return StepResult(
                name=step.name,
                command=command,
                outcome="failed",
                output=f"{step.cwd} does not exist in the target, so there was nothing to run in",
            )

        started = time.monotonic()
        try:
            completed = subprocess.run(
                step.command,
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                timeout=step.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as expired:
            return StepResult(
                name=step.name,
                command=command,
                outcome="timed-out",
                duration_seconds=round(time.monotonic() - started, 2),
                output=_decode(expired.stdout) + _decode(expired.stderr),
            )
        except OSError as error:
            return StepResult(
                name=step.name,
                command=command,
                outcome="failed",
                duration_seconds=round(time.monotonic() - started, 2),
                output=str(error),
            )

        return StepResult(
            name=step.name,
            command=command,
            outcome="passed" if completed.returncode == 0 else "failed",
            duration_seconds=round(time.monotonic() - started, 2),
            exit_code=completed.returncode,
            output=completed.stdout + completed.stderr,
        )

    def read(self, path: str) -> str | None:
        """A file the run produced, or None. Never raises: an absent report is
        the answer, and the caller says what its absence means."""
        target = self.root / path
        try:
            return target.read_text(errors="replace")
        except OSError:
            return None


def _decode(value: bytes | str | None) -> str:
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else value


def _version(line: str) -> str:
    """The version out of a `--version` line, however the tool spells it."""
    quoted = re.search(r'"([^"]+)"', line)
    if quoted:
        return quoted.group(1)
    numbered = re.search(r"\d[\w.+-]*", line)
    return numbered.group(0) if numbered else line.strip()


def toolchain() -> str:
    """What actually ran, measured rather than assumed.

    Every number this component produces is stamped with it, because "vitest"
    is not a provenance and a coverage figure nobody can reproduce is not a
    result anybody can use.
    """
    parts: list[str] = []
    for label, command in (
        ("node", ("node", "--version")),
        ("npm", ("npm", "--version")),
        ("java", ("java", "-version")),
    ):
        try:
            answer = subprocess.run(
                list(command), capture_output=True, text=True, timeout=15, check=False
            )
        except (OSError, subprocess.SubprocessError):
            continue
        # `java -version` writes to stderr, which is a decades old quirk, and
        # says `openjdk version "21.0.11" 2026-04-21` where the others say
        # `22.17.0`. One shape out, so the stamp on a number is readable.
        text = (answer.stdout or answer.stderr or "").strip().splitlines()
        if text:
            parts.append(f"{label} {_version(text[0])}")
    return " / ".join(parts) if parts else "no toolchain found on PATH"
