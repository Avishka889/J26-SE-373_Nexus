"""Table 7: does the monitor name the state a release is really in? (FR21, proposal 3.4.4)

    uv run python -m orchestrator.deploy.table7 --repeats 3 \\
        --out services/c4-deployment-dependency/studies/epochs

The proposal's metric is "monitoring state detection accuracy", compared "with
known application states". Each episode puts a small release into a known state
on purpose, watches it for one window with the monitor's own probe loop,
requests and rule (`observe`, `conclude`, `health-rule/1` at the thresholds
every report records), and keeps what the monitor concluded beside what was
known. Every episode starts a fresh container on local Docker and removes it
after, so no episode inherits another's state.

**The watched app is not the generated app, on purpose.** The generated
backend's handlers take about a millisecond of CPU, so starving it to 2 percent
of a CPU leaves it fast, and calling that episode `degraded` would be a label
the app does not live up to. The watched app spends a fixed amount of CPU on
`/tasks` (`WORK_ITERATIONS` rounds of PBKDF2), which answers in about 80 ms
free and in several seconds at 2 percent of a CPU, as measured on this machine
before the study. It reads `release.json` on every request, so a different
candidate can be put under it.

**Idle spells are given, not waited for.** A local container never sleeps, so
the conditions that follow an idle spell give the monitor 20 idle minutes, as a
release last probed 20 minutes ago would, and a frozen container (`docker
pause`) thawed a few seconds into the first request stands for a free host
waking. The window is shorter than the product's (5 rounds 2 s apart, where the
product watches 20 rounds 30 s apart); the rule reads rounds, not wall time.
"""

import argparse
import asyncio
import json
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sdlc_contracts import HEALTH_RULE, HealthState, HealthThresholds

from .adapters.checks import probe
from .adapters.local_docker import docker
from .monitor import conclude, observe

LANE = "table-7"
NODE = (
    "node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c"
)
WORK_ITERATIONS = 250_000
VERIFIED = "7" * 64
ANOTHER = "8" * 64
IDLE_SPELL = 1200.0
THAW_AFTER_SECONDS = 5.0
ROUNDS, INTERVAL = 5, 2.0

#: The states a window can conclude, in the order the table prints them.
STATES: tuple[HealthState, ...] = ("healthy", "cold-start", "degraded", "down", "unknown")

REQUESTS = [
    ("/release.json", "application/json"),
    ("/", "text/html"),
    ("/tasks", "application/json"),
]

SERVER = """import { createServer } from "node:http";
import { readFileSync } from "node:fs";
import { pbkdf2Sync } from "node:crypto";

const WORK = Number(process.env.WORK_ITERATIONS ?? "0");
createServer((request, response) => {
  if (request.url === "/release.json") {
    response.writeHead(200, { "content-type": "application/json" });
    response.end(readFileSync("/app/release.json"));
  } else if (request.url === "/tasks") {
    if (WORK) pbkdf2Sync("task", "salt", WORK, 32, "sha256");
    response.writeHead(200, { "content-type": "application/json" });
    response.end("[]");
  } else {
    response.writeHead(200, { "content-type": "text/html" });
    response.end("<!doctype html><title>watched</title>");
  }
}).listen(3001, "0.0.0.0");
"""

Hook = Callable[[str], Awaitable[None]]


@dataclass(frozen=True)
class Condition:
    """One known state and how it is produced."""

    name: str
    known: HealthState
    #: How it is put into that state, in words, for the table.
    how: str
    idle_seconds: float | None = None
    #: Run on the container before the window opens.
    before: tuple[tuple[str, ...], ...] = ()
    #: Docker commands run before a given round (1 is the second round).
    between: dict[int, tuple[tuple[str, ...], ...]] = field(default_factory=dict)
    #: Seconds into the window at which a frozen container is thawed.
    thaw_after: float | None = None


