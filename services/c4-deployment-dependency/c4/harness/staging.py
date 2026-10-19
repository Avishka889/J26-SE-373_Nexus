"""Staging verification: the candidate built from its own Dockerfile, booted, and asked what it is.

This is the preview in preview then promote. The deployment review decides
about a candidate that has already been built, tested, started and answered,
and a release starts exactly this image. `verified` is computed by the
contract from what is recorded here, never set.

**The steps, in order**, each recorded with its command, outcome, duration and
the tail of its output (for a step that failed, what failed comes first, from
wherever it was printed); a step that fails leaves the later ones not run, and
nothing is retried:

1. `candidate`: the files hash to the candidate hash pipeline generation fixed.
   Anything else is a different candidate, which the review did not see.
2. `lockfile`: every included update is in the candidate's lockfile at its
   version, in the workspace that declares it. An update npm could not apply
   is found missing here.
3. `install`: `docker build --target deps`, which runs `npm ci` from the lockfile.
4. `test`: `docker build --target test`, the typecheck and the tests.
5. `image`: `docker build`, the frontend built, dev dependencies pruned, and the
   runtime image tagged. Its id is the digest a release starts.
6. `database`, only for code that reads MONGODB_URL: a throwaway MongoDB, the
   release Atlas's free tier runs, on a private network of its own, answering
   a ping within a minute. The candidate is then booted on that network with
   MONGODB_URL naming it, so it keeps its records the way a release that has
   a database does. A backend that only declares the name in `.env.example`
   gets none: C2 declared it long before any generated code read it.
7. `boot`: the image started on loopback, answering `/release.json` within a
   minute.

Then the fingerprint is read from `/release.json`, and each smoke request is
made once: the page, asking for HTML, and every GET the generated client
declares without a parameter, asking for JSON. A smoke request passes on a 2xx
answer of the kind it asked for, because the backend answers any request that
accepts a page with the app's `index.html`, so a status alone would pass for an
endpoint that is not there.

The intermediate targets are built into the cache only, so they leave no image
behind; the container, and the database and its network when there was one,
are removed when the checks end; the image stays, tagged and labelled, for a
release to start by its id. The build has the network, to fetch packages from
the registry, and each container runs with 512 MB of memory.
"""

import hashlib
import json
import posixpath
import re
import secrets
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sdlc_contracts import (
    BuildStepReport,
    DependencyUpdate,
    ExcludedUpdate,
    ReleaseCandidate,
    SmokeCheck,
)
from sdlc_contracts.deploy_rules import candidate_hash, fingerprint_file

from ..intake.lockfile import LOCKFILE, resolved_versions
from ..pipeline.layout import Undetectable, detect
from .container import DATABASE_IMAGE, IMAGE
from .steps import smoke_paths

LABEL = "sdlc.c4.lane=staging"
BUILD_TIMEOUT_SECONDS = 1200
BOOT_WITHIN_SECONDS = 60
MEMORY = "512m"
_TAIL = 2000
#: How much of a failed step's account of what failed is kept, besides its tail.
_FAILURES = 6000
#: BuildKit's plain progress puts "#14 3.100 " before every line a step prints.
_PROGRESS = re.compile(r"^#\d+ (?:\d+\.\d+ ?)?")
#: Where vitest's account of its failures starts, and the summary that ends it.
_FAILED_HEADER = re.compile(r"Failed (?:Tests|Suites) \d+")
_SUMMARY = re.compile(r"^\s*Test Files\s")
#: Single lines that say what failed outside that account: a compiler error,
#: npm naming the workspace whose script failed, and the count of failed tests.
_FAILURE_LINE = re.compile(
    r"error TS\d+|^npm (?:error|ERR!) (?:workspace|command sh)|^\s*Tests\s+\d+ failed"
)
#: The time Docker's closing error block puts before each line it repeats.
_REPEATED = re.compile(r"^\d+\.\d+\s+")
#: What the generated backend reads to keep its records in a database.
DATABASE_VARIABLE = "MONGODB_URL"
#: The staging database, as the candidate reaches it on their private network.
DATABASE_URL = "mongodb://database:27017/staging"
_READS_DATABASE = re.compile(r"process\.env(?:\.MONGODB_URL\b|\[\s*[\"']MONGODB_URL[\"']\s*\])")
_CODE = (".ts", ".tsx", ".js", ".mjs", ".cjs")


