"""The saga runner: finds deployments to carry out, and carries each out once at a time.

The run supervisor's pattern, for deployments: a handover writes a `pending`
row and may hand its id straight to a worker; the poller finds anything that was
not handed over, including a deployment whose worker died mid step (its
heartbeat stops), so a restart carries on rather than leaving it half done. The
executor's step records make carrying on safe.

Before any work the deployment's authorisation is asked again. A release is
authorised by what its row recorded: the gate decision (who, which gate, the go
ahead) or the standing policy, and the release guards must still pass with that.
A row that records no authorisation is refused outright.
"""

import asyncio
import contextlib
import logging
import uuid
from typing import Any

from psycopg_pool import AsyncConnectionPool
from sdlc_contracts import Blocker

from ..db import store
from ..deploy import guards
from .executor import Adapter, Authorise, run_deployment

log = logging.getLogger(__name__)

POLL_SECONDS = 2.0

#: What a release's authorisation must name, per kind.
_REQUIRED = {
    "gate": ("by", "gateId"),
    "policy": ("policy", "by"),
    "rollback": ("by", "deploymentId", "fromVersion"),
}


async def authorise_release(conn: Any, row: store.Row) -> list[Blocker]:
    """The guards again, under the authorisation the row recorded."""
    authorised = row.get("authorised") or {}
    kind = authorised.get("kind")
    if kind not in _REQUIRED or any(not authorised.get(name) for name in _REQUIRED[kind]):
        return [Blocker(code="AUTH", message="the deployment records no authorisation to act on")]
    if row["kind"] != "release":
        return []
    project = await store.project_without_owner_check(conn, row["project_id"])
    if project is None:
        return [Blocker(code="AUTH", message="the project no longer exists")]
    facts = await guards.gather(
        conn,
        row["project_id"],
        owner=project["owner_id"],
        deploy_version=row["deploy_version"],
        target=row["target"],
        test_version=int(authorised.get("testVersion") or 0),
        go_ahead=bool(authorised.get("goAhead")),
    )
    return guards.release_blockers(facts)


class SagaRunner:
    def __init__(
        self,
        *,
        pool: AsyncConnectionPool,
        adapters: dict[str, Adapter],
        authorise: Authorise = authorise_release,
        workers: int = 1,
        poll_seconds: float = POLL_SECONDS,
    ) -> None:
        self._pool = pool
        self._adapters = adapters
        self._authorise = authorise
        self._worker_count = workers
        self._poll_seconds = poll_seconds
        self._queue: asyncio.Queue[uuid.UUID] = asyncio.Queue()
        self._tasks: list[asyncio.Task[None]] = []
        self._inflight: set[uuid.UUID] = set()

    async def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._worker(i), name=f"saga-worker-{i}")
            for i in range(self._worker_count)
        ]
        self._tasks.append(asyncio.create_task(self._poller(), name="saga-poller"))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()

    def submit(self, deployment_id: uuid.UUID) -> None:
        """Hand a deployment straight to a worker, skipping the poll delay."""
        self._queue.put_nowait(deployment_id)

    async def advance(self, deployment_id: uuid.UUID) -> str | None:
        return await run_deployment(
            self._pool, deployment_id, adapters=self._adapters, authorise=self._authorise
        )

    async def _poller(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._poll_seconds)
                async with self._pool.connection() as conn:
                    rows = await store.claimable_deployments(conn)
                for row in rows:
                    if row["id"] not in self._inflight:
                        self._queue.put_nowait(row["id"])
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("the saga poller failed; it will try again")

    async def _worker(self, index: int) -> None:
        while True:
            deployment_id = await self._queue.get()
            if deployment_id in self._inflight:
                self._queue.task_done()
                continue
            self._inflight.add(deployment_id)
            try:
                await self.advance(deployment_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("deployment %s failed in saga worker %s", deployment_id, index)
            finally:
                self._inflight.discard(deployment_id)
                self._queue.task_done()
