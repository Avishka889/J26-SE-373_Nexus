"""The phase's newest full run, as every snapshot reports it."""

from psycopg import AsyncConnection
from sdlc_contracts import RunStatus

from ..components import spec_for, where_it_stopped
from ..db import store

#: For a failed row written before every failure path recorded its reason. A
#: snapshot that refused to load over it would hide the whole phase.
UNRECORDED = "The run stopped without recording why."


async def run_status(conn: AsyncConnection, project_id: str, *, component: str) -> RunStatus | None:
    row = await store.latest_full_run(conn, project_id, component=component)
    if row is None:
        return None
    failed = row["state"] == "failed"
    return RunStatus(
        id=str(row["id"]),
        state=row["state"],
        version=int(row["requirements_version"]),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        error=((row["error"] or "").strip() or UNRECORDED) if failed else None,
        stopped_at=await stopped_at(conn, project_id, component) if failed else None,
        model=row.get("model"),
        thinking=row.get("thinking"),
    )


async def stopped_at(conn: AsyncConnection, project_id: str, component: str) -> str:
    """Where the phase's stopped run stopped, read from its stages as they stand."""
    spec = spec_for(component)
    statuses = {
        row["stage_id"]: row["status"] for row in await store.stage_states(conn, project_id)
    }
    pending = [stage for stage in spec.stage_ids if statuses.get(stage, "pending") == "pending"]
    return where_it_stopped(spec, statuses, pending)