@dataclass(frozen=True)
class Ran:
    returncode: int
    output: str
    seconds: float


#: Runs a command with a timeout. The product's runs it; tests script it.
Runner = Callable[[list[str], float], Ran]

#: Asks a URL with headers: the status (None when nothing answered), the
#: content type and the body.
Prober = Callable[[str, dict[str, str], float], tuple[int | None, str, str]]


def run(argv: list[str], timeout: float) -> Ran:
    started = time.monotonic()
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as expired:
        output = expired.output or ""
        text = output if isinstance(output, str) else output.decode(errors="replace")
        return Ran(124, text + f"\ntimed out after {timeout:.0f}s", time.monotonic() - started)
    return Ran(done.returncode, done.stdout + done.stderr, time.monotonic() - started)


def probe(url: str, headers: dict[str, str], timeout: float) -> tuple[int | None, str, str]:
    try:
        answer = httpx.get(url, headers=headers, timeout=timeout)
    except httpx.HTTPError as error:
        return None, "", f"{type(error).__name__}: {error}"
    return answer.status_code, answer.headers.get("content-type", ""), answer.text[:_TAIL]


def failure_section(output: str) -> str:
    """The lines of a step's output that say what failed, in the order printed.

    A failed test step ends with Docker's own error block, which repeats the
    last lines the step printed, and with npm going on to the next workspace;
    so the 2,000 characters kept from the end held "Tests 2 failed | 13
    passed" and none of the two tests' names or assertions. This keeps
    vitest's account of its failures whole, and the single lines that name a
    compiler error or the workspace whose script failed, each once.
    """
    kept: list[str] = []
    seen: set[str] = set()
    inside = False
    for raw in output.splitlines():
        line = _PROGRESS.sub("", raw)
        if _FAILED_HEADER.search(line):
            inside = True
        if inside:
            kept.append(line)
            if _SUMMARY.match(line):
                inside = False
            continue
        if _FAILURE_LINE.search(line):
            key = _REPEATED.sub("", line).strip()
            if key not in seen:
                seen.add(key)
                kept.append(line)
    text = "\n".join(kept).strip()
    return (
        text if len(text) <= _FAILURES else text[:_FAILURES] + "\n[the rest of what failed is cut]"
    )


def _kept(output: str, outcome: str) -> str:
    """The step's tail, and for a step that failed, what failed above it."""
    tail = output[-_TAIL:]
    if outcome in ("passed", "not-run") or len(output) <= _TAIL:
        return tail
    section = failure_section(output)
    if not section:
        return tail
    return f"What failed:\n{section}\n\nThe last of the output:\n{tail}"


def _step(
    name: str, command: str, outcome: str, seconds: float | None, tail: str
) -> BuildStepReport:
    return BuildStepReport(
        name=name,
        command=command,
        outcome=outcome,  # type: ignore[arg-type]
        duration_seconds=None if outcome == "not-run" else round(seconds or 0.0, 3),
        log_tail=_kept(tail, outcome),
    )


def reads_database(tree: dict[str, str]) -> bool:
    """Whether the backend's own code reads MONGODB_URL, not merely declares it.

    Read from the code, because the declaration says nothing: C2 put the name
    in `.env.example` long before any code it generated read it, and code
    generated before 2026-10-01 keeps its records in memory whatever it is
    given. Tests are not the code a release runs, so they do not count.
    """
    try:
        backend = detect(tree).layout.backend_dir or ""
    except Undetectable:
        return False
    prefix = f"{backend}/src/" if backend else "src/"
    return any(
        path.startswith(prefix)
        and path.endswith(_CODE)
        and "/__tests__/" not in path
        and _READS_DATABASE.search(text) is not None
        for path, text in tree.items()
    )


