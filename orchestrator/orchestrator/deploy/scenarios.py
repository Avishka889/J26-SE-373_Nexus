"""Controlled failures, injected into a local release on purpose and recorded as such.

    uv run python -m orchestrator.deploy.scenarios inject stop-container --project p_...
    uv run python -m orchestrator.deploy.scenarios clear stop-container --project p_...

The rollback guard and the monitor are only as good as the failures they have
been shown to catch, so each scenario is named, applied to the project's running
local release container, and written on the deployment that container belongs
to (its own `sdlc.c4.deployment` label, not a guess from the ledger), so no
metric ever counts an injected failure as an organic one (Table 7).

- `stop-container`: the release stops answering at all (down);
- `throttle-cpu`: the release is starved to 2 percent of a CPU (degraded);
- `pause`: the release is frozen, and answers nothing until it is unpaused.

A scenario acts only on the local target's own containers, found by their
labels; it never touches a cloud release.
"""

import argparse
import asyncio
import sys
import uuid

from ..config import get_settings
from ..db import store
from ..db.pool import create_app_pool
from .adapters.local_docker import docker

SCENARIOS = {
    "stop-container": (["stop"], ["start"]),
    "throttle-cpu": (["update", "--cpus", "0.02"], ["update", "--cpus", "0"]),
    "pause": (["pause"], ["unpause"]),
}


async def release_container(project_id: str, lane: str) -> str:
    code, output = await docker(
        [
            "ps",
            "-aq",
            "--filter",
            f"label=sdlc.c4.lane={lane}",
            "--filter",
            f"label=sdlc.c4.project={project_id}",
            "--filter",
            "label=sdlc.c4.role=release",
        ]
    )
    found = output.split() if code == 0 else []
    if not found:
        raise LookupError(f"project {project_id} has no local release container in lane {lane}")
    return found[0]


async def apply(project_id: str, scenario: str, *, lane: str, clear: bool = False) -> str:
    """Inject (or clear) one scenario on the project's release container; its id."""
    if scenario not in SCENARIOS:
        raise KeyError(f"no scenario called {scenario}: {', '.join(SCENARIOS)}")
    container = await release_container(project_id, lane)
    command = SCENARIOS[scenario][1 if clear else 0]
    code, output = await docker([*command, container])
    if code != 0:
        raise RuntimeError(f"docker {' '.join(command)} failed: {output}")
    return container


async def deployment_of(container: str) -> uuid.UUID:
    """The deployment a release container was started by, from its own label."""
    code, output = await docker(
        ["inspect", "--format", '{{index .Config.Labels "sdlc.c4.deployment"}}', container]
    )
    if code != 0:
        raise LookupError(f"docker inspect failed on {container[:12]}: {output.strip()}")
    try:
        return uuid.UUID(output.strip())
    except ValueError as exc:
        raise LookupError(f"container {container[:12]} names no deployment") from exc


async def inject(pool, project_id: str, scenario: str, *, lane: str) -> str:
    """Inject a scenario and record it on the deployment whose container it hit."""
    container = await release_container(project_id, lane)
    deployment_id = await deployment_of(container)
    async with pool.connection() as conn:
        release = await store.get_deployment(conn, deployment_id)
    if release is None or release["project_id"] != project_id:
        raise LookupError(f"container {container[:12]} belongs to no deployment of {project_id}")
    await apply(project_id, scenario, lane=lane)
    async with pool.connection() as conn:
        await store.set_fault_injected(conn, release["id"], scenario)
        await store.post_thread_message(
            conn,
            project_id,
            kind="system",
            author="platform",
            content=(
                f"A controlled failure was injected into deploy version "
                f"{release['deploy_version']}: {scenario}."
            ),
            stage_id="monitoring",  # type: ignore[arg-type]
        )
    return container


async def _main(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m orchestrator.deploy.scenarios",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("action", choices=["inject", "clear"])
    parser.add_argument("scenario", choices=list(SCENARIOS))
    parser.add_argument("--project", required=True)
    args = parser.parse_args(argv)
    lane = get_settings().c4_local_lane
    try:
        if args.action == "clear":
            container = await apply(args.project, args.scenario, lane=lane, clear=True)
            print(f"cleared {args.scenario} on {container[:12]}")
            return 0
        # Refused here, before any connection, when there is nothing to inject into.
        await release_container(args.project, lane)
        pool = create_app_pool(get_settings().database_url, max_size=1)
        await pool.open(wait=True)
        try:
            container = await inject(pool, args.project, args.scenario, lane=lane)
        finally:
            await pool.close()
    except (LookupError, RuntimeError) as refused:
        print(f"refused: {refused}", file=sys.stderr)
        return 2
    print(f"injected {args.scenario} into {container[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(None)))
