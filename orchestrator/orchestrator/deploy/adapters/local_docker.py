"""The local release target: the verified image, run in a container on this machine.

The dev loop and the controlled failure scenarios release here, so nothing is
spent in the cloud until a person asks for it. Production is one container per
project, published on that project's own release port, on loopback only.

- **start** runs the image staging verified, by its id, on a spare loopback port
  beside the running release, for the checks to ask before any traffic moves.
- **switch** is the one step that moves traffic: the running release's container
  is removed, which frees the project's release port, and the image is started
  on it. A failure between the two leaves nothing serving, which the saga treats
  as traffic having moved: a person decides the rollback (FR20).

**A release port per project.** Every project's release used to bind the one
configured port. A second project's first release then failed at its switch, a
traffic step, and waited on a rollback with nothing to restore, and a
monitoring window on one project could read another's fingerprint. A project
now keeps the port its release container was started on, or, when that
container is gone, the one its last verified local release served on. A
project with neither takes the first port, from the configured one up, that no
other project's release claims and nothing holds. The port is checked before
anything is removed, so a switch that cannot have it moves nothing.

Every container carries labels naming its lane, project, deployment, step and
role, and a release its port, so a step a crash interrupted is found and
adopted rather than started twice, a restart can reap what staging and checks
left behind without touching a release, tests run in their own lane on their
own ports, and a deleted project's containers go with it.
"""

import asyncio
import json
import re
import socket
import subprocess
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit

from ...saga.executor import StepContext, StepFailed, StepResult

MEMORY = "512m"
DOCKER_TIMEOUT_SECONDS = 180
#: The waits before a release's start is tried again when Docker has not freed
#: or exposed its port yet. Docker Desktop answered "ports are not available:
#: ... /forwards/expose returned unexpected status: 500" for a port nothing
#: held, and a port the replaced release held can take a moment to come free.
PORT_RETRY_SECONDS = (0.5, 1.0, 2.0)
#: How many release ports, from the configured one up, are handed out, one per
#: project, before a switch says none is free.
PORT_SPAN = 200

#: How the adapter asks Docker something: the arguments, then the exit code and
#: what it printed.
Docker = Callable[[list[str]], Awaitable[tuple[int, str]]]

#: A host port in `docker ps`'s ports column (`127.0.0.1:18080->3001/tcp`), or
#: a range of them.
_PUBLISHED = re.compile(r":(\d+)(?:-(\d+))?->")

#: Docker refusing a port it may have ready a moment later.
_PORT_NOT_READY = re.compile(
    r"port is already allocated|ports are not available|address already in use", re.IGNORECASE
)

#: The full id `docker run -d` prints, which it prints for a container it
#: created even when it could not start it.
_CONTAINER_ID = re.compile(r"^[0-9a-f]{64}$")


async def docker(args: list[str], *, timeout: float = DOCKER_TIMEOUT_SECONDS) -> tuple[int, str]:
    def call() -> tuple[int, str]:
        try:
            done = subprocess.run(
                ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False
            )
        except FileNotFoundError:
            return 127, "docker is not installed"
        except subprocess.TimeoutExpired:
            return 124, f"docker {args[0]} timed out after {timeout:.0f}s"
        return done.returncode, (done.stdout + done.stderr).strip()

    return await asyncio.to_thread(call)