CONDITIONS: tuple[Condition, ...] = (
    Condition("healthy", "healthy", "nothing injected"),
    Condition(
        "healthy after an idle spell",
        "healthy",
        "nothing injected; 20 idle minutes given",
        idle_seconds=IDLE_SPELL,
    ),
    Condition(
        "waking after an idle spell",
        "cold-start",
        f"frozen, thawed {THAW_AFTER_SECONDS:g} s into the first request; 20 idle minutes given",
        idle_seconds=IDLE_SPELL,
        before=(("pause",),),
        thaw_after=THAW_AFTER_SECONDS,
    ),
    Condition(
        "frozen with no idle spell",
        "degraded",
        f"frozen, thawed {THAW_AFTER_SECONDS:g} s into the first request; not idle",
        before=(("pause",),),
        thaw_after=THAW_AFTER_SECONDS,
    ),
    Condition(
        "throttled",
        "degraded",
        "2 percent of a CPU (`throttle-cpu`)",
        before=(("update", "--cpus", "0.02"),),
    ),
    Condition(
        "throttled after an idle spell",
        "degraded",
        "2 percent of a CPU; 20 idle minutes given",
        idle_seconds=IDLE_SPELL,
        before=(("update", "--cpus", "0.02"),),
    ),
    Condition(
        "flapping",
        "degraded",
        "stopped for the second round, started before the third",
        between={1: (("stop", "-t", "1"),), 2: (("start",),)},
    ),
    Condition("stopped", "down", "stopped (`stop-container`)", before=(("stop", "-t", "1"),)),
    Condition(
        "stopped after an idle spell",
        "down",
        "stopped; 20 idle minutes given",
        idle_seconds=IDLE_SPELL,
        before=(("stop", "-t", "1"),),
    ),
    Condition(
        "another candidate",
        "down",
        "serves a candidate other than the verified one",
        before=(
            (
                "exec",
                "sh",
                "-c",
                f'printf \'{{"candidateHash": "{ANOTHER}"}}\' > /app/release.json',
            ),
        ),
    ),
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def build_image() -> tuple[str, str]:
    """The watched app's image, labelled with the study's lane; its tag and digest."""
    with tempfile.TemporaryDirectory() as directory:
        context = Path(directory)
        (context / "server.mjs").write_text(SERVER)
        (context / "release.json").write_text(json.dumps({"candidateHash": VERIFIED}))
        (context / "Dockerfile").write_text(
            f"FROM {NODE}\nWORKDIR /app\nCOPY --chown=1000:1000 server.mjs release.json /app/\n"
            'EXPOSE 3001\nUSER 1000:1000\nCMD ["node", "server.mjs"]\n'
        )
        tag = "sdlc-c4-table7:watched"
        subprocess.run(
            ["docker", "build", "-q", "--label", f"sdlc.c4.lane={LANE}", "-t", tag, str(context)],
            check=True,
            capture_output=True,
        )
    digest = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", tag],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return tag, digest


async def _answering(base: str, within: float = 30.0) -> None:
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        status, _, _ = await probe(
            f"{base}/release.json", {"Accept": "application/json"}, timeout=2
        )
        if status == 200:
            return
        await asyncio.sleep(0.2)
    raise RuntimeError(f"the watched app at {base} did not answer within {within:g}s")


async def _docker(command: tuple[str, ...], container: str) -> None:
    verb, *rest = command
    # `exec` names its container before the command it runs; the others after their flags.
    args = [verb, container, *rest] if verb == "exec" else [verb, *rest, container]
    code, output = await docker(args)
    if code != 0:
        raise RuntimeError(f"docker {' '.join(args)} failed: {output}")


async def _start(image: str) -> tuple[str, str]:
    """A fresh watched app on a free port; its container name and address.

    A port the operating system called free can still be held by Docker a moment
    after another container let go of it, and a `docker run` that fails to bind
    leaves a created container behind. So each attempt is named, removed when it
    fails, and tried again on another port.
    """
    failures = []
    for _ in range(3):
        port = _free_port()
        name = f"sdlc-c4-table7-{uuid.uuid4().hex[:12]}"
        code, output = await docker(
            [
                "run",
                "-d",
                "--name",
                name,
                "--label",
                f"sdlc.c4.lane={LANE}",
                "--memory",
                "512m",
                "-e",
                f"WORK_ITERATIONS={WORK_ITERATIONS}",
                "-p",
                f"127.0.0.1:{port}:3001",
                image,
            ]
        )
        if code == 0:
            return name, f"http://127.0.0.1:{port}"
        await docker(["rm", "-f", name])
        failures.append(output)
    raise RuntimeError(f"docker run failed three times: {failures[-1]}")


async def episode(condition: Condition, image: str, *, repeat: int) -> dict[str, Any]:
    """Put one container into the condition's state, watch it for one window, keep both."""
    container, base = await _start(image)
    thresholds = HealthThresholds()
    try:
        await _answering(base)
        for command in condition.before:
            await _docker(command, container)

        async def before_round(index: int) -> None:
            for command in condition.between.get(index, ()):
                await _docker(command, container)
                if command[0] == "start":
                    await _answering(base)

        thaw = (
            asyncio.create_task(_thaw(container, condition.thaw_after))
            if condition.thaw_after is not None
            else None
        )
        waking = (
            condition.idle_seconds is not None
            and condition.idle_seconds >= thresholds.cold_start_idle_seconds
        )
        observed = await observe(
            base,
            REQUESTS,
            rounds=ROUNDS,
            interval=INTERVAL,
            wake_timeout=thresholds.cold_start_first_ms / 1000 if waking else None,
            before_round=before_round,
        )
        if thaw is not None:
            await thaw
        detected, evidence = conclude(
            observed.rounds,
            expected=VERIFIED,
            idle_seconds=condition.idle_seconds,
            thresholds=thresholds,
        )
    finally:
        await docker(["rm", "-f", container])
    return {
        "condition": condition.name,
        "repeat": repeat,
        "known": condition.known,
        "detected": detected,
        "correct": detected == condition.known,
        "evidence": evidence,
        "idleSeconds": condition.idle_seconds,
        "rounds": [
            {"ok": ok, "slowestMs": None if ms is None else round(ms, 1), "served": served}
            for ok, ms, served in observed.rounds
        ],
        "seconds": round((observed.ended - observed.started).total_seconds(), 1),
    }


async def _thaw(container: str, after: float) -> None:
    await asyncio.sleep(after)
    await docker(["unpause", container])


def confusion(episodes: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Known state by detected state, every cell present."""
    matrix = {known: dict.fromkeys(STATES, 0) for known in STATES}
    for item in episodes:
        matrix[item["known"]][item["detected"]] += 1
    return matrix


def scores(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Accuracy over all episodes, and precision and recall per state that was known or found."""
    matrix = confusion(episodes)
    total = len(episodes)
    correct = sum(matrix[state][state] for state in STATES)
    per_state: dict[str, dict[str, Any]] = {}
    for state in STATES:
        support = sum(matrix[state].values())
        found = sum(matrix[known][state] for known in STATES)
        if not support and not found:
            continue
        hits = matrix[state][state]
        per_state[state] = {
            "support": support,
            "detected": found,
            "precision": hits / found if found else None,
            "recall": hits / support if support else None,
        }
    return {
        "total": total,
        "correct": correct,
        "accuracy": correct / total if total else None,
        "confusion": matrix,
        "perState": per_state,
    }


def _docker_version() -> str:
    done = subprocess.run(
        ["docker", "version", "--format", "{{.Server.Version}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return done.stdout.strip() or "unknown"


def header(commit: str, image_digest: str, repeats: int, *, today: date) -> dict[str, Any]:
    return {
        "label": "Table 7: monitoring state detection",
        "date": today.isoformat(),
        "commit": commit,
        "rule": HEALTH_RULE,
        "thresholds": HealthThresholds().model_dump(by_alias=True),
        "window": {"rounds": ROUNDS, "intervalSeconds": INTERVAL},
        "requests": [path for path, _ in REQUESTS],
        "repeats": repeats,
        "watchedApp": {
            "base": NODE,
            "imageDigest": image_digest,
            "workIterations": WORK_ITERATIONS,
        },
        "docker": _docker_version(),
        "conditions": [
            {"name": item.name, "known": item.known, "how": item.how} for item in CONDITIONS
        ],
    }


async def run(repeats: int, *, commit: str, now: datetime | None = None) -> dict[str, Any]:
    """Every condition, `repeats` times, interleaved so no condition runs in one warm burst."""
    now = now or datetime.now(UTC)
    image, digest = build_image()
    episodes = []
    try:
        for repeat in range(1, repeats + 1):
            for condition in CONDITIONS:
                episodes.append(await episode(condition, image, repeat=repeat))
    finally:
        await docker(["rmi", "-f", image])
    return {
        "study": header(commit, digest, repeats, today=now.date()),
        "episodes": episodes,
        **scores(episodes),
    }


def render_table(record: dict[str, Any]) -> str:
    study = record["study"]
    window = study["window"]
    lines = [
        f"### {study['label']}, {study['date']}",
        "",
        f"Commit `{study['commit']}`. {record['total']} episodes: "
        f"{len(study['conditions'])} conditions, {study['repeats']} each, on local Docker "
        f"{study['docker']}. Each one window of {window['rounds']} rounds "
        f"{window['intervalSeconds']:g} s apart, classified by `{study['rule']}` at the "
        "thresholds every report records.",
        "",
        "| known \\ detected | " + " | ".join(STATES) + " |",
        "|---|" + "---|" * len(STATES),
    ]
    for known in STATES:
        row = record["confusion"][known]
        if sum(row.values()):
            lines.append(f"| {known} | " + " | ".join(str(row[state]) for state in STATES) + " |")
    lines += ["", "| condition | how | known | detected | correct |", "|---|---|---|---|---|"]
    for condition in study["conditions"]:
        mine = [item for item in record["episodes"] if item["condition"] == condition["name"]]
        detected = ", ".join(item["detected"] for item in mine)
        right = sum(item["correct"] for item in mine)
        lines.append(
            f"| {condition['name']} | {condition['how']} | {condition['known']} | {detected} | "
            f"{right} of {len(mine)} |"
        )
    accuracy = record["accuracy"]
    lines += [
        "",
        f"Accuracy: {record['correct']} of {record['total']}"
        + (f" ({accuracy:.0%})." if accuracy is not None else "."),
    ]
    return "\n".join(lines) + "\n"


def _commit() -> str:
    done = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False
    )
    return done.stdout.strip() or "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m orchestrator.deploy.table7",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--commit", default=None)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    record = asyncio.run(run(args.repeats, commit=args.commit or _commit()))
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        target = args.out / "table-7-monitoring-state-detection.json"
        target.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(render_table(record))
    return 0


if __name__ == "__main__":
    sys.exit(main())