def _missing_updates(lockfile: str, updates: list[DependencyUpdate]) -> list[str]:
    try:
        resolved = resolved_versions(lockfile)
    except (json.JSONDecodeError, AttributeError):
        return ["the candidate's lockfile is not a lockfile npm wrote"]
    missing = []
    for update in updates:
        workspace = posixpath.dirname(update.manifest_path)
        found = (resolved.get(workspace) or {}).get(update.package)
        if found != update.to_version:
            where = workspace or "the root"
            missing.append(
                f"{update.package} is at {found or 'nothing'} in {where}, not the included "
                f"{update.to_version}"
            )
    return missing


def verify(
    files: dict[str, str],
    layer: dict[str, str],
    *,
    candidate: str,
    included: list[DependencyUpdate],
    excluded: list[dict[str, str]],
    image: str,
    version: int,
    code_version: int,
    unmatched: tuple[str, ...] = (),
    runner: Runner = run,
    prober: Prober = probe,
    now: datetime | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> ReleaseCandidate:
    """The candidate built, booted and checked, whatever came of it."""
    tree = {**files, **layer}
    lockfile = tree.get(LOCKFILE, "")
    fingerprint_path = fingerprint_file(layer) or ""
    steps: list[BuildStepReport] = []
    smoke: list[SmokeCheck] = []
    digest: str | None = None
    served: str | None = None
    toolchain = f"docker, BuildKit, {IMAGE}"
    version_ran = runner(["docker", "version", "--format", "{{.Server.Version}}"], 30)
    if version_ran.returncode == 0:
        toolchain = f"docker {version_ran.output.strip()}, BuildKit, {IMAGE}"

    def blocked(names: list[str], commands: list[str]) -> None:
        for name, command in zip(names, commands, strict=True):
            steps.append(_step(name, command, "not-run", None, ""))

    later = ["install", "test", "image", "boot"]
    later_commands = [
        "docker build --target deps --output type=cacheonly .",
        "docker build --target test --output type=cacheonly .",
        f"docker build --label {LABEL} -t {image} .",
        f"docker run -d --memory {MEMORY} -p 127.0.0.1::PORT {image}",
    ]

    recomputed = candidate_hash(tree, fingerprint=fingerprint_path)
    if not fingerprint_path or recomputed != candidate:
        why = (
            "the layer carries no public/release.json"
            if not fingerprint_path
            else f"the files hash to {recomputed[:12]}, not the candidate {candidate[:12]}"
        )
        steps.append(_step("candidate", "sha256 over the files", "failed", 0.0, why))
        blocked(["lockfile", *later], ["read the lockfile", *later_commands])
    else:
        steps.append(
            _step("candidate", "sha256 over the files", "passed", 0.0, f"candidate {candidate}")
        )
        missing = [
            f"the included update {update_id} is not among the run's updates, so its version "
            "cannot be checked"
            for update_id in unmatched
        ] + _missing_updates(lockfile, included)
        steps.append(
            _step(
                "lockfile",
                "read the lockfile",
                "failed" if missing else "passed",
                0.0,
                "; ".join(missing) or f"{len(included)} included updates, each at its version",
            )
        )
        if missing:
            blocked(later, later_commands)
        else:
            digest, served, smoke = _build_and_boot(
                tree, image, steps, runner=runner, prober=prober, sleep=sleep
            )

    return ReleaseCandidate(
        version=version,
        generated_at=now or datetime.now(UTC),
        code_version=code_version,
        candidate_hash=candidate,
        lockfile_sha256=hashlib.sha256(lockfile.encode("utf-8")).hexdigest() if lockfile else None,
        included=[update.id for update in included] + list(unmatched),
        excluded=[ExcludedUpdate.model_validate(item) for item in excluded],
        image=image,
        image_digest=digest,
        toolchain=toolchain,
        isolation=(
            f"a container on 127.0.0.1 with {MEMORY} of memory; the build fetches packages "
            "from the registry, and runs the tests in the image's test stage"
            + (
                f"; code that reads {DATABASE_VARIABLE} boots beside a throwaway MongoDB on a "
                "private network, removed with its records afterwards"
                if reads_database(tree)
                else ""
            )
        ),
        steps=steps,
        smoke=smoke,
        fingerprint=served,
    )


def _build_and_boot(
    tree: dict[str, str],
    image: str,
    steps: list[BuildStepReport],
    *,
    runner: Runner,
    prober: Prober,
    sleep: Callable[[float], None],
) -> tuple[str | None, str | None, list[SmokeCheck]]:
    try:
        port = detect(tree).runtime
    except Undetectable:
        port = None
    container_port = port.port if port and port.port else 3000
    with tempfile.TemporaryDirectory(prefix="c4-staging-") as scratch:
        context = Path(scratch)
        for path, text in tree.items():
            target = context / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        builds = [
            ("install", ["docker", "build", "--target", "deps", "--output", "type=cacheonly"]),
            ("test", ["docker", "build", "--target", "test", "--output", "type=cacheonly"]),
            ("image", ["docker", "build", "--label", LABEL, "-t", image]),
        ]
        for index, (name, argv) in enumerate(builds):
            ran = runner([*argv, str(context)], BUILD_TIMEOUT_SECONDS)
            outcome = (
                "passed"
                if ran.returncode == 0
                else "timed-out"
                if ran.returncode == 124
                else "failed"
            )
            steps.append(_step(name, " ".join([*argv, "."]), outcome, ran.seconds, ran.output))
            if outcome != "passed":
                for later, later_argv in builds[index + 1 :]:
                    steps.append(_step(later, " ".join([*later_argv, "."]), "not-run", None, ""))
                steps.append(_step("boot", f"docker run {image}", "not-run", None, ""))
                return None, None, []

    inspected = runner(["docker", "image", "inspect", "--format", "{{.Id}}", image], 60)
    digest = inspected.output.strip() if inspected.returncode == 0 else None

    network, database = "", ""
    if reads_database(tree):
        network = f"c4-staging-{secrets.token_hex(6)}"
        database = _database(network, steps, runner=runner, sleep=sleep)
    try:
        if network and not database:
            steps.append(_step("boot", f"docker run {image}", "not-run", None, ""))
            return digest, None, []
        return _boot(
            image,
            container_port,
            network,
            steps,
            runner=runner,
            prober=prober,
            tree=tree,
            sleep=sleep,
            digest=digest,
        )
    finally:
        if database:
            runner(["docker", "rm", "-f", database], 60)
        if network:
            runner(["docker", "network", "rm", network], 60)


def _database(
    network: str,
    steps: list[BuildStepReport],
    *,
    runner: Runner,
    sleep: Callable[[float], None],
) -> str:
    """A throwaway MongoDB on its own network, answering a ping; its container id, or "" and
    the step failed with the reason."""
    command = (
        f"docker run -d --network {network} --network-alias database --memory {MEMORY} "
        f"{DATABASE_IMAGE}"
    )
    made = runner(["docker", "network", "create", "--label", LABEL, network], 60)
    if made.returncode != 0:
        steps.append(_step("database", command, "failed", made.seconds, made.output))
        return ""
    started = runner(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--label",
            LABEL,
            "--network",
            network,
            "--network-alias",
            "database",
            "--memory",
            MEMORY,
            DATABASE_IMAGE,
            # Inside 512 MB, rather than a cache sized from the whole machine's memory.
            "--wiredTigerCacheSizeGB",
            "0.25",
        ],
        300,
    )
    if started.returncode != 0:
        steps.append(_step("database", command, "failed", started.seconds, started.output))
        return ""
    container = started.output.strip().splitlines()[-1]
    began = time.monotonic()
    ping = [
        "docker",
        "exec",
        container,
        "mongosh",
        "--quiet",
        "--eval",
        "db.runCommand({ping: 1}).ok",
    ]
    while True:
        answered = runner(ping, 30)
        if answered.returncode == 0 and answered.output.strip().endswith("1"):
            steps.append(
                _step(
                    "database",
                    command,
                    "passed",
                    time.monotonic() - began,
                    f"MongoDB answered on the network {network}; the candidate reads it as "
                    f"{DATABASE_VARIABLE}={DATABASE_URL}",
                )
            )
            return container
        if time.monotonic() - began >= BOOT_WITHIN_SECONDS:
            logs = runner(["docker", "logs", container], 30).output
            steps.append(
                _step(
                    "database",
                    command,
                    "failed",
                    time.monotonic() - began,
                    f"MongoDB did not answer a ping within {BOOT_WITHIN_SECONDS}s\n{logs}",
                )
            )
            runner(["docker", "rm", "-f", container], 60)
            return ""
        sleep(1)