def bindable(port: int) -> bool:
    """Whether nothing on this machine listens on a loopback port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def port_of(url: str | None) -> int | None:
    """The port a recorded local address names, when it names one."""
    if not url:
        return None
    try:
        return urlsplit(url if "://" in url else f"http://{url}").port
    except ValueError:
        return None


class LocalDocker:
    def __init__(
        self,
        *,
        release_port: int,
        lane: str = "release",
        run: Docker | None = None,
        free: Callable[[int], bool] = bindable,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        #: The first release port handed out; each project takes its own from here up.
        self.release_port = release_port
        self.lane = lane
        self._run = run
        self._free = free
        self._sleep = sleep
        # A port is chosen and taken within one switch, and two projects
        # switching at once could otherwise both choose the same one.
        self._switching = asyncio.Lock()

    async def _docker(self, args: list[str]) -> tuple[int, str]:
        return await (self._run or docker)(args)

    def _labels(self, ctx: StepContext, role: str, port: int | None = None) -> list[str]:
        labels = {
            "sdlc.c4.lane": self.lane,
            "sdlc.c4.project": ctx.deployment["project_id"],
            "sdlc.c4.deployment": str(ctx.deployment["id"]),
            "sdlc.c4.step": ctx.step.id,
            "sdlc.c4.role": role,
        }
        if port is not None:
            labels["sdlc.c4.port"] = str(port)
        return [part for key, value in labels.items() for part in ("--label", f"{key}={value}")]

    def _image(self, ctx: StepContext) -> str:
        """The image this deployment starts: the candidate's, or for a rollback the verified one's."""
        if ctx.deployment["kind"] == "rollback":
            image = ctx.previous.image_digest if ctx.previous else None
        else:
            image = ctx.candidate.image_digest if ctx.candidate else None
        if not image:
            raise StepFailed("there is no verified image to start: staging recorded no digest")
        return image

    async def _container_port(self, image: str) -> int:
        code, output = await self._docker(
            ["image", "inspect", "--format", "{{json .Config.ExposedPorts}}", image]
        )
        if code != 0:
            raise StepFailed(f"the image {image[:19]} is not on this machine: {output}")
        ports = [key.split("/")[0] for key in (json.loads(output or "null") or {})]
        if not ports:
            raise StepFailed(f"the image {image[:19]} exposes no port to publish")
        return int(ports[0])

    async def _address(self, container: str, port: int) -> str:
        code, output = await self._docker(["port", container, f"{port}/tcp"])
        if code != 0 or not output:
            raise StepFailed(f"the container published no port: {output}")
        return output.splitlines()[0].strip()

    async def _claims(self) -> dict[int, str]:
        """Each port this lane's releases were started on, and whose release it is.

        Stopped ones too: a release a fault stopped is still that project's,
        and its port is not another project's to take.
        """
        code, output = await self._docker(
            [
                "ps",
                "-a",
                "--filter",
                f"label=sdlc.c4.lane={self.lane}",
                "--filter",
                "label=sdlc.c4.role=release",
                "--format",
                '{{.ID}} {{.Label "sdlc.c4.port"}} {{.Label "sdlc.c4.project"}}',
            ]
        )
        claims: dict[int, str] = {}
        for line in output.splitlines() if code == 0 else []:
            parts = line.split()
            if len(parts) == 3 and parts[1].isdigit():
                claims[int(parts[1])] = parts[2]
        return claims

    async def _published(self) -> dict[int, set[str]]:
        """Every host port a running container publishes, and whose containers they are.

        A container no project's labels name is held by "", which is nobody a
        switch may take a port from.
        """
        code, output = await self._docker(
            ["ps", "--format", '{{.ID}}|{{.Label "sdlc.c4.project"}}|{{.Ports}}']
        )
        held: dict[int, set[str]] = {}
        for line in output.splitlines() if code == 0 else []:
            _, project, ports = [*line.split("|", 2), "", ""][:3]
            for match in _PUBLISHED.finditer(ports):
                first = int(match.group(1))
                for port in range(first, int(match.group(2) or first) + 1):
                    held.setdefault(port, set()).add(project.strip())
        return held

    async def _port_for(self, ctx: StepContext) -> tuple[int, str]:
        """This project's release port, and where it came from.

        Its own when it has one it can still have: the port its release was
        started on, or, with that container gone, the one its last verified
        local release served on. Otherwise the first port from the configured
        one up that no release claims, no container publishes and nothing else
        listens on. Refused as having moved nothing when there is none.
        """
        project = ctx.deployment["project_id"]
        claims = await self._claims()
        held = await self._published()

        def usable(port: int) -> bool:
            holders = held.get(port, set())
            if holders - {project}:
                return False
            # Its own running release holds it until the switch removes it.
            return bool(holders) or self._free(port)

        own = [(port, "its own port") for port in sorted(claims) if claims[port] == project]
        previous = ctx.previous
        recorded = port_of(previous.url) if previous and previous.target == "local" else None
        if recorded and claims.get(recorded, project) == project:
            own.append((recorded, "the port its last verified release served on"))
        for port, said in own:
            if usable(port):
                return port, said
        for port in range(self.release_port, self.release_port + PORT_SPAN):
            if port not in claims and usable(port):
                return port, "the first release port free"
        raise StepFailed(
            f"no release port from {self.release_port} to {self.release_port + PORT_SPAN - 1} "
            "is free on this machine, so nothing was changed",
            moved=False,
        )

    async def execute(self, ctx: StepContext) -> StepResult:
        if ctx.step.id in ("start", "start-verified"):
            return await self._start(ctx)
        if ctx.step.id in ("switch", "switch-back"):
            return await self._switch(ctx)
        raise StepFailed(f"the local target has no step called {ctx.step.id}")

    async def _start(self, ctx: StepContext) -> StepResult:
        image = self._image(ctx)
        port = await self._container_port(image)
        command = [
            "run",
            "-d",
            *self._labels(ctx, "check"),
            "--memory",
            MEMORY,
            "-p",
            f"127.0.0.1::{port}",
            image,
        ]
        code, output = await self._docker(command)
        if code != 0:
            raise StepFailed(f"the image did not start: {output}", log=output)
        container = output.splitlines()[-1]
        address = await self._address(container, port)
        return StepResult(
            resource={"container": container, "address": address, "image": image, "port": port},
            log=f"started {image[:19]} as {container[:12]} on {address}",
            command="docker " + " ".join(command),
        )

    async def _switch(self, ctx: StepContext) -> StepResult:
        image = self._image(ctx)
        port = await self._container_port(image)
        async with self._switching:
            # Chosen before anything is removed: a port another project holds
            # refuses here, while this project's release still serves.
            release, said = await self._port_for(ctx)
            code, output = await self._docker(
                [
                    "ps",
                    "-aq",
                    "--filter",
                    f"label=sdlc.c4.lane={self.lane}",
                    "--filter",
                    f"label=sdlc.c4.project={ctx.deployment['project_id']}",
                    "--filter",
                    "label=sdlc.c4.role=release",
                ]
            )
            running = output.split() if code == 0 else []
            replaced: list[dict[str, Any]] = []
            for container in running:
                _, image_of = await self._docker(["inspect", "--format", "{{.Image}}", container])
                await self._docker(["rm", "-f", container])
                replaced.append({"container": container, "image": image_of})
            command = [
                "run",
                "-d",
                *self._labels(ctx, "release", release),
                "--memory",
                MEMORY,
                "-p",
                f"127.0.0.1:{release}:{port}",
                image,
            ]
            code, output = await self._docker(command)
            for wait in PORT_RETRY_SECONDS:
                if code == 0 or not _PORT_NOT_READY.search(output):
                    break
                # The run created its container even so, and a release that
                # never started is not one to keep beside the next attempt.
                created = output.splitlines()[0].strip()
                if _CONTAINER_ID.match(created):
                    await self._docker(["rm", "-f", created])
                await self._sleep(wait)
                code, output = await self._docker(command)
        if code != 0:
            raise StepFailed(
                f"the release port {release} was freed and the new release did not start on "
                f"it: {output}",
                log=output,
            )
        container = output.splitlines()[-1]
        checked = next(
            (
                earlier.get("container")
                for step_id, earlier in ctx.earlier.items()
                if step_id in ("start", "start-verified")
            ),
            None,
        )
        if checked:
            await self._docker(["rm", "-f", checked])
        return StepResult(
            resource={
                "container": container,
                "address": f"127.0.0.1:{release}",
                "image": image,
                "replaced": replaced,
            },
            log=(
                f"moved 127.0.0.1:{release} ({said}) to {container[:12]}"
                + (f", replacing {len(replaced)} container(s)" if replaced else "")
            ),
            command="docker " + " ".join(command),
        )

    async def compensate(self, ctx: StepContext) -> None:
        container = (ctx.resource or {}).get("container")
        if container:
            await self._docker(["rm", "-f", container])

    async def find_existing(self, ctx: StepContext) -> dict[str, Any] | None:
        code, output = await self._docker(
            [
                "ps",
                "-q",
                "--filter",
                f"label=sdlc.c4.deployment={ctx.deployment['id']}",
                "--filter",
                f"label=sdlc.c4.step={ctx.step.id}",
            ]
        )
        found = output.split() if code == 0 else []
        if not found:
            return None
        image = self._image(ctx)
        port = await self._container_port(image)
        return {
            "container": found[0],
            "address": await self._address(found[0], port),
            "image": image,
        }


async def reap_leftovers(lane: str = "release") -> int:
    """Remove what staging and the checks left behind; never a release."""
    removed = 0
    for selector in ("label=sdlc.c4.lane=staging", "label=sdlc.c4.role=check"):
        filters = ["--filter", selector]
        if selector.endswith("role=check"):
            filters += ["--filter", f"label=sdlc.c4.lane={lane}"]
        code, output = await docker(["ps", "-aq", *filters])
        for container in output.split() if code == 0 else []:
            await docker(["rm", "-f", container])
            removed += 1
    return removed


async def remove_project(project_id: str, *, run: Docker | None = None) -> int:
    """Remove every container a deleted project left on this machine, its release too.

    Nothing else would ever come back for them once its rows are gone, and a
    release kept its port from every project after it.
    """
    ask = run or docker
    code, output = await ask(["ps", "-aq", "--filter", f"label=sdlc.c4.project={project_id}"])
    removed = 0
    for container in output.split() if code == 0 else []:
        await ask(["rm", "-f", container])
        removed += 1
    return removed
