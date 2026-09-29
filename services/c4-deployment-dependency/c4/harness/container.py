"""Run a project's steps inside a container, one at a time, and record what happened.

The same lane serves two purposes on purpose. Staging uses it to prove a release
candidate before anyone is asked to approve it, and the study uses it to observe
what an update actually does to a project. Because the ground truth of the study
is observed by exactly the machinery the product relies on, a number in a table
and a verdict on the deployment page mean the same thing.

The project is copied into a fresh container rather than mounted, so nothing the
container writes (a root owned `node_modules`, a lockfile) lands on the host, and
cleaning up is removing the container; the one exception is an optional package
cache, a Docker volume that only speeds downloads up. Every step runs separately, so each has
its own exit code, time and output, and a step after a failure is `not-run`
rather than run against a broken tree. A step that downloads and failed because
the download did is `unavailable`, not `failed`: the network is not the project. Containers carry a label, and only
containers with this lane's label are ever removed.
"""

import re
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

#: Node 22, because the generated API runs under --experimental-strip-types,
#: which needs 22.6 or later. Pinned by digest, so a rerun of the study runs
#: exactly this toolchain: node v22.23.3, pulled 2026-09-27.
IMAGE = (
    "node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c"
)

#: MongoDB 8.0, the release Atlas's free tier runs ("free clusters stay on a
#: major version (currently, MongoDB 8.0)", Atlas's version documentation, read
#: 2026-10-01), so staging reads and writes what production will. Pinned by
#: digest: mongo 8.0.32, pulled 2026-10-01.
DATABASE_IMAGE = "mongo:8.0@sha256:4968f22d0c6c10ef29952f3e807f62872ba22b3312f25803564fbfc08255efc2"

LABEL = "sdlc.c4.lane"

#: Enough memory for an install and a test run, on a machine with under 6 GB.
MEMORY = "1g"

TAIL_LINES = 40

#: Set in every lane container: npm's update notice, funding and audit lines
#: are about npm, not the project, and would crowd a step's tail.
ENVIRONMENT = {
    "npm_config_update_notifier": "false",
    "npm_config_fund": "false",
    "npm_config_audit": "false",
}


#: Output that says a download failed, not the project: a transfer cut short, a
#: connection reset or refused, a name that did not resolve. Read only for steps
#: that download (`StepSpec.downloads`), because a project's own tests can print
#: a refused connection for reasons that are entirely the project's.
_UNAVAILABLE = re.compile(
    r"Could not transfer artifact"
    r"|Premature end of Content-Length"
    r"|Connection reset"
    r"|Connect(?:ion)? timed out"
    r"|Read timed out"
    r"|Temporary failure in name resolution"
    r"|\bE(?:CONNRESET|TIMEDOUT|AI_AGAIN|CONNREFUSED|NOTFOUND|SOCKETTIMEOUT)\b"
    r"|socket hang up"
    r"|network request to \S+ failed",
    re.IGNORECASE,
)


def download_failure(output: str) -> str | None:
    """The first line showing that a download failed, or None."""
    for line in output.splitlines():
        if _UNAVAILABLE.search(line):
            return line.strip()
    return None


@dataclass(frozen=True)
class StepSpec:
    name: str
    command: str
    timeout: int = 600
    #: The step fetches from a registry or a repository, so a failure in it may
    #: be the network's rather than the project's, and is checked for that.
    downloads: bool = False


@dataclass(frozen=True)
class StepRun:
    name: str
    command: str
    exit_code: int | None
    outcome: str
    seconds: float | None
    output: str = ""

    @property
    def tail(self) -> str:
        return "\n".join(self.output.strip().splitlines()[-TAIL_LINES:])


@dataclass
class LaneResult:
    steps: list[StepRun] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(step.outcome == "passed" for step in self.steps)


def docker_unavailable() -> str | None:
    """Why the lane cannot run here, or None when it can."""
    docker = shutil.which("docker")
    if docker is None:
        return "docker is not installed"
    done = subprocess.run(
        [docker, "info", "--format", "{{.ServerVersion}}"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if done.returncode != 0:
        return "the Docker daemon is not answering"
    return None


#: Package caches the lane can share between runs, by image family: a Docker
#: managed volume, never a directory on the host. npm checks every tarball it
#: takes from its cache against the lockfile's integrity hash, and Maven reads
#: an artifact from its local repository only by its exact coordinates, so a
#: shared cache changes how long a run takes and never what it installs.
NPM_CACHE = {"c4-lane-npm-cache": "/root/.npm"}
MAVEN_CACHE = {"c4-lane-maven-repository": "/root/.m2"}


class Lane:
    """One fresh container per run, removed afterwards whatever happened."""

    def __init__(
        self,
        image: str = IMAGE,
        *,
        memory: str = MEMORY,
        label: str = LABEL,
        caches: dict[str, str] | None = None,
    ) -> None:
        self.image = image
        self.memory = memory
        self.label = label
        #: Volume name to the path it is mounted at. None shares nothing.
        self.caches = caches or {}

    def _docker(self, *args: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False
        )

    def run(self, files: dict[str, str], steps: list[StepSpec]) -> LaneResult:
        name = f"c4-lane-{uuid.uuid4().hex[:12]}"
        result = LaneResult()
        for volume in self.caches:
            # Idempotent: an existing volume is answered with its name.
            self._docker("volume", "create", "--label", f"{self.label}=1", volume)
        started = self._docker(
            "run",
            "-d",
            "--name",
            name,
            "--label",
            f"{self.label}=1",
            "--memory",
            self.memory,
            *[flag for key, value in ENVIRONMENT.items() for flag in ("-e", f"{key}={value}")],
            *[flag for volume, path in self.caches.items() for flag in ("-v", f"{volume}:{path}")],
            "-w",
            "/work",
            self.image,
            "sleep",
            "infinity",
        )
        if started.returncode != 0:
            raise RuntimeError(f"the lane could not start a container: {started.stderr.strip()}")
        try:
            with tempfile.TemporaryDirectory(prefix="c4-lane-") as scratch:
                root = Path(scratch)
                for path, content in files.items():
                    target = root / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content)
                copied = self._docker("cp", f"{root}/.", f"{name}:/work")
                if copied.returncode != 0:
                    raise RuntimeError(
                        f"the project could not be copied in: {copied.stderr.strip()}"
                    )
            failed = False
            for step in steps:
                if failed:
                    result.steps.append(StepRun(step.name, step.command, None, "not-run", None))
                    continue
                run = self._exec(name, step)
                result.steps.append(run)
                failed = run.outcome != "passed"
        finally:
            self._docker("rm", "-f", name)
        return result

    def _exec(self, name: str, step: StepSpec) -> StepRun:
        began = time.monotonic()
        try:
            done = self._docker("exec", name, "sh", "-c", step.command, timeout=step.timeout)
        except subprocess.TimeoutExpired as expired:
            output = (
                (expired.stdout or b"").decode()
                if isinstance(expired.stdout, bytes)
                else (expired.stdout or "")
            )
            return StepRun(
                step.name, step.command, None, "timed-out", time.monotonic() - began, output
            )
        output = (done.stdout or "") + (done.stderr or "")
        if done.returncode == 0:
            outcome = "passed"
        elif step.downloads and download_failure(output):
            # A download that failed says nothing about the project or the
            # update, so it is not a failure of either.
            outcome = "unavailable"
        else:
            outcome = "failed"
        return StepRun(
            step.name, step.command, done.returncode, outcome, time.monotonic() - began, output
        )