def _boot(
    image: str,
    container_port: int,
    network: str,
    steps: list[BuildStepReport],
    *,
    runner: Runner,
    prober: Prober,
    tree: dict[str, str],
    sleep: Callable[[float], None],
    digest: str | None,
) -> tuple[str | None, str | None, list[SmokeCheck]]:
    beside = ["--network", network, "-e", f"{DATABASE_VARIABLE}={DATABASE_URL}"] if network else []
    started = runner(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--label",
            LABEL,
            "--memory",
            MEMORY,
            *beside,
            "-p",
            f"127.0.0.1::{container_port}",
            image,
        ],
        120,
    )
    command = " ".join(
        ["docker run -d --memory", MEMORY, *beside, "-p", f"127.0.0.1::{container_port}", image]
    )
    if started.returncode != 0:
        steps.append(_step("boot", command, "failed", started.seconds, started.output))
        return digest, None, []
    container = started.output.strip().splitlines()[-1]
    try:
        mapped = runner(["docker", "port", container, f"{container_port}/tcp"], 30)
        address = mapped.output.strip().splitlines()[0] if mapped.returncode == 0 else ""
        base = f"http://{address}" if address else ""
        began = time.monotonic()
        status, body = None, ""
        while base and time.monotonic() - began < BOOT_WITHIN_SECONDS:
            status, _, body = prober(f"{base}/release.json", {"Accept": "application/json"}, 5)
            if status == 200:
                break
            sleep(1)
        waited = time.monotonic() - began
        if status != 200:
            logs = runner(["docker", "logs", container], 30).output
            steps.append(
                _step(
                    "boot",
                    command,
                    "failed",
                    waited,
                    f"/release.json did not answer within {BOOT_WITHIN_SECONDS}s\n{logs}",
                )
            )
            return digest, None, []
        steps.append(_step("boot", command, "passed", waited, f"answered on {address}"))
        try:
            served = str(json.loads(body).get("candidateHash") or "") or None
        except (json.JSONDecodeError, AttributeError):
            served = None
        smoke = [_smoke(base, "/", "text/html", prober)]
        smoke += [_smoke(base, path, "application/json", prober) for path in smoke_paths(tree)]
        return digest, served, smoke
    finally:
        runner(["docker", "rm", "-f", container], 60)


def _smoke(base: str, path: str, kind: str, prober: Prober) -> SmokeCheck:
    status, content_type, _ = prober(f"{base}{path}", {"Accept": kind}, 10)
    ok = status is not None and 200 <= status < 300 and content_type.startswith(kind)
    detail = (
        "nothing answered"
        if status is None
        else f"{status} {content_type or 'with no content type'}"
        + ("" if ok else f", where {kind} was asked for")
    )
    return SmokeCheck(path=path, status_code=status, ok=ok, detail=detail)
