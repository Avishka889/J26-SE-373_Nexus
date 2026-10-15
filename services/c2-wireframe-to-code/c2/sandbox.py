"""The sandboxed build: install, typecheck, tests, honestly reported.

A subprocess in a scrubbed temporary directory, because Docker is not
installed in this environment, and the report says so in words including what
that does and does not guarantee. Every step's outcome is recorded as it
happened: a step after a failure is `not-run`, a step that hit its cap is
`timed-out`, and neither is ever `passed`.

The environment is scrubbed to a small allow list: the platform's process
holds provider keys and database URLs, and a generated project's install
scripts have no business reading any of them.
"""

import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sdlc_contracts import BuildReport, BuildStepReport

#: Generous, because a cold npm install legitimately takes minutes; the cap
#: exists for hangs, not for slowness.
PER_STEP_TIMEOUT_SECONDS = 420.0
LOG_TAIL_CHARS = 4000

ISOLATION = (
    "A subprocess in a scrubbed temporary directory: only PATH, HOME and an "
    "npm cache reach the child, with time and output caps per step. Not a "
    "container, because Docker is not installed here, so kernel level "
    "isolation is not claimed: this guards against accidents and leaked "
    "environment, not against a hostile build script."
)


@dataclass(frozen=True)
class BuildStep:
    name: str
    command: tuple[str, ...]


DEFAULT_STEPS: tuple[BuildStep, ...] = (
    BuildStep(name="install", command=("npm", "install", "--no-audit", "--no-fund")),
    BuildStep(name="typecheck", command=("npm", "run", "typecheck")),
    BuildStep(name="unit tests", command=("npm", "test")),
)


def toolchain() -> str:
    """What actually runs the build, measured rather than assumed."""
    try:
        node = subprocess.run(
            ["node", "--version"], capture_output=True, text=True, timeout=10
        ).stdout.strip()
        npm = subprocess.run(
            ["npm", "--version"], capture_output=True, text=True, timeout=10
        ).stdout.strip()
        return f"node {node} / npm {npm}"
    except (OSError, subprocess.SubprocessError):
        return "node and npm not found"


def _scrubbed_env(cache_dir: str) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "CI": "1",
        # Shared across runs so the second install is seconds, not minutes.
        "npm_config_cache": cache_dir,
    }


def _tail(text: str) -> str:
    return text[-LOG_TAIL_CHARS:]


def run_build(
    sources: dict[str, str],
    *,
    steps: tuple[BuildStep, ...] = DEFAULT_STEPS,
    per_step_timeout: float = PER_STEP_TIMEOUT_SECONDS,
    workdir: str | None = None,
    on_step: Callable[[str], None] | None = None,
) -> BuildReport:
    """Write the sources into isolation, run the steps, report what happened."""
    # Whoever made the directory owns it. A caller that passes one wants the
    # tree afterwards (the preview serves it, a test inspects it); a build that
    # made its own has no reader for it and deletes it on the way out. Eight of
    # these were found holding 1.1 GB after one afternoon of live runs.
    owned = workdir is None
    root = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="c2-build-"))
    root.mkdir(parents=True, exist_ok=True)
    for path, content in sources.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    cache_dir = str(Path(tempfile.gettempdir()) / "c2-npm-cache")
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    env = _scrubbed_env(cache_dir)

    reports: list[BuildStepReport] = []
    failed = False
    for step in steps:
        if failed:
            reports.append(
                BuildStepReport(
                    name=step.name,
                    command=" ".join(step.command),
                    outcome="not-run",
                    log_tail="",
                )
            )
            continue
        if on_step is not None:
            on_step(step.name)
        started = time.monotonic()
        try:
            completed = subprocess.run(
                step.command,
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                timeout=per_step_timeout,
            )
            duration = time.monotonic() - started
            output = completed.stdout + completed.stderr
            outcome = "passed" if completed.returncode == 0 else "failed"
            if outcome == "failed":
                failed = True
            reports.append(
                BuildStepReport(
                    name=step.name,
                    command=" ".join(step.command),
                    outcome=outcome,  # type: ignore[arg-type]
                    duration_seconds=round(duration, 2),
                    log_tail=_tail(output),
                )
            )
        except subprocess.TimeoutExpired as expired:
            duration = time.monotonic() - started
            failed = True
            output = (
                (expired.stdout or b"").decode(errors="replace")
                if isinstance(expired.stdout, bytes)
                else (expired.stdout or "")
            )
            reports.append(
                BuildStepReport(
                    name=step.name,
                    command=" ".join(step.command),
                    outcome="timed-out",
                    duration_seconds=round(duration, 2),
                    log_tail=_tail(output),
                )
            )
        except OSError as error:
            failed = True
            reports.append(
                BuildStepReport(
                    name=step.name,
                    command=" ".join(step.command),
                    outcome="failed",
                    duration_seconds=round(time.monotonic() - started, 2),
                    log_tail=str(error),
                )
            )

    report = BuildReport(toolchain=toolchain(), isolation=ISOLATION, steps=reports)
    if owned:
        cleanup(str(root))
    return report


def cleanup(workdir: str) -> None:
    """Remove a build tree. Never raises: a directory already gone is the
    outcome this wanted."""
    shutil.rmtree(workdir, ignore_errors=True)
